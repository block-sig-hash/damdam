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
from uuid import UUID

from sqlmodel import Session, col, select

from app.auth.models import Organization, User, utc_now
from app.organizations.models import (
    MembershipStatus,
    OrganizationMember,
    OrganizationRole,
    rank,
)
from app.organizations.permissions import Permission, permissions_for


class MembershipError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


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
    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self.clock = clock

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
    ) -> OrganizationMember:
        membership = self.require_membership(session, organization_id, user_id)
        if permission not in permissions_for(membership.role):
            raise MembershipError("permission_denied")
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
    ) -> OrganizationMember:
        acting = self.resolve_actor(session, actor)
        if Permission.MEMBER_ROLE_CHANGE not in permissions_for(acting.role):
            raise MembershipError("permission_denied")
        if acting.user_id == target_user_id:
            raise MembershipError("cannot_modify_own_membership")

        target = self._target(session, acting.organization_id, target_user_id)
        if not may_manage(acting.role, target.role):
            raise MembershipError("role_change_forbidden")
        if not may_grant(acting.role, new_role):
            raise MembershipError("role_change_forbidden")
        if new_role is not OrganizationRole.OWNER:
            self._refuse_if_last_owner(session, target)

        target.role = new_role
        target.updated_at = self.clock()
        session.add(target)
        session.flush()
        return target

    def revoke(
        self,
        session: Session,
        actor: OrganizationMember,
        target_user_id: UUID,
    ) -> OrganizationMember:
        acting = self.resolve_actor(session, actor)
        if Permission.MEMBER_REVOKE not in permissions_for(acting.role):
            raise MembershipError("permission_denied")
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
        session.flush()
        return target

    def reinstate(
        self,
        session: Session,
        actor: OrganizationMember,
        target_user_id: UUID,
        role: OrganizationRole,
    ) -> OrganizationMember:
        """Reactivate the existing row rather than inserting a second one.

        A second row for the same pair would violate the unique constraint, and
        the constraint exists precisely so that two concurrent reinstatements
        cannot produce two answers to "what may this person do here".
        """
        acting = self.resolve_actor(session, actor)
        if Permission.MEMBER_INVITE not in permissions_for(acting.role):
            raise MembershipError("permission_denied")
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
