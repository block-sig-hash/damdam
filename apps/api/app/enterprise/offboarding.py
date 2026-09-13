"""What happens when somebody leaves an organization (US-40, chunk 24).

One rule governs this file and it is worth stating before any code:

**Work ends; personal service does not.** An organization pays for its staff's
work lines. It does not own their phone, their personal data plan, their
personal calling credit or their account. Offboarding therefore touches exactly
what the organization paid for, and a test asserts that a personal line survives
it — because the failure here is not a wrong number on a screen, it is somebody
losing their own phone service on the day they change jobs.

The second rule follows from the first being hard to verify:

**Say what is pending.** Some of this is ours and instant — access, invitations,
unclaimed lines, unspent top-ups. Some of it is a request to a carrier whose
answer arrives later or never. Each action records its own outcome, and a run
that finishes with an unanswered carrier request is `completed_with_pending`
rather than `completed`. An administrator who is told "done" about a line that
is still live will find out from an invoice.

## What this deliberately does not do

Reassign a line. *Do not silently transfer a live profile to another person* —
and an eSIM on a departing employee's handset is not moveable by us updating a
row. Reassignment is a suspension plus a new line for the new holder, which is
two decisions with a person in the middle. `reassign` is not a method here.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlmodel import Session, col, select

from app.auth.models import utc_now
from app.bulk.models import (
    ActivationRequest,
    ActivationRequestState,
    BulkItemState,
    BulkJobItem,
)
from app.connectivity.models import ActivationState, CarrierLine, Entitlement
from app.enterprise.models import (
    OffboardingAction,
    OffboardingActionKind,
    OffboardingActionState,
    OffboardingState,
    OrganizationOffboarding,
)
from app.ledger.models import Reservation, ReservationState
from app.ledger.service import LedgerService
from app.orders.models import Order, OrderItem
from app.organizations.models import MembershipStatus, OrganizationMember
from app.people.models import OrganizationPerson, PersonStatus


class OffboardingError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class OffboardingSummary:
    """What a departure did, and what is still outstanding."""

    offboarding_id: UUID
    state: OffboardingState
    confirmed: int
    pending_carrier: int
    not_applicable: int
    failed: int

    @property
    def has_pending(self) -> bool:
        return self.pending_carrier > 0


class OffboardingService:
    def __init__(
        self,
        ledger: LedgerService,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.ledger = ledger
        self.clock = clock

    def offboard(
        self,
        session: Session,
        organization_id: UUID,
        person_id: UUID,
        *,
        requested_by_user_id: UUID | None = None,
        reason: str | None = None,
    ) -> OffboardingSummary:
        """End somebody's work relationship with one organization.

        Idempotent on the person: an open run is returned rather than a second
        one started, because two runs would race each other's suspensions.
        """
        person = session.exec(
            select(OrganizationPerson).where(
                OrganizationPerson.id == person_id,
                # Tenant scope in the query. Offboarding somebody from an
                # organization they do not belong to is not an error message,
                # it is a person who does not exist here.
                OrganizationPerson.organization_id == organization_id,
            )
        ).first()
        if person is None:
            raise OffboardingError("person_not_found")

        # Idempotent for the whole departure, not merely while a run is open.
        # Somebody leaving is a one-time event: a second request is an
        # administrator who did not see the first response, and starting a
        # second run would re-ask a carrier to suspend a line it is already
        # suspending. A *completed* run only short-circuits when the person is
        # already archived — otherwise they were re-added since, and this is a
        # new departure.
        existing = session.exec(
            select(OrganizationOffboarding)
            .where(OrganizationOffboarding.person_id == person_id)
            .order_by(col(OrganizationOffboarding.requested_at).desc())
        ).first()
        if existing is not None and (
            existing.state
            in {OffboardingState.REQUESTED, OffboardingState.IN_PROGRESS}
            or person.status is PersonStatus.ARCHIVED
        ):
            return self.summary(session, existing)

        now = self.clock()
        run = OrganizationOffboarding(
            organization_id=organization_id,
            person_id=person_id,
            requested_by_user_id=requested_by_user_id,
            state=OffboardingState.IN_PROGRESS,
            reason=reason[:200] if reason else None,
            requested_at=now,
        )
        session.add(run)
        session.flush()

        # Order matters. Access and spending authority go first, because every
        # later step takes time and none of them should be able to be undone by
        # the person being offboarded.
        self._revoke_membership(session, run, person)
        self._revoke_activation_requests(session, run, person)
        self._cancel_pending_lines(session, run, person)
        self._suspend_work_lines(session, run, person)

        # The person is archived last: chunk 22 keeps them, because their orders
        # and receipts still name them.
        if person.status is PersonStatus.ACTIVE:
            person.status = PersonStatus.ARCHIVED
            person.archived_at = now
            person.updated_at = now
            session.add(person)

        summary = self._settle(session, run)
        session.flush()
        return summary

    # --- the individual acts ----------------------------------------------

    def _revoke_membership(
        self,
        session: Session,
        run: OrganizationOffboarding,
        person: OrganizationPerson,
    ) -> None:
        """Dashboard access and the authority to spend. Ours, immediately.

        A person row and a membership are different things (chunk 22), and most
        recipients have no membership at all — which is `not_applicable`, not a
        failure.
        """
        if person.user_id is None:
            self._record(
                session,
                run,
                OffboardingActionKind.REVOKE_MEMBERSHIP,
                OffboardingActionState.NOT_APPLICABLE,
                detail="this person never claimed an account",
            )
            return

        memberships = session.exec(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == run.organization_id,
                OrganizationMember.user_id == person.user_id,
                OrganizationMember.status == MembershipStatus.ACTIVE,
            )
        ).all()
        if not memberships:
            self._record(
                session,
                run,
                OffboardingActionKind.REVOKE_MEMBERSHIP,
                OffboardingActionState.NOT_APPLICABLE,
                detail="no active membership",
            )
            return

        now = self.clock()
        for membership in memberships:
            membership.status = MembershipStatus.REVOKED
            membership.revoked_at = now
            membership.updated_at = now
            session.add(membership)
            self._record(
                session,
                run,
                OffboardingActionKind.REVOKE_MEMBERSHIP,
                OffboardingActionState.CONFIRMED,
                target=f"membership:{membership.id}",
            )

    def _revoke_activation_requests(
        self,
        session: Session,
        run: OrganizationOffboarding,
        person: OrganizationPerson,
    ) -> None:
        """Unclaimed invitations to work lines. Nobody is going to claim them."""
        requests = session.exec(
            select(ActivationRequest).where(
                ActivationRequest.person_id == person.id,
                col(ActivationRequest.state).in_(
                    [ActivationRequestState.PENDING, ActivationRequestState.SENT]
                ),
            )
        ).all()
        if not requests:
            self._record(
                session,
                run,
                OffboardingActionKind.REVOKE_ACTIVATION_REQUEST,
                OffboardingActionState.NOT_APPLICABLE,
            )
            return
        for request in requests:
            request.state = ActivationRequestState.REVOKED
            request.revoked_reason = "offboarded"
            session.add(request)
            self._record(
                session,
                run,
                OffboardingActionKind.REVOKE_ACTIVATION_REQUEST,
                OffboardingActionState.CONFIRMED,
                target=f"activation_request:{request.id}",
            )

    def _cancel_pending_lines(
        self,
        session: Session,
        run: OrganizationOffboarding,
        person: OrganizationPerson,
    ) -> None:
        """Funded but unprovisioned bulk lines: cancel and release the hold.

        A line whose supplier outcome is **unknown** is deliberately left alone.
        Chunk 23's rule holds here too: the supplier may have provisioned it,
        and releasing the hold on a line somebody may already have is giving the
        money away.
        """
        items = session.exec(
            select(BulkJobItem).where(
                BulkJobItem.person_id == person.id,
                col(BulkJobItem.state).in_(
                    [BulkItemState.PENDING, BulkItemState.RESERVED]
                ),
            )
        ).all()
        if not items:
            self._record(
                session,
                run,
                OffboardingActionKind.CANCEL_PENDING_LINE,
                OffboardingActionState.NOT_APPLICABLE,
            )
            return
        now = self.clock()
        for item in items:
            if item.reservation_id is not None:
                reservation = session.get(Reservation, item.reservation_id)
                if reservation is not None and (
                    reservation.state is ReservationState.HELD
                ):
                    outstanding = (
                        reservation.amount
                        - reservation.settled_amount
                        - reservation.released_amount
                    )
                    if outstanding > 0:
                        self.ledger.release(session, reservation, outstanding)
            item.state = BulkItemState.CANCELLED
            item.error_code = "offboarded"
            item.updated_at = now
            session.add(item)
            self._record(
                session,
                run,
                OffboardingActionKind.CANCEL_PENDING_LINE,
                OffboardingActionState.CONFIRMED,
                target=f"bulk_item:{item.id}",
            )

    def _suspend_work_lines(
        self,
        session: Session,
        run: OrganizationOffboarding,
        person: OrganizationPerson,
    ) -> None:
        """Live work lines. A **request** to a carrier, not an accomplished fact.

        The scoping here is the important part: only lines whose order was paid
        for by *this organization* are touched. A personal line the same person
        bought themselves is on an order with a `payer_user_id` and no
        `payer_organization_id`, and it is not in this query — which is the
        mechanism behind "personal services survive work offboarding", rather
        than a filter somebody has to remember.
        """
        lines = self._work_lines(session, run.organization_id, person)
        if not lines:
            self._record(
                session,
                run,
                OffboardingActionKind.SUSPEND_LINE,
                OffboardingActionState.NOT_APPLICABLE,
            )
            return
        for line in lines:
            if line.activation_state in {
                ActivationState.SUSPENDED,
                ActivationState.TERMINATED,
            }:
                self._record(
                    session,
                    run,
                    OffboardingActionKind.SUSPEND_LINE,
                    OffboardingActionState.NOT_APPLICABLE,
                    target=f"line:{line.id}",
                    detail=f"already {line.activation_state.value}",
                )
                continue
            # No carrier adapter is wired into this chunk, so the honest record
            # is that we asked and have not been told. Marking it confirmed
            # would be a screen telling an administrator a line is off when
            # nothing has reached the carrier.
            self._record(
                session,
                run,
                OffboardingActionKind.SUSPEND_LINE,
                OffboardingActionState.PENDING_CARRIER,
                target=f"line:{line.id}",
                detail="suspension requested; awaiting carrier confirmation",
            )

    def _work_lines(
        self, session: Session, organization_id: UUID, person: OrganizationPerson
    ) -> Sequence[CarrierLine]:
        """Lines this organization paid for, for this person. Nothing else.

        The join runs through the order, because *who paid* is the only durable
        definition of a work line. A line's holder can change; who bought it
        cannot.
        """
        if person.user_id is None:
            return []
        return session.exec(
            select(CarrierLine)
            .join(Entitlement, col(CarrierLine.entitlement_id) == col(Entitlement.id))
            .join(OrderItem, col(Entitlement.order_item_id) == col(OrderItem.id))
            .join(Order, col(OrderItem.order_id) == col(Order.id))
            .where(
                Entitlement.holder_user_id == person.user_id,
                Order.payer_organization_id == organization_id,
            )
        ).all()

    # --- bookkeeping -------------------------------------------------------

    def _record(
        self,
        session: Session,
        run: OrganizationOffboarding,
        kind: OffboardingActionKind,
        state: OffboardingActionState,
        *,
        target: str | None = None,
        detail: str | None = None,
    ) -> OffboardingAction:
        now = self.clock()
        action = OffboardingAction(
            offboarding_id=run.id,
            kind=kind,
            state=state,
            target_reference=target,
            detail=detail[:500] if detail else None,
            requested_at=now,
            confirmed_at=(
                now if state is OffboardingActionState.CONFIRMED else None
            ),
        )
        session.add(action)
        session.flush()
        return action

    def _settle(
        self, session: Session, run: OrganizationOffboarding
    ) -> OffboardingSummary:
        actions = self.actions(session, run)
        pending = [
            action
            for action in actions
            if action.state is OffboardingActionState.PENDING_CARRIER
        ]
        run.state = (
            OffboardingState.COMPLETED_WITH_PENDING
            if pending
            else OffboardingState.COMPLETED
        )
        run.completed_at = self.clock()
        session.add(run)
        session.flush()
        return self.summary(session, run)

    def confirm_action(
        self, session: Session, action: OffboardingAction, *, detail: str | None = None
    ) -> OffboardingAction:
        """A carrier answered. The run may now be finished rather than pending."""
        action.state = OffboardingActionState.CONFIRMED
        action.confirmed_at = self.clock()
        if detail:
            action.detail = detail[:500]
        session.add(action)
        session.flush()
        run = session.get(OrganizationOffboarding, action.offboarding_id)
        if run is not None:
            self._settle(session, run)
        return action

    def summary(
        self, session: Session, run: OrganizationOffboarding
    ) -> OffboardingSummary:
        actions = self.actions(session, run)
        return OffboardingSummary(
            offboarding_id=run.id,
            state=run.state,
            confirmed=sum(
                1
                for action in actions
                if action.state is OffboardingActionState.CONFIRMED
            ),
            pending_carrier=sum(
                1
                for action in actions
                if action.state is OffboardingActionState.PENDING_CARRIER
            ),
            not_applicable=sum(
                1
                for action in actions
                if action.state is OffboardingActionState.NOT_APPLICABLE
            ),
            failed=sum(
                1 for action in actions if action.state is OffboardingActionState.FAILED
            ),
        )

    def actions(
        self, session: Session, run: OrganizationOffboarding
    ) -> Sequence[OffboardingAction]:
        return session.exec(
            select(OffboardingAction)
            .where(OffboardingAction.offboarding_id == run.id)
            .order_by(col(OffboardingAction.requested_at))
        ).all()

    def run(
        self, session: Session, organization_id: UUID, offboarding_id: UUID
    ) -> OrganizationOffboarding:
        found = session.exec(
            select(OrganizationOffboarding).where(
                OrganizationOffboarding.id == offboarding_id,
                OrganizationOffboarding.organization_id == organization_id,
            )
        ).first()
        if found is None:
            raise OffboardingError("offboarding_not_found")
        return found

    def history(
        self, session: Session, organization_id: UUID, *, limit: int = 50
    ) -> Sequence[OrganizationOffboarding]:
        return session.exec(
            select(OrganizationOffboarding)
            .where(OrganizationOffboarding.organization_id == organization_id)
            .order_by(col(OrganizationOffboarding.requested_at).desc())
            .limit(limit)
        ).all()


__all__ = ["OffboardingError", "OffboardingService", "OffboardingSummary"]
