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
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import or_
from sqlmodel import Session, col, select

from app.auth.models import utc_now
from app.bulk.models import (
    ActivationRequest,
    ActivationRequestState,
    BulkItemState,
    BulkJob,
    BulkJobItem,
)
from app.bulk.service import BulkProvisioningService
from app.calling.models import TERMINAL_ATTEMPT_STATES, CallAttempt
from app.connectivity.models import ActivationState, CarrierLine, Entitlement
from app.controls.models import EntitlementTopUp, TopUpState
from app.enterprise.models import (
    OffboardingAction,
    OffboardingActionKind,
    OffboardingActionState,
    OffboardingState,
    OrganizationOffboarding,
)
from app.ledger.models import Reservation
from app.ledger.service import LedgerError, LedgerService
from app.orders.models import Order, OrderItem
from app.organizations.models import MembershipStatus, OrganizationMember
from app.organizations.service import MembershipError, MembershipService
from app.people.models import OrganizationPerson, PersonStatus

if TYPE_CHECKING:
    from app.mfa.service import MfaService


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
        memberships: MembershipService | None = None,
        mfa: MfaService | None = None,
        call_revoker: Callable[[Session, UUID, UUID, datetime], None] | None = None,
    ) -> None:
        self.ledger = ledger
        self.clock = clock
        self.bulk = BulkProvisioningService(ledger, clock=clock)
        self.memberships = memberships or MembershipService(clock=clock)
        self.mfa = mfa
        self.call_revoker = call_revoker

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
            select(OrganizationPerson)
            .where(
                OrganizationPerson.id == person_id,
                # Tenant scope in the query. Offboarding somebody from an
                # organization they do not belong to is not an error message,
                # it is a person who does not exist here.
                OrganizationPerson.organization_id == organization_id,
            )
            # This is the idempotency lock. It also serializes invitation
            # issuance, whose lock order starts with the same recipient row.
            .with_for_update()
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
        self._cancel_pending_top_ups(session, run, person)
        self._revoke_work_entitlements(session, run, person)
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
            self._record_active_calls(session, run, [])
            return

        attempts = list(
            session.exec(
                select(CallAttempt)
                .where(
                    CallAttempt.organization_id == run.organization_id,
                    CallAttempt.owner_user_id == person.user_id,
                    col(CallAttempt.state).not_in(list(TERMINAL_ATTEMPT_STATES)),
                )
                .with_for_update()
            ).all()
        )
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
            if attempts and self.call_revoker is not None:
                self.call_revoker(
                    session, run.organization_id, person.user_id, self.clock()
                )
            self._record_active_calls(session, run, attempts)
            return

        for membership in memberships:
            try:
                self.memberships.revoke_for_offboarding(
                    session, membership, self.mfa
                )
            except MembershipError as error:
                raise OffboardingError(error.code) from error
            self._record(
                session,
                run,
                OffboardingActionKind.REVOKE_MEMBERSHIP,
                OffboardingActionState.CONFIRMED,
                target=f"membership:{membership.id}",
            )
        self._record_active_calls(session, run, attempts)

    def _record_active_calls(
        self,
        session: Session,
        run: OrganizationOffboarding,
        attempts: Sequence[CallAttempt],
    ) -> None:
        if not attempts:
            self._record(
                session,
                run,
                OffboardingActionKind.END_ACTIVE_CALL,
                OffboardingActionState.NOT_APPLICABLE,
            )
            return
        for attempt in attempts:
            session.refresh(attempt)
            if attempt.stop_requested_at is not None:
                state = OffboardingActionState.CONFIRMED
                detail = "call stop requested"
            else:
                state = OffboardingActionState.FAILED
                detail = "active work call was not stopped"
            self._record(
                session,
                run,
                OffboardingActionKind.END_ACTIVE_CALL,
                state,
                target=f"call:{attempt.id}",
                detail=detail,
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
            self.bulk.revoke_activation_request(
                session, request, reason="offboarded"
            )
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
                    [
                        BulkItemState.PENDING,
                        BulkItemState.RESERVED,
                        BulkItemState.FAILED,
                        BulkItemState.ORDERED,
                        BulkItemState.UNKNOWN,
                    ]
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
        for item in items:
            if item.state in {BulkItemState.ORDERED, BulkItemState.UNKNOWN}:
                # A supplier may already have acted. Keep the hold and expose
                # the reconciliation/cancellation as pending instead of
                # pretending the service or the money was unwound.
                self._record(
                    session,
                    run,
                    OffboardingActionKind.CANCEL_PENDING_LINE,
                    OffboardingActionState.PENDING_CARRIER,
                    target=f"bulk_item:{item.id}",
                    detail="supplier outcome must be reconciled before cancellation",
                )
                continue

            job = session.get(BulkJob, item.job_id)
            if job is None:  # pragma: no cover - FK guarantees this
                continue
            self.bulk.cancel_item(session, job, item, reason="offboarded")
            self._record(
                session,
                run,
                OffboardingActionKind.CANCEL_PENDING_LINE,
                OffboardingActionState.CONFIRMED,
                target=f"bulk_item:{item.id}",
            )

    def _revoke_work_entitlements(
        self,
        session: Session,
        run: OrganizationOffboarding,
        person: OrganizationPerson,
    ) -> None:
        """End local work service now; carrier suspension remains separate."""
        entitlements = self._work_entitlements(
            session, run.organization_id, person
        )
        if not entitlements:
            self._record(
                session,
                run,
                OffboardingActionKind.REVOKE_ENTITLEMENT,
                OffboardingActionState.NOT_APPLICABLE,
            )
            return

        now = self.clock()
        for entitlement in entitlements:
            if entitlement.expires_at is not None and entitlement.expires_at <= now:
                state = OffboardingActionState.NOT_APPLICABLE
                detail = "entitlement already expired"
            else:
                entitlement.expires_at = now
                session.add(entitlement)
                state = OffboardingActionState.CONFIRMED
                detail = "local work entitlement expired"
            self._record(
                session,
                run,
                OffboardingActionKind.REVOKE_ENTITLEMENT,
                state,
                target=f"entitlement:{entitlement.id}",
                detail=detail,
            )

    def _cancel_pending_top_ups(
        self,
        session: Session,
        run: OrganizationOffboarding,
        person: OrganizationPerson,
    ) -> None:
        """Release unspent organization top-up holds; expose unsafe states."""
        entitlement_ids = [
            entitlement.id
            for entitlement in self._work_entitlements(
                session, run.organization_id, person
            )
        ]
        if not entitlement_ids:
            top_ups: Sequence[EntitlementTopUp] = []
        else:
            top_ups = session.exec(
                select(EntitlementTopUp)
                .join(
                    OrderItem,
                    col(EntitlementTopUp.order_item_id) == col(OrderItem.id),
                )
                .join(Order, col(OrderItem.order_id) == col(Order.id))
                .where(
                    col(EntitlementTopUp.entitlement_id).in_(entitlement_ids),
                    Order.payer_organization_id == run.organization_id,
                    col(EntitlementTopUp.state).in_(
                        [
                            TopUpState.REQUESTED,
                            TopUpState.RESERVED,
                            TopUpState.PAID,
                            TopUpState.PROVISIONING,
                            TopUpState.OUTCOME_UNKNOWN,
                        ]
                    ),
                )
                .with_for_update()
            ).all()
        if not top_ups:
            self._record(
                session,
                run,
                OffboardingActionKind.CANCEL_PENDING_TOP_UP,
                OffboardingActionState.NOT_APPLICABLE,
            )
            return

        for top_up in top_ups:
            target = f"top_up:{top_up.id}"
            if top_up.state in {TopUpState.PROVISIONING, TopUpState.OUTCOME_UNKNOWN}:
                self._record(
                    session,
                    run,
                    OffboardingActionKind.CANCEL_PENDING_TOP_UP,
                    OffboardingActionState.PENDING_CARRIER,
                    target=target,
                    detail="supplier outcome must be reconciled before cancellation",
                )
                continue
            if top_up.state is TopUpState.PAID:
                self._record(
                    session,
                    run,
                    OffboardingActionKind.CANCEL_PENDING_TOP_UP,
                    OffboardingActionState.FAILED,
                    target=target,
                    detail="settled top-up requires an explicit refund",
                )
                continue

            try:
                if top_up.state is TopUpState.RESERVED:
                    reservation = (
                        session.get(Reservation, top_up.reservation_id)
                        if top_up.reservation_id is not None
                        else None
                    )
                    if reservation is None:
                        raise OffboardingError("top_up_reservation_missing")
                    self.ledger.release(session, reservation)
                top_up.state = TopUpState.FAILED
                top_up.detail = "offboarded before top-up settlement"
                session.add(top_up)
                self._record(
                    session,
                    run,
                    OffboardingActionKind.CANCEL_PENDING_TOP_UP,
                    OffboardingActionState.CONFIRMED,
                    target=target,
                )
            except (LedgerError, OffboardingError) as error:
                self._record(
                    session,
                    run,
                    OffboardingActionKind.CANCEL_PENDING_TOP_UP,
                    OffboardingActionState.FAILED,
                    target=target,
                    detail=str(error),
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
        identity = [col(BulkJobItem.person_id) == person.id]
        if person.user_id is not None:
            identity.extend(
                [
                    col(OrderItem.recipient_user_id) == person.user_id,
                    col(Entitlement.holder_user_id) == person.user_id,
                ]
            )
        return session.exec(
            select(CarrierLine)
            .join(Entitlement, col(CarrierLine.entitlement_id) == col(Entitlement.id))
            .join(OrderItem, col(Entitlement.order_item_id) == col(OrderItem.id))
            .join(Order, col(OrderItem.order_id) == col(Order.id))
            .outerjoin(
                BulkJobItem,
                col(BulkJobItem.order_item_id) == col(OrderItem.id),
            )
            .where(
                Order.payer_organization_id == organization_id,
                or_(*identity),
            )
            .distinct()
        ).all()

    def _work_entitlements(
        self, session: Session, organization_id: UUID, person: OrganizationPerson
    ) -> Sequence[Entitlement]:
        """Local grants paid for by this organization and assigned to a person."""
        identity = [col(BulkJobItem.person_id) == person.id]
        if person.user_id is not None:
            identity.extend(
                [
                    col(OrderItem.recipient_user_id) == person.user_id,
                    col(Entitlement.holder_user_id) == person.user_id,
                ]
            )
        return session.exec(
            select(Entitlement)
            .join(OrderItem, col(Entitlement.order_item_id) == col(OrderItem.id))
            .join(Order, col(OrderItem.order_id) == col(Order.id))
            .outerjoin(
                BulkJobItem,
                col(BulkJobItem.order_item_id) == col(OrderItem.id),
            )
            .where(
                Order.payer_organization_id == organization_id,
                or_(*identity),
            )
            .distinct()
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
        failed = [
            action
            for action in actions
            if action.state is OffboardingActionState.FAILED
        ]
        if failed:
            run.state = OffboardingState.COMPLETED_WITH_EXCEPTIONS
        elif pending:
            run.state = OffboardingState.COMPLETED_WITH_PENDING
        else:
            run.state = OffboardingState.COMPLETED
        run.completed_at = self.clock()
        session.add(run)
        session.flush()
        return self.summary(session, run)

    def confirm_action(
        self, session: Session, action: OffboardingAction, *, detail: str | None = None
    ) -> OffboardingAction:
        """A carrier answered. The run may now be finished rather than pending."""
        if action.state is OffboardingActionState.CONFIRMED:
            return action
        if action.state is not OffboardingActionState.PENDING_CARRIER:
            raise OffboardingError("offboarding_action_not_pending")

        if (
            action.kind is OffboardingActionKind.SUSPEND_LINE
            and action.target_reference
            and action.target_reference.startswith("line:")
        ):
            try:
                line_id = UUID(action.target_reference.removeprefix("line:"))
            except ValueError as error:  # pragma: no cover - our writer owns it
                raise OffboardingError("offboarding_action_target_invalid") from error
            line = session.get(CarrierLine, line_id)
            if line is None:
                raise OffboardingError("offboarding_action_target_missing")
            line.activation_state = ActivationState.SUSPENDED
            session.add(line)

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
