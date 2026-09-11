"""Recipient-bound organization invitations (US-29, chunk 07B).

An invitation is a standing grant of access to another tenant's data, so it is
treated as a credential:

- **Bound to a recipient, not to a link.** Acceptance requires the accepting
  account to hold a *verified* identifier equal to the invited address. A
  forwarded link, a leaked mailbox archive or a guessed id is therefore worth
  nothing on its own, and an *unverified* claim on the address is worth nothing
  either -- claiming must never be as good as proving.
- **Single-use and expiring**, both enforced by the database. Acceptance claims
  the row with `UPDATE ... WHERE status = 'pending'`, so two simultaneous clicks
  cannot both produce a membership; expiry is exclusive at the boundary, the
  same rule chunk 06 applies to identity tokens.
- **Never an escalation.** The inviter must hold `MEMBER_INVITE` *and* be
  allowed to grant the role in question, so "invite" cannot become a one-step
  route to owner.
"""

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, and_, or_, update
from sqlmodel import Session, col, select

from app.auth.models import Organization, User, utc_now
from app.identity.models import AccountIdentifier, IdentifierKind
from app.identity.service import normalize
from app.organizations.models import (
    InvitationStatus,
    MembershipStatus,
    OrganizationInvitation,
    OrganizationMember,
    OrganizationRole,
)
from app.organizations.permissions import Permission, permissions_for
from app.organizations.service import (
    MembershipError,
    MembershipService,
    may_grant,
)

TOKEN_BYTES = 32


class InvitationError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class IssuedInvitation:
    """The raw token exists only here, on the way to the delivery transport."""

    invitation: OrganizationInvitation
    token: str


class InvitationService:
    def __init__(
        self,
        memberships: MembershipService,
        clock: Callable[[], datetime] = utc_now,
        ttl: timedelta = timedelta(days=7),
    ) -> None:
        self.memberships = memberships
        self.clock = clock
        self.ttl = ttl

    @staticmethod
    def _hash(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    # --- issuing ----------------------------------------------------------

    def invite(
        self,
        session: Session,
        actor: OrganizationMember,
        email: str,
        role: OrganizationRole,
    ) -> IssuedInvitation:
        try:
            acting = self.memberships.resolve_actor(session, actor)
        except MembershipError as exc:
            raise InvitationError(exc.code) from exc
        if Permission.MEMBER_INVITE not in permissions_for(acting.role):
            raise InvitationError("permission_denied")
        if not may_grant(acting.role, role):
            raise InvitationError("role_change_forbidden")

        value = normalize(IdentifierKind.EMAIL, email)
        now = self.clock()
        # Serialize invitations per tenant so two requests for the same
        # recipient cannot race the partial unique index and leak a database
        # error as a 500.
        session.exec(
            select(Organization)
            .where(Organization.id == acting.organization_id)
            .with_for_update()
        ).one()
        existing = session.exec(
            select(OrganizationInvitation).where(
                OrganizationInvitation.organization_id == acting.organization_id,
                OrganizationInvitation.invited_kind == IdentifierKind.EMAIL,
                OrganizationInvitation.invited_value == value,
                OrganizationInvitation.status == InvitationStatus.PENDING,
            )
        ).first()
        if existing is not None:
            if not self._is_expired(existing, now):
                raise InvitationError("invitation_already_pending")
            # Expiry is computed rather than stored as a fourth status, but an
            # expired pending row must leave the partial unique index before a
            # replacement can be issued.
            existing.status = InvitationStatus.REVOKED
            existing.revoked_at = now
            session.add(existing)
            session.flush()

        raw = secrets.token_urlsafe(TOKEN_BYTES)
        invitation = OrganizationInvitation(
            organization_id=acting.organization_id,
            role=role,
            invited_kind=IdentifierKind.EMAIL,
            invited_value=value,
            token_hash=self._hash(raw),
            invited_by_user_id=acting.user_id,
            expires_at=now + self.ttl,
            created_at=now,
        )
        session.add(invitation)
        session.flush()
        return IssuedInvitation(invitation=invitation, token=raw)

    def revoke(
        self, session: Session, actor: OrganizationMember, invitation_id: UUID
    ) -> OrganizationInvitation:
        try:
            acting = self.memberships.resolve_actor(session, actor)
        except MembershipError as exc:
            raise InvitationError(exc.code) from exc
        if Permission.MEMBER_INVITE not in permissions_for(acting.role):
            raise InvitationError("permission_denied")

        # Scoped by organization as well as id: an invitation belonging to
        # another tenant must read as absent, not as forbidden, so the endpoint
        # cannot be used to confirm that an id exists elsewhere.
        invitation = session.exec(
            select(OrganizationInvitation).where(
                OrganizationInvitation.id == invitation_id,
                OrganizationInvitation.organization_id == acting.organization_id,
            )
        ).first()
        if invitation is None:
            raise InvitationError("invitation_not_found")
        if invitation.status is not InvitationStatus.PENDING:
            raise InvitationError("invitation_invalid")

        invitation.status = InvitationStatus.REVOKED
        invitation.revoked_at = self.clock()
        session.add(invitation)
        session.flush()
        return invitation

    def list_pending(
        self, session: Session, organization_id: UUID
    ) -> list[OrganizationInvitation]:
        now = self.clock()
        return list(
            session.exec(
                select(OrganizationInvitation)
                .where(
                    OrganizationInvitation.organization_id == organization_id,
                    OrganizationInvitation.status == InvitationStatus.PENDING,
                    or_(
                        col(OrganizationInvitation.expires_at).is_(None),
                        col(OrganizationInvitation.expires_at) > now,
                    ),
                )
                .order_by(col(OrganizationInvitation.created_at))
            ).all()
        )

    # --- the recipient side -----------------------------------------------

    def _verified_values(
        self, session: Session, user: User
    ) -> set[tuple[IdentifierKind, str]]:
        rows = session.exec(
            select(AccountIdentifier).where(
                AccountIdentifier.user_id == user.id,
                col(AccountIdentifier.verified_at).is_not(None),
            )
        ).all()
        return {(row.kind, row.value) for row in rows}

    def list_for_user(
        self, session: Session, user: User
    ) -> list[OrganizationInvitation]:
        """Pending invitations addressed to something this account has proved.

        Deliberately driven from the user's *verified* identifiers rather than
        from a supplied address: a caller cannot ask "is there an invitation for
        someone else" and read the answer from the length of the list.
        """
        owned = self._verified_values(session, user)
        if not owned:
            return []
        recipient_matches = [
            and_(
                col(OrganizationInvitation.invited_kind) == kind,
                col(OrganizationInvitation.invited_value) == value,
            )
            for kind, value in owned
        ]
        now = self.clock()
        candidates = session.exec(
            select(OrganizationInvitation)
            .where(
                OrganizationInvitation.status == InvitationStatus.PENDING,
                or_(*recipient_matches),
                or_(
                    col(OrganizationInvitation.expires_at).is_(None),
                    col(OrganizationInvitation.expires_at) > now,
                ),
            )
            .order_by(col(OrganizationInvitation.created_at))
        ).all()
        return list(candidates)

    @staticmethod
    def _is_expired(invitation: OrganizationInvitation, now: datetime) -> bool:
        if invitation.expires_at is None:
            return False
        expires_at = invitation.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        # Exclusive at the boundary: dead *at* expires_at, not after it.
        return now >= expires_at

    def find_by_token(
        self, session: Session, token: str
    ) -> OrganizationInvitation | None:
        """The one place a raw invitation token is turned into a row.

        Public because chunk 18's preview needs the same lookup without
        accepting anything, and a second copy of "hash it, then select on the
        hash" is a second place for the hashing to drift.
        """
        return session.exec(
            select(OrganizationInvitation).where(
                OrganizationInvitation.token_hash == self._hash(token)
            )
        ).first()

    def accept_by_token(
        self, session: Session, user: User, token: str
    ) -> OrganizationMember:
        invitation = self.find_by_token(session, token)
        if invitation is None:
            raise InvitationError("invitation_invalid")
        return self._accept(session, user, invitation)

    def accept(
        self, session: Session, user: User, invitation_id: UUID
    ) -> OrganizationMember:
        invitation = session.get(OrganizationInvitation, invitation_id)
        if invitation is None:
            raise InvitationError("invitation_invalid")
        return self._accept(session, user, invitation)

    def _accept(
        self,
        session: Session,
        user: User,
        invitation: OrganizationInvitation,
    ) -> OrganizationMember:
        now = self.clock()
        if invitation.status is not InvitationStatus.PENDING:
            raise InvitationError("invitation_invalid")
        if self._is_expired(invitation, now):
            raise InvitationError("invitation_expired")

        # The binding. Checked before anything is claimed, and against verified
        # rows only.
        if (
            invitation.invited_kind,
            invitation.invited_value,
        ) not in self._verified_values(session, user):
            raise InvitationError("invitation_recipient_mismatch")

        existing = session.exec(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == invitation.organization_id,
                OrganizationMember.user_id == user.id,
            )
        ).first()
        if existing is not None and existing.status is MembershipStatus.ACTIVE:
            raise InvitationError("already_a_member")

        # Atomic claim. Two simultaneous clicks both reach here; only one
        # UPDATE reports a row changed, and the loser never creates a
        # membership.
        claimed = cast(
            CursorResult[Any],
            session.execute(
                update(OrganizationInvitation)
                .where(
                    col(OrganizationInvitation.id) == invitation.id,
                    col(OrganizationInvitation.status) == InvitationStatus.PENDING,
                )
                .values(
                    status=InvitationStatus.ACCEPTED,
                    accepted_at=now,
                    accepted_by_user_id=user.id,
                )
            ),
        )
        if claimed.rowcount != 1:
            raise InvitationError("invitation_invalid")

        if existing is not None:
            # Reactivate the row that already exists rather than inserting a
            # second one: the unique constraint would refuse it, and the
            # revoked row is what carries the history.
            existing.status = MembershipStatus.ACTIVE
            existing.role = invitation.role
            existing.revoked_at = None
            existing.joined_at = now
            existing.updated_at = now
            existing.invited_by_user_id = invitation.invited_by_user_id
            session.add(existing)
            session.flush()
            return existing

        organization = session.get(Organization, invitation.organization_id)
        if organization is None:  # pragma: no cover - FK makes this unreachable
            raise InvitationError("invitation_invalid")
        return self.memberships.seed_member(
            session,
            organization,
            user,
            invitation.role,
            invited_by_user_id=invitation.invited_by_user_id,
        )

    # --- the controlled migration for existing organizations --------------

    def seed_bootstrap_owner_invitation(
        self, session: Session, organization: Organization
    ) -> OrganizationInvitation | None:
        """Offer ownership of a pre-membership organization to its contact.

        This is the whole of the migration path, and what it deliberately does
        *not* do matters more than what it does:

        - It creates **no user account**. Inventing an account for an address
          nobody has proved would be exactly the auto-promotion the assignment
          forbids.
        - It promotes **nobody**. The organization gains an owner only when a
          person proves they can read the contact mailbox and claims the offer.
        - It touches **no `users` row**. Historical customer accounts are not
          organization staff and are never enrolled by this.

        Returns `None` when the organization already has an owner, so a re-run
        cannot put a live tenant's ownership back up for grabs. Idempotent.
        """
        owner = session.exec(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == organization.id,
                OrganizationMember.role == OrganizationRole.OWNER,
                OrganizationMember.status == MembershipStatus.ACTIVE,
            )
        ).first()
        if owner is not None:
            return None

        value = normalize(IdentifierKind.EMAIL, organization.email)
        existing = session.exec(
            select(OrganizationInvitation).where(
                OrganizationInvitation.organization_id == organization.id,
                OrganizationInvitation.invited_kind == IdentifierKind.EMAIL,
                OrganizationInvitation.invited_value == value,
                OrganizationInvitation.status == InvitationStatus.PENDING,
            )
        ).first()
        if existing is not None:
            return existing

        invitation = OrganizationInvitation(
            organization_id=organization.id,
            role=OrganizationRole.OWNER,
            invited_kind=IdentifierKind.EMAIL,
            invited_value=value,
            token_hash=None,
            is_bootstrap=True,
            expires_at=None,
            created_at=self.clock(),
        )
        session.add(invitation)
        session.flush()
        return invitation
