"""Membership transitions, enforced on the server (US-29, AC-29.3/AC-29.4).

Three classes of mistake are prevented here, and each one is a real incident
rather than a hypothetical:

1. **Escalation.** An administrator who can mint owners can take the
   organization. Nobody may grant a role above their own, and nobody may edit
   their own membership -- self-service promotion is the shortest path there is.
2. **A stranded organization.** Demoting or revoking the last owner leaves an
   account nobody can administer, recoverable only by a support engineer with
   database access. The owner count is read under a row lock so two concurrent
   demotions cannot both see "there is still another owner".
3. **Access that outlives its grant.** Every check re-reads the membership row
   inside the request's own transaction. Nothing about a caller's authority is
   carried in a token or a cache, so revocation is effective on the next
   request rather than on the next token expiry (AC-29.5).
"""

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from sqlmodel import Session, col, select

from app.auth.models import Organization, User, utc_now
from app.organizations.models import (
    MembershipStatus,
    OrganizationMember,
    OrganizationRole,
    rank,
)
from app.organizations.permissions import (
    Permission,
    permissions_for,
    requires_step_up,
)

if TYPE_CHECKING:  # pragma: no cover - only the checker needs the concrete type
    from app.mfa.service import MfaService


class MembershipError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RevocationListener(Protocol):
    """Something that must react when a person loses a membership.

    The seam exists because losing organization access has to withdraw more
    than the membership row -- outstanding work-call grants and issued
    credentials, for one (`VOICE-EXPANSION.md`, the chunks 06-07 row). Chunk 07
    owns the *moment*; the capabilities own what they withdraw, and V02
    registers the calling-specific listener when there is a call grant to
    revoke.

    A listener rather than a direct call into calling code, for a reason that
    matters here: a listener cannot reach personal service. It is handed an
    organization and a person, so "revoked membership blocks new work calls
    without affecting personal service" is a property of the interface rather
    than of each implementation remembering to check.

    Listeners run inside the revoking transaction. One that raises aborts the
    revocation rather than leaving a membership removed and its grants live.
    """

    def on_membership_revoked(
        self, session: Session, organization_id: UUID, user_id: UUID, at: datetime
    ) -> None: ...


def may_manage(actor: OrganizationRole, target: OrganizationRole) -> bool:
    """May the actor act on a membership currently holding `target`?

    An owner may act on anyone (including another owner -- the last-owner rule,
    not the rank rule, is what stops an organization being emptied). Everyone
    else may only act strictly below themselves, so an administrator cannot
    demote or remove a peer, let alone an owner.
    """
    if actor is OrganizationRole.OWNER:
        return True
    return rank(target) < rank(actor)


def may_grant(actor: OrganizationRole, new_role: OrganizationRole) -> bool:
    if actor is OrganizationRole.OWNER:
        return True
    return rank(new_role) < rank(actor)


class MembershipService:
    def __init__(
        self,
        clock: Callable[[], datetime] = utc_now,
        revocation_listeners: "list[RevocationListener] | None" = None,
    ) -> None:
        self.clock = clock
        self.revocation_listeners: list[RevocationListener] = list(
            revocation_listeners or []
        )

    def add_revocation_listener(self, listener: RevocationListener) -> None:
        self.revocation_listeners.append(listener)

    # --- reads ------------------------------------------------------------

    def active_membership(
        self, session: Session, organization_id: UUID, user_id: UUID
    ) -> OrganizationMember | None:
        """The single authorization lookup. Scoped by organization *and* person.

        Every org-scoped route goes through here, so a caller holding a valid
        session for organization A can never be resolved into authority over
        organization B by supplying B's id.
        """
        return session.exec(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
                OrganizationMember.status == MembershipStatus.ACTIVE,
            )
        ).first()

    def require_membership(
        self, session: Session, organization_id: UUID, user_id: UUID
    ) -> OrganizationMember:
        membership = self.active_membership(session, organization_id, user_id)
        if membership is None:
            raise MembershipError("not_a_member")
        return membership

    def require_permission(
        self,
        session: Session,
        organization_id: UUID,
        user_id: UUID,
        permission: Permission,
        mfa: "MfaService | None" = None,
    ) -> OrganizationMember:
        """Membership, then role, then -- for privileged actions -- a second factor.

        The order is deliberate. A caller who is not a member learns
        `not_a_member` whatever they asked for, so the MFA prompt cannot be
        used to confirm that an organization exists or that someone belongs
        to it.

        `mfa` is optional so that the pure membership rules stay testable on
        their own, but every route passes it: the step-up requirement is
        declared once in `STEP_UP_PERMISSIONS`, not re-decided per endpoint.
        """
        membership = self.require_membership(session, organization_id, user_id)
        if permission not in permissions_for(membership.role):
            raise MembershipError("permission_denied")
        if mfa is not None and requires_step_up(permission):
            from app.mfa.service import MfaError

            try:
                mfa.assert_stepped_up(session, user_id, organization_id)
            except MfaError as exc:
                raise MembershipError(exc.code) from exc
        return membership

    def list_members(
        self, session: Session, organization_id: UUID
    ) -> list[OrganizationMember]:
        return list(
            session.exec(
                select(OrganizationMember)
                .where(OrganizationMember.organization_id == organization_id)
                .order_by(col(OrganizationMember.created_at))
            ).all()
        )

    # --- the last-owner invariant ----------------------------------------

    def _lock_owners(
        self, session: Session, organization_id: UUID
    ) -> list[OrganizationMember]:
        """Lock every active owner row, in a deterministic order.

        `ORDER BY id` matters: two transactions locking the same set in
        different orders deadlock instead of queueing. With a fixed order the
        second waits, then re-reads a count that already reflects the first.
        """
        return list(
            session.exec(
                select(OrganizationMember)
                .where(
                    OrganizationMember.organization_id == organization_id,
                    OrganizationMember.role == OrganizationRole.OWNER,
                    OrganizationMember.status == MembershipStatus.ACTIVE,
                )
                .order_by(col(OrganizationMember.id))
                .with_for_update()
            ).all()
        )

    def _refuse_if_last_owner(
        self, session: Session, membership: OrganizationMember
    ) -> None:
        if membership.role is not OrganizationRole.OWNER:
            return
        owners = self._lock_owners(session, membership.organization_id)
        remaining = [owner for owner in owners if owner.id != membership.id]
        if not remaining:
            raise MembershipError("last_owner")

    # --- actor resolution -------------------------------------------------

    def resolve_actor(
        self, session: Session, actor: OrganizationMember
    ) -> OrganizationMember:
        """Re-read the actor's own membership before trusting its role.

        The object the caller handed in may have been loaded before their role
        changed, or before it was revoked. Authority is whatever the database
        says at this instant.
        """
        current = self.active_membership(
            session, actor.organization_id, actor.user_id
        )
        if current is None:
            raise MembershipError("not_a_member")
        return current

    def _target(
        self,
        session: Session,
        organization_id: UUID,
        user_id: UUID,
        *,
        status: MembershipStatus | None = MembershipStatus.ACTIVE,
    ) -> OrganizationMember:
        statement = select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
        )
        if status is not None:
            statement = statement.where(OrganizationMember.status == status)
        membership = session.exec(statement).first()
        if membership is None:
            raise MembershipError("membership_not_found")
        return membership

    def _require(
        self,
        session: Session,
        acting: OrganizationMember,
        permission: Permission,
        mfa: "MfaService | None",
    ) -> None:
        """One gate for every transition: the role, then the second factor."""
        if permission not in permissions_for(acting.role):
            raise MembershipError("permission_denied")
        if mfa is not None and requires_step_up(permission):
            from app.mfa.service import MfaError

            try:
                mfa.assert_stepped_up(
                    session, acting.user_id, acting.organization_id
                )
            except MfaError as exc:
                raise MembershipError(exc.code) from exc

    # --- transitions ------------------------------------------------------

    def seed_member(
        self,
        session: Session,
        organization: Organization,
        user: User,
        role: OrganizationRole,
        invited_by_user_id: UUID | None = None,
    ) -> OrganizationMember:
        """Create a membership with no actor.

        Reached from exactly two places: the controlled migration that gives an
        existing organization its first owner, and invitation acceptance, where
        the authority was checked when the invitation was issued. It is not an
        API surface, and it deliberately performs no escalation check -- the
        callers that use it have no acting membership to compare against.
        """
        now = self.clock()
        membership = OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=role,
            invited_by_user_id=invited_by_user_id,
            joined_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(membership)
        session.flush()
        return membership

    def change_role(
        self,
        session: Session,
        actor: OrganizationMember,
        target_user_id: UUID,
        new_role: OrganizationRole,
        mfa: "MfaService | None" = None,
    ) -> OrganizationMember:
        acting = self.resolve_actor(session, actor)
        self._require(
            session, acting, Permission.MEMBER_ROLE_CHANGE, mfa
        )
        if acting.user_id == target_user_id:
            raise MembershipError("cannot_modify_own_membership")

        target = self._target(session, acting.organization_id, target_user_id)
        if not may_manage(acting.role, target.role):
            raise MembershipError("role_change_forbidden")
        if not may_grant(acting.role, new_role):
            raise MembershipError("role_change_forbidden")
        if new_role is not OrganizationRole.OWNER:
            self._refuse_if_last_owner(session, target)

        now = self.clock()
        target.role = new_role
        target.updated_at = now
        session.add(target)
        # New authority, new proof. An elevation earned as an administrator
        # must not survive a demotion to member, and one earned as a member
        # must not be reusable as a promotion's second factor.
        if mfa is not None:
            mfa.revoke_elevations(
                session, target.user_id, target.organization_id, now
            )
        session.flush()
        return target

    def revoke(
        self,
        session: Session,
        actor: OrganizationMember,
        target_user_id: UUID,
        mfa: "MfaService | None" = None,
    ) -> OrganizationMember:
        acting = self.resolve_actor(session, actor)
        self._require(session, acting, Permission.MEMBER_REVOKE, mfa)
        if acting.user_id == target_user_id:
            # Leaving is a separate, deliberate action. Routing it through
            # revoke() would let the last owner remove themselves by accident.
            raise MembershipError("cannot_modify_own_membership")

        target = self._target(session, acting.organization_id, target_user_id)
        if not may_manage(acting.role, target.role):
            raise MembershipError("role_change_forbidden")
        self._refuse_if_last_owner(session, target)

        now = self.clock()
        target.status = MembershipStatus.REVOKED
        target.revoked_at = now
        target.updated_at = now
        session.add(target)
        # AC-29.5: immediately. The revoked member's live second-factor proof
        # dies in the same transaction, so the next request they make is
        # refused rather than served until an elevation happens to lapse.
        if mfa is not None:
            mfa.revoke_elevations(
                session, target.user_id, target.organization_id, now
            )
        # Same transaction, same reason: anything else this membership was
        # holding open goes with it. Scoped to (organization, person), so
        # nothing a listener does can reach the person's own service.
        for listener in self.revocation_listeners:
            listener.on_membership_revoked(
                session, target.organization_id, target.user_id, now
            )
        session.flush()
        return target

    def reinstate(
        self,
        session: Session,
        actor: OrganizationMember,
        target_user_id: UUID,
        role: OrganizationRole,
        mfa: "MfaService | None" = None,
    ) -> OrganizationMember:
        """Reactivate the existing row rather than inserting a second one.

        A second row for the same pair would violate the unique constraint, and
        the constraint exists precisely so that two concurrent reinstatements
        cannot produce two answers to "what may this person do here".
        """
        acting = self.resolve_actor(session, actor)
        self._require(session, acting, Permission.MEMBER_INVITE, mfa)
        if not may_grant(acting.role, role):
            raise MembershipError("role_change_forbidden")

        target = self._target(
            session, acting.organization_id, target_user_id, status=None
        )
        if target.status is MembershipStatus.ACTIVE:
            raise MembershipError("already_a_member")

        now = self.clock()
        target.status = MembershipStatus.ACTIVE
        target.role = role
        target.revoked_at = None
        target.joined_at = now
        target.updated_at = now
        session.add(target)
        session.flush()
        return target
