"""Top-ups, spending bounds, expiry and suspension policy (US-36, chunk 17).

Chunk 15 built the line lifecycle and chunk 16 built the meter. This is the part
that decides what to *do* about a balance, and its hardest requirement is a
refusal.

## The refusal

`prd.md` AC-36.4 and the chunk assignment both say it: **do not claim delayed app
accounting stops native calls.** The Telnyx capability record explains why that
bites here — the data limit's network-side enforcement latency is undocumented,
and no voice spending cap is documented at all.

So `prepaid_guarantee` returns whether a hard cap can honestly be promised, and
for Telnyx today the answer is **no**, with the reason attached. An offer that
depends on one stays gated. Building the accounting and calling it a guarantee
would be the easy path and the wrong one: the customer discovers the difference
during a call they cannot afford.

The approved calling amendment sharpens the same point for the shared-credit
case: *"Carrier spend has its own reservation/control mechanism while the app is
closed. A unified displayed balance is insufficient."* `shared_credit_allowed`
implements exactly that check.

## Top-ups

The states are named so partial ones are recoverable, and the ordering is the
chunk 11 ordering for the same reason: money is reserved before it is taken,
taken before allowance is granted, and a supplier request whose outcome is
unknown is reconciled rather than repeated.

The property worth stating plainly, because it is what the assignment asks for
twice: **a top-up never gives away allowance and never loses paid credit.**
Consumption already recorded stays recorded, so topping up after an overshoot
adds to a deficit rather than resetting it; and a top-up that fails releases its
hold rather than keeping the customer's money.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.auth.models import utc_now
from app.connectivity.contract import (
    Capability,
    ConnectivityAdapter,
    ConnectivityError,
    ConnectivityOutcomeUnknown,
)
from app.connectivity.models import (
    ActivationState,
    CarrierLine,
    CarrierLineAction,
    Entitlement,
    LineActionKind,
)
from app.connectivity.service import ConnectivityService
from app.controls.models import (
    SPENDABLE_TOP_UP_STATES,
    AllowanceNotice,
    ControlState,
    Enforcement,
    EntitlementTopUp,
    OrganizationSpendingPolicy,
    SpendingControl,
    TopUpState,
)
from app.ledger.models import LedgerAccount, Reservation
from app.ledger.service import LedgerError, LedgerService
from app.money import round_money
from app.orders.models import Order, OrderItem
from app.refunds.models import ExceptionKind
from app.usage.service import AllowanceView, Freshness, UsageService

#: The thresholds a customer is told about. Percentages of the granted total,
#: not absolute figures: "you have 500 MB left" means different things on a
#: 1 GB plan and a 50 GB one.
DEFAULT_NOTICE_THRESHOLDS = (50, 80, 95)


class ControlError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


@dataclass(frozen=True)
class GuaranteeAssessment:
    """Whether a hard prepaid cap can be promised, and why not when it cannot.

    A boolean alone would be useless to the product decision this feeds. The
    reason is what tells somebody whether the answer changes with a Telnyx
    email, a policy approval, or neither.
    """

    can_promise: bool
    enforcement: Enforcement
    reason: str
    #: The documented worst case, when it is documented. `None` means
    #: unquantified — which is precisely why a guarantee cannot be made.
    max_overshoot_bytes: int | None = None


@dataclass(frozen=True)
class TopUpQuote:
    """What a top-up would grant and what it would cost. Nothing reserved yet."""

    data_bytes: int
    voice_seconds: int
    extends_days: int
    currency: str
    amount: Decimal


class ControlService:
    def __init__(
        self,
        usage: UsageService,
        connectivity: ConnectivityService,
        ledger: LedgerService | None = None,
        clock: Callable[[], datetime] = utc_now,
        notice_thresholds: Sequence[int] = DEFAULT_NOTICE_THRESHOLDS,
    ) -> None:
        self.usage = usage
        self.connectivity = connectivity
        self.ledger = ledger
        self.clock = clock
        self.notice_thresholds = tuple(sorted(notice_thresholds))

    # --- what may be promised ---------------------------------------------

    def prepaid_guarantee(
        self, adapter: ConnectivityAdapter, control: SpendingControl | None = None
    ) -> GuaranteeAssessment:
        """Can a hard prepaid cap be promised for lines on this supplier?

        Three ways to get a yes, and only three:

        1. The supplier advertises verified `SPENDING_ENFORCEMENT` **and** the
           line's control is confirmed active with a limit the supplier
           acknowledged.
        2. Somebody approved a bounded-exposure policy with a named reference —
           accepting a quantified maximum overshoot rather than claiming none.
        3. Nothing else.

        Delayed app-side accounting is not one of them, and this is the function
        that says so out loud rather than a comment nobody reads at sale time.
        """
        capabilities = adapter.capabilities()
        if control is not None and control.enforcement is (
            Enforcement.APPROVED_BOUNDED_EXPOSURE
        ):
            return GuaranteeAssessment(
                can_promise=True,
                enforcement=Enforcement.APPROVED_BOUNDED_EXPOSURE,
                reason=(
                    "a bounded-exposure policy is approved under "
                    f"{control.policy_reference}; exposure is capped at a "
                    "quantified maximum rather than at zero"
                ),
                max_overshoot_bytes=control.max_overshoot_bytes,
            )
        if not capabilities.supports(Capability.SPENDING_ENFORCEMENT):
            return GuaranteeAssessment(
                can_promise=False,
                enforcement=Enforcement.NONE,
                reason=capabilities.undocumented.get(
                    Capability.SPENDING_ENFORCEMENT.value,
                    f"{adapter.name} does not advertise verified supplier-side "
                    "spending enforcement",
                ),
            )
        if control is None or control.state is not ControlState.ACTIVE:
            return GuaranteeAssessment(
                can_promise=False,
                enforcement=Enforcement.NONE,
                reason=(
                    "the supplier can enforce a limit but none is confirmed on "
                    "this line; a cap nobody set stops nothing"
                ),
            )
        if control.max_overshoot_bytes is None:
            # The Telnyx case, and the reason it stays gated even if the
            # capability were switched on: a limit whose enforcement latency is
            # undocumented has an unbounded overshoot, and an unbounded
            # overshoot is not a cap.
            return GuaranteeAssessment(
                can_promise=False,
                enforcement=Enforcement.NONE,
                reason=(
                    "the supplier's enforcement latency is undocumented, so the "
                    "overshoot is unquantified; approve a bounded-exposure "
                    "policy or obtain a documented bound"
                ),
            )
        return GuaranteeAssessment(
            can_promise=True,
            enforcement=Enforcement.PROVIDER_HARD_LIMIT,
            reason=f"{adapter.name} confirms a hard limit on this line",
            max_overshoot_bytes=control.max_overshoot_bytes,
        )

    def shared_credit_allowed(
        self, adapter: ConnectivityAdapter, control: SpendingControl | None = None
    ) -> tuple[bool, str]:
        """May carrier and internet calling draw on one pool of credit?

        The approved calling amendment: *"Carrier spend has its own
        reservation/control mechanism while the app is closed. A unified
        displayed balance is insufficient: allocate bounded carrier exposure
        separately before native use, or prove equivalent atomic provider
        enforcement. Without that, do not offer an unrestricted common spend
        pool or hard cap."*

        A shared pool is only safe if the carrier half is independently bounded,
        because the app is not running while a native call is placed and cannot
        stop it. So this answers the same question as `prepaid_guarantee`, and
        deliberately gives the same answer — one function is the product
        promise, the other is the product shape, and they cannot disagree.
        """
        assessment = self.prepaid_guarantee(adapter, control)
        if assessment.can_promise:
            return True, assessment.reason
        return False, (
            "carrier exposure is not independently bounded while the app is "
            f"closed ({assessment.reason}); a shared credit pool would let a "
            "native call spend internet-calling credit with nothing able to "
            "stop it"
        )

    # --- spending controls -------------------------------------------------

    def control_for(self, session: Session, line: CarrierLine) -> SpendingControl:
        existing = session.exec(
            select(SpendingControl).where(SpendingControl.carrier_line_id == line.id)
        ).first()
        if existing is not None:
            return existing
        control = SpendingControl(
            carrier_line_id=line.id,
            enforcement=Enforcement.NONE,
            state=ControlState.REQUESTED,
            requested_at=self.clock(),
        )
        session.add(control)
        session.flush()
        return control

    def apply_provider_limit(
        self,
        session: Session,
        line: CarrierLine,
        adapter: ConnectivityAdapter,
        limit_bytes: int,
        max_overshoot_bytes: int | None = None,
    ) -> SpendingControl:
        """Ask the supplier to enforce a cap, and record what it confirmed.

        `requested` and `confirmed` are separate fields for the whole duration
        of this call: a UI showing the requested figure while the change is in
        flight tells a customer their cap has moved when it has not.

        A lost response leaves `OUTCOME_UNKNOWN` and does **not** re-send.
        Re-sending races a change that may already have applied, and on a
        supplier where raising a cap is how a suspended line comes back, sending
        it twice is the difference between one raise and two.
        """
        control = self.control_for(session, line)
        control.requested_limit_bytes = limit_bytes
        control.requested_at = self.clock()
        control.state = ControlState.REQUESTED
        session.add(control)
        session.flush()

        setter = getattr(adapter, "set_data_limit", None)
        if setter is None:
            control.state = ControlState.FAILED
            control.enforcement = Enforcement.NONE
            control.detail = (
                f"{adapter.name} exposes no way to set a supplier-side limit"
            )
            session.add(control)
            session.flush()
            return control

        try:
            line_view = setter(line.carrier_line_reference, limit_bytes)
        except ConnectivityOutcomeUnknown as exc:
            control.state = ControlState.OUTCOME_UNKNOWN
            control.enforcement = Enforcement.NONE
            control.detail = f"outcome unknown: {exc.reason}"[:500]
            session.add(control)
            self.usage.raise_exception(
                session,
                ExceptionKind.USAGE_DISCREPANCY,
                f"spending-control:{control.id}",
                "a spending-limit change did not return; the supplier may or "
                "may not have applied it. Read the line before re-sending.",
            )
            session.flush()
            return control
        except ConnectivityError as exc:
            control.state = ControlState.FAILED
            control.enforcement = Enforcement.NONE
            control.detail = (exc.detail or exc.code)[:500]
            session.add(control)
            session.flush()
            return control

        confirmed = line_view.data_limit_bytes
        if confirmed is None:
            # The supplier accepted the call and reported no limit. That is not
            # a confirmation, and recording it as one would put a cap in the
            # database that does not exist at the carrier.
            control.state = ControlState.FAILED
            control.enforcement = Enforcement.NONE
            control.detail = "the supplier reported no data limit after the change"
        else:
            control.confirmed_limit_bytes = confirmed
            control.confirmed_at = self.clock()
            control.state = ControlState.ACTIVE
            control.max_overshoot_bytes = max_overshoot_bytes
            control.enforcement = Enforcement.PROVIDER_HARD_LIMIT
        session.add(control)
        session.flush()
        return control

    def approve_bounded_exposure(
        self,
        session: Session,
        line: CarrierLine,
        policy_reference: str,
        max_overshoot_bytes: int,
    ) -> SpendingControl:
        """Record an approved policy that accepts a quantified overshoot.

        The alternative to a hard cap, and an honest one: somebody with the
        authority decided how much exposure is acceptable and put their name on
        it. `ck_spending_controls_policy_needs_reference` refuses it without the
        reference, because an approval nobody can find is not an approval.
        """
        if not policy_reference:
            raise ControlError(
                "policy_reference_required",
                "a bounded-exposure approval must name the decision behind it",
            )
        if max_overshoot_bytes < 0:
            raise ControlError("negative_overshoot")
        control = self.control_for(session, line)
        control.enforcement = Enforcement.APPROVED_BOUNDED_EXPOSURE
        control.policy_reference = policy_reference
        control.max_overshoot_bytes = max_overshoot_bytes
        control.state = ControlState.ACTIVE
        control.confirmed_at = self.clock()
        session.add(control)
        session.flush()
        return control

    # --- allowance, including top-ups --------------------------------------

    def allowance(
        self, session: Session, entitlement: Entitlement, now: datetime | None = None
    ) -> AllowanceView:
        """Chunk 16's balance, plus whatever has been topped up and applied.

        Only `APPLIED` top-ups count. A customer who has paid but whose supplier
        cap has not been raised does not yet have the data, and telling them
        they do produces a session that fails for reasons the app just denied.
        """
        base = self.usage.allowance(session, entitlement, now=now)
        granted = self.applied_top_ups(session, entitlement)
        if granted == (0, 0, 0):
            return base
        data_bytes, voice_seconds, extra_days = granted
        expires_at = base.expires_at
        if expires_at is not None and extra_days:
            expires_at = expires_at + timedelta(days=extra_days)
        return AllowanceView(
            entitlement_id=base.entitlement_id,
            data_bytes_total=base.data_bytes_total + data_bytes,
            data_bytes_used=base.data_bytes_used,
            voice_seconds_total=base.voice_seconds_total + voice_seconds,
            voice_seconds_used=base.voice_seconds_used,
            observed_at=base.observed_at,
            freshness=base.freshness,
            expires_at=expires_at,
            has_provisional=base.has_provisional,
        )

    def applied_top_ups(
        self, session: Session, entitlement: Entitlement
    ) -> tuple[int, int, int]:
        row = session.exec(
            select(
                func.coalesce(func.sum(EntitlementTopUp.data_bytes), 0),
                func.coalesce(func.sum(EntitlementTopUp.voice_seconds), 0),
                func.coalesce(func.sum(EntitlementTopUp.extends_days), 0),
            ).where(
                EntitlementTopUp.entitlement_id == entitlement.id,
                col(EntitlementTopUp.state).in_(SPENDABLE_TOP_UP_STATES),
            )
        ).first()
        if row is None:
            return (0, 0, 0)
        return (int(row[0]), int(row[1]), int(row[2]))

    def is_expired(
        self, session: Session, entitlement: Entitlement, now: datetime | None = None
    ) -> bool:
        """Expiry includes any extension a top-up bought.

        Reading `entitlements.expires_at` directly would suspend a line whose
        owner has already paid to keep it, which is the worst possible moment to
        get this wrong.
        """
        view = self.allowance(session, entitlement, now=now)
        if view.expires_at is None:
            return False
        return _aware(view.expires_at) <= _aware(now or self.clock())

    # --- top-ups -----------------------------------------------------------

    def request_top_up(
        self,
        session: Session,
        entitlement: Entitlement,
        order_item: OrderItem,
        quote: TopUpQuote,
    ) -> EntitlementTopUp:
        """Record the intention. Idempotent on the order item.

        A replayed request returns the existing top-up rather than creating a
        second one — the unique constraint is the backstop, and returning the
        original is what makes a worker retry harmless rather than an error.
        """
        existing = session.exec(
            select(EntitlementTopUp).where(
                EntitlementTopUp.order_item_id == order_item.id
            )
        ).first()
        if existing is not None:
            return existing
        if quote.data_bytes < 0 or quote.voice_seconds < 0 or quote.extends_days < 0:
            raise ControlError("negative_grant")
        if not (quote.data_bytes or quote.voice_seconds or quote.extends_days):
            raise ControlError(
                "empty_top_up", "a top-up that grants nothing is not a purchase"
            )

        top_up = EntitlementTopUp(
            entitlement_id=entitlement.id,
            order_item_id=order_item.id,
            business_event_id=f"topup:{order_item.id}",
            data_bytes=quote.data_bytes,
            voice_seconds=quote.voice_seconds,
            extends_days=quote.extends_days,
            currency=quote.currency,
            amount=round_money(quote.amount, quote.currency),
            state=TopUpState.REQUESTED,
            requested_at=self.clock(),
        )
        session.add(top_up)
        session.flush()
        return top_up

    def reserve_top_up(
        self, session: Session, top_up: EntitlementTopUp, account: LedgerAccount
    ) -> Reservation:
        """Hold the funds atomically, before anything is granted.

        Delegates to chunk 10, which takes the account row lock. Two concurrent
        top-ups competing for the same balance therefore cannot both succeed —
        which is the concurrency case the assignment asks for, and it is
        enforced by a `SELECT … FOR UPDATE` rather than by ordering luck.
        """
        if self.ledger is None:
            raise ControlError("no_ledger")
        if top_up.state not in (TopUpState.REQUESTED, TopUpState.RESERVED):
            raise ControlError(
                "top_up_not_reservable", f"top-up is {top_up.state.value}"
            )
        if account.currency != top_up.currency:
            raise ControlError("cross_currency_top_up")
        reservation = self.ledger.reserve(
            session,
            account,
            top_up.amount,
            business_event_id=f"{top_up.business_event_id}:reserve",
        )
        top_up.state = TopUpState.RESERVED
        session.add(top_up)
        session.flush()
        return reservation

    def settle_top_up(
        self,
        session: Session,
        top_up: EntitlementTopUp,
        reservation: Reservation,
        revenue_account: LedgerAccount,
    ) -> EntitlementTopUp:
        """Take the money. The allowance is still not theirs.

        Separate from `apply_top_up` because they can fail independently, and
        because a customer who has paid must not lose their money if the
        supplier call then fails — `PAID` is a state somebody can be refunded
        from, and a state where nothing has been given away.
        """
        if self.ledger is None:
            raise ControlError("no_ledger")
        if top_up.state is TopUpState.PAID:
            return top_up
        if top_up.state is not TopUpState.RESERVED:
            raise ControlError("top_up_not_reserved", f"top-up is {top_up.state.value}")
        self.ledger.settle(
            session,
            reservation,
            top_up.amount,
            business_event_id=f"{top_up.business_event_id}:settle",
            credit_account=revenue_account,
        )
        top_up.state = TopUpState.PAID
        session.add(top_up)
        session.flush()
        return top_up

    def apply_top_up(
        self,
        session: Session,
        top_up: EntitlementTopUp,
        line: CarrierLine,
        adapter: ConnectivityAdapter | None = None,
    ) -> EntitlementTopUp:
        """Grant the allowance, raising the supplier cap first if there is one.

        Order matters and it is the cautious order: if a supplier-enforced limit
        is in force, it is raised **before** the allowance becomes spendable. A
        customer told they have more data while the carrier is still enforcing
        the old cap gets a plan that does not work and an app that says it does.

        A lost supplier response leaves `OUTCOME_UNKNOWN`. The allowance is not
        granted and the money is not returned, because neither is known to be
        right yet — that is what reconciliation is for, and guessing either way
        costs somebody something.
        """
        if top_up.state is TopUpState.APPLIED:
            return top_up
        if top_up.state not in (TopUpState.PAID, TopUpState.PROVISIONING):
            raise ControlError("top_up_not_payable", f"top-up is {top_up.state.value}")

        control = session.exec(
            select(SpendingControl).where(SpendingControl.carrier_line_id == line.id)
        ).first()
        needs_raise = (
            adapter is not None
            and control is not None
            and control.state is ControlState.ACTIVE
            and control.enforcement is Enforcement.PROVIDER_HARD_LIMIT
            and control.confirmed_limit_bytes is not None
            and top_up.data_bytes > 0
        )
        if needs_raise:
            assert adapter is not None and control is not None
            assert control.confirmed_limit_bytes is not None
            top_up.state = TopUpState.PROVISIONING
            session.add(top_up)
            session.flush()
            raised = self.apply_provider_limit(
                session,
                line,
                adapter,
                control.confirmed_limit_bytes + top_up.data_bytes,
                max_overshoot_bytes=control.max_overshoot_bytes,
            )
            if raised.state is ControlState.OUTCOME_UNKNOWN:
                top_up.state = TopUpState.OUTCOME_UNKNOWN
                top_up.detail = (
                    "the supplier did not confirm the raised cap; reconcile "
                    "before re-sending"
                )
                session.add(top_up)
                session.flush()
                return top_up
            if raised.state is not ControlState.ACTIVE:
                top_up.state = TopUpState.FAILED
                top_up.detail = (raised.detail or "the supplier refused the cap")[:500]
                session.add(top_up)
                session.flush()
                return top_up

        top_up.state = TopUpState.APPLIED
        top_up.applied_at = self.clock()
        session.add(top_up)
        session.flush()
        return top_up

    def fail_top_up(
        self,
        session: Session,
        top_up: EntitlementTopUp,
        reason: str,
        reservation: Reservation | None = None,
    ) -> EntitlementTopUp:
        """Give the hold back. Never the settled money, which is a refund.

        The line matters: releasing a *reservation* returns availability that
        was never spent, while money already settled is chunk 14's to refund.
        Conflating them would either invent a transaction or quietly keep a
        customer's payment.
        """
        if top_up.state is TopUpState.APPLIED:
            raise ControlError(
                "top_up_already_applied",
                "reversing granted allowance is a refund decision, not a failure",
            )
        if reservation is not None and self.ledger is not None:
            try:
                self.ledger.release(session, reservation)
            except LedgerError as exc:
                if exc.code != "reservation_closed":
                    raise
        top_up.state = TopUpState.FAILED
        top_up.detail = reason[:500]
        session.add(top_up)
        session.flush()
        return top_up

    # --- organization budgets ---------------------------------------------

    def budget_headroom(
        self,
        session: Session,
        organization_id: UUID,
        currency: str,
        since: datetime,
    ) -> Decimal | None:
        """What an organization may still spend on top-ups this period.

        `None` means no policy is recorded, which is not the same as zero and
        not the same as unlimited — it means nobody has decided, and the caller
        is left to say so rather than being handed a number that implies one.

        Chunk 24 owns real enterprise budgets. This is the part chunk 17 needs
        to refuse a top-up that would exceed a recorded cap.
        """
        policy = session.exec(
            select(OrganizationSpendingPolicy).where(
                OrganizationSpendingPolicy.organization_id == organization_id,
                OrganizationSpendingPolicy.currency == currency,
            )
        ).first()
        if policy is None or not policy.enforced:
            return None
        spent = session.exec(
            select(func.coalesce(func.sum(EntitlementTopUp.amount), 0))
            .join(OrderItem, col(EntitlementTopUp.order_item_id) == col(OrderItem.id))
            .join(Order, col(OrderItem.order_id) == col(Order.id))
            .where(
                Order.payer_organization_id == organization_id,
                EntitlementTopUp.currency == currency,
                # Committed spend, not just applied: a reserved or paid top-up
                # is money the organization has already committed, and
                # excluding it lets two purchases both fit under one cap.
                col(EntitlementTopUp.state).notin_([TopUpState.FAILED]),
                col(EntitlementTopUp.requested_at) >= since,
            )
        ).first()
        return round_money(
            policy.period_cap_amount - Decimal(spent or 0), currency
        )

    def check_budget(
        self,
        session: Session,
        order_item: OrderItem,
        quote: TopUpQuote,
        since: datetime,
    ) -> None:
        """Refuse a top-up that would take an organization past its cap."""
        order = session.get(Order, order_item.order_id)
        if order is None or order.payer_organization_id is None:
            return
        headroom = self.budget_headroom(
            session, order.payer_organization_id, quote.currency, since
        )
        if headroom is None:
            return
        if round_money(quote.amount, quote.currency) > headroom:
            raise ControlError(
                "budget_exceeded",
                f"{quote.amount} {quote.currency} exceeds the remaining "
                f"{headroom} {quote.currency} of this organization's cap",
            )

    # --- notices -----------------------------------------------------------

    def low_balance_notices(
        self, session: Session, entitlement: Entitlement
    ) -> list[AllowanceNotice]:
        """Which thresholds have been crossed and not yet announced.

        Two rules, both about not lying and not nagging:

        - **An unobserved balance announces nothing.** A line nobody has polled
          has not crossed anything; a "you have used 80%" notice derived from a
          grant and no measurement is an invention.
        - **Each threshold announces once.** Usage corrected downward and back
          up re-crosses 80%, and the unique constraint makes that silent.
        """
        view = self.allowance(session, entitlement)
        if view.freshness is Freshness.UNKNOWN:
            return []

        raised: list[AllowanceNotice] = []
        for kind, used, total in (
            ("data", view.data_bytes_used, view.data_bytes_total),
            ("voice", view.voice_seconds_used, view.voice_seconds_total),
        ):
            if total <= 0:
                continue
            percent = (used * 100) // total
            for threshold in self.notice_thresholds:
                if percent < threshold:
                    continue
                existing = session.exec(
                    select(AllowanceNotice).where(
                        AllowanceNotice.entitlement_id == entitlement.id,
                        AllowanceNotice.kind == kind,
                        AllowanceNotice.threshold_percent == threshold,
                    )
                ).first()
                if existing is not None:
                    continue
                notice = AllowanceNotice(
                    entitlement_id=entitlement.id,
                    kind=kind,
                    threshold_percent=threshold,
                    notified_at=self.clock(),
                )
                session.add(notice)
                raised.append(notice)
        session.flush()
        return raised

    # --- suspension policy -------------------------------------------------

    def suspend_for_exhaustion(
        self,
        session: Session,
        entitlement: Entitlement,
        line: CarrierLine,
        adapter: ConnectivityAdapter,
    ) -> CarrierLineAction | None:
        """Suspend an exhausted or expired line — as a request, not a fact.

        Returns `None` when there is nothing to do, including the case that
        matters most: **an unobserved balance suspends nobody.** Cutting off a
        customer because a poller has never run is worse than the overshoot it
        would prevent, and the balance would be an invention anyway.

        The suspension itself goes through chunk 15's four-state machine, so the
        line moves when the carrier confirms and not when we ask.
        """
        view = self.allowance(session, entitlement)
        if view.freshness is Freshness.UNKNOWN and not self.is_expired(
            session, entitlement
        ):
            return None
        exhausted = (
            view.data_bytes_remaining <= 0 and view.voice_seconds_remaining <= 0
        )
        if not exhausted and not self.is_expired(session, entitlement):
            return None
        if line.activation_state in (
            ActivationState.SUSPENDED,
            ActivationState.TERMINATED,
        ):
            return None

        action = self.connectivity.request_action(
            session, line, LineActionKind.SUSPEND
        )
        return self.connectivity.dispatch_action(session, action, line, adapter)

    def resume_after_top_up(
        self,
        session: Session,
        entitlement: Entitlement,
        line: CarrierLine,
        adapter: ConnectivityAdapter,
    ) -> CarrierLineAction | None:
        """Bring a line back once there is something to bring it back for.

        Refuses while the allowance is still exhausted: resuming a line with no
        allowance produces a customer who can spend money they have not got, on
        a supplier that will not stop them.

        Refuses outright when the carrier stopped the line itself. A
        `data_limit_exceeded` line is not one we suspended, and a resume request
        would be refused by the carrier anyway — only raising the limit clears
        it. Saying so here gives an operator something to act on instead of a
        supplier rejection nobody can read.
        """
        if line.provider_status in ("data_limit_exceeded", "unauthorized_imei"):
            raise ControlError(
                "carrier_imposed_restriction",
                f"the carrier reports {line.provider_status}; this is not our "
                "suspension and resuming it will not clear it",
            )
        view = self.allowance(session, entitlement)
        if view.data_bytes_remaining <= 0 and view.voice_seconds_remaining <= 0:
            raise ControlError(
                "still_exhausted",
                "resuming a line with no allowance lets a customer spend credit "
                "they do not have",
            )
        if self.is_expired(session, entitlement):
            raise ControlError("still_expired")
        if line.activation_state is ActivationState.ACTIVE:
            return None

        action = self.connectivity.request_action(
            session, line, LineActionKind.RESUME
        )
        return self.connectivity.dispatch_action(session, action, line, adapter)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
