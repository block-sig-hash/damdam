"""Turning a held reservation into money, once, with evidence — US-46, V03.

V02 stops at the hold on purpose: *a reservation stays held until every known
supplier liability is final*. This module is what decides that liability is
final, and it is written around four facts that make that decision harder than
it sounds.

**The provider's account of the call is incomplete.** Events are duplicated,
delayed, reordered and sometimes describe a leg nobody recognises (V01 §4–§5).
So settlement reads `call_legs` — our own converged record — and never a client's
elapsed time, a wall clock or a hangup request. A browser that closed and an app
that was killed both produce the same number here, because neither is consulted.

**"We do not know" is not "it was free".** An answered leg with no recorded end
is unmetered liability. Releasing the hold there funds nothing and un-funds a
call that may still be connected, so the money stays held, a deadline is written
and a human is told. Chunk 16 made the same choice for a stalled usage poller.

**The customer authorized a maximum, and that maximum binds us too.** If metered
cost exceeds the hold, the customer is charged the hold — never more than they
agreed to — and the difference goes to the exception queue as our exposure. A
settlement that quietly took more than was authorized would be the one thing a
prepaid product may not do.

**Supplier cost is a separate number.** V01's worksheet establishes the published
unit prices and explicitly not how many billable components a call produces, so
nothing here derives a retail amount from a supplier cost or vice versa. They are
reconciled by a person looking at an exception, not by arithmetic nobody checked.

Renewal extends the reservation's expiry lease, never its amount. The amount is
`max_charge_amount`, computed from `max_seconds`, which the provider also
enforces as `time_limit_secs`: the authorized maximum is the *whole* liability.
Each renewal re-asks whether the call may continue — the hold is still open,
organization budget remains unexhausted, and carrier exposure stays separately
bounded — before extending that lease. Increasing the amount would mean charging
a customer for a call they never agreed the price of.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from uuid import UUID

from sqlalchemy import func, or_, text
from sqlmodel import Session, col, select

from app.auth.models import utc_now
from app.calling.contract import LegRole
from app.calling.metering import (
    MeteringError,
    MeteringOutcome,
    charge_for,
    talk_interval,
)
from app.calling.models import (
    TERMINAL_ATTEMPT_STATES,
    AttemptState,
    CallAttempt,
    CallCharge,
    CallDeadline,
    CallLeg,
    CallSupplierCost,
    ChargeBasis,
    ChargeState,
    DeadlineKind,
    DeadlineState,
    PayerKind,
    SupplierCostComponent,
)
from app.controls.service import ControlService
from app.ledger.models import (
    AccountKind,
    Direction,
    LedgerAccount,
    OwnerKind,
    Reservation,
    ReservationState,
)
from app.ledger.service import LedgerService, Posting
from app.money import round_money
from app.refunds.models import ExceptionItem, ExceptionKind


class ChargingError(Exception):
    """A settlement that must not proceed as asked."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


class SettlementStatus(str, Enum):
    """What settling an attempt actually did.

    A status rather than an exception because three of these four are ordinary
    outcomes of a healthy system, and a caller that has to catch exceptions to
    handle ordinary outcomes eventually catches them all in one place.
    """

    #: Money moved; unused authorization stays held while the charge is provisional.
    SETTLED = "settled"
    #: Nobody answered. The whole hold went back; no entry was posted.
    NOTHING_TO_CHARGE = "nothing_to_charge"
    #: Liability is not final. The hold stays, a deadline is set, a human is told.
    DEFERRED = "deferred"
    #: Two answered destination legs. Nothing is settled automatically.
    AMBIGUOUS = "ambiguous"


class EnforcementDecision(str, Enum):
    CONTINUE = "continue"
    STOP = "stop"


@dataclass(frozen=True)
class SettlementResult:
    status: SettlementStatus
    charge: CallCharge | None = None
    #: Metered cost the hold could not cover. Our exposure, never the
    #: customer's surprise.
    shortfall: Decimal | None = None
    exception_item: ExceptionItem | None = None


@dataclass(frozen=True)
class EnforcementOutcome:
    decision: EnforcementDecision
    reason: str


class CallChargingService:
    """Metering, settlement, corrections and the durable deadlines around them."""

    def __init__(
        self,
        ledger: LedgerService,
        *,
        controls: ControlService | None = None,
        clock: Callable[[], datetime] = utc_now,
        supplier_cost_wait_seconds: int = 86_400,
        unknown_review_seconds: int = 900,
        missing_terminal_seconds: int = 3_600,
        renewal_interval_seconds: int = 60,
        claim_timeout_seconds: int = 300,
    ) -> None:
        self.ledger = ledger
        self.controls = controls
        self.clock = clock
        self.supplier_cost_wait_seconds = supplier_cost_wait_seconds
        self.unknown_review_seconds = unknown_review_seconds
        self.missing_terminal_seconds = missing_terminal_seconds
        self.renewal_interval_seconds = renewal_interval_seconds
        self.claim_timeout_seconds = claim_timeout_seconds

    # --- settlement -------------------------------------------------------

    def settle(
        self,
        session: Session,
        attempt: CallAttempt,
        *,
        revenue_account: LedgerAccount | None = None,
    ) -> SettlementResult:
        """Charge one finished attempt, once.

        Idempotent twice over: the live-charge index means a replay finds the
        row rather than writing a second one, and the ledger event id means even
        a caller that bypassed this method could not post the movement twice.
        """
        self._lock(session, f"call-settlement:{attempt.id}")
        existing = self._live_charge(session, attempt)
        if existing is not None:
            return SettlementResult(
                SettlementStatus.SETTLED
                if existing.charged_amount > 0
                else SettlementStatus.NOTHING_TO_CHARGE,
                existing,
            )

        if (
            attempt.state not in TERMINAL_ATTEMPT_STATES
            and attempt.state is not AttemptState.UNKNOWN
        ):
            raise ChargingError(
                "call_not_finished",
                "an attempt that has not reached a terminal state has no "
                "final duration to charge for",
            )
        # `UNKNOWN` is deliberately *not* terminal in V02 — a real observation
        # always supersedes it — but it is the state this chunk exists to
        # resolve. It is settled only if the legs turn out to be complete
        # after all, which is the late-terminal-event case; otherwise the
        # metering below defers it with the hold intact.

        legs = self._legs(session, attempt)
        if attempt.state is AttemptState.UNKNOWN and not any(
            leg.role is LegRole.DESTINATION for leg in legs
        ):
            item = self.raise_exception(
                session,
                ExceptionKind.CALL_UNKNOWN_OUTCOME,
                f"call:{attempt.id}",
                "the destination command outcome is unknown and no provider "
                "leg has been correlated; the hold stays until reconciliation",
            )
            self.schedule(
                session,
                attempt,
                DeadlineKind.UNKNOWN_OUTCOME_REVIEW,
                self.clock() + timedelta(seconds=self.unknown_review_seconds),
            )
            return SettlementResult(
                SettlementStatus.DEFERRED, exception_item=item
            )
        try:
            interval = talk_interval(legs)
        except MeteringError as error:
            item = self.raise_exception(
                session,
                ExceptionKind.CALL_DUPLICATE_BILLABLE_LEG,
                f"call:{attempt.id}",
                f"legs cannot be metered: {error.detail or error.code}",
            )
            self.schedule(
                session,
                attempt,
                DeadlineKind.UNKNOWN_OUTCOME_REVIEW,
                self.clock() + timedelta(seconds=self.unknown_review_seconds),
            )
            return SettlementResult(
                SettlementStatus.AMBIGUOUS, exception_item=item
            )

        if interval.outcome is MeteringOutcome.AMBIGUOUS:
            item = self.raise_exception(
                session,
                ExceptionKind.CALL_DUPLICATE_BILLABLE_LEG,
                f"call:{attempt.id}",
                "two answered destination legs on one authorized attempt; the "
                "hold stays until a human decides which call this was",
            )
            self.schedule(
                session,
                attempt,
                DeadlineKind.UNKNOWN_OUTCOME_REVIEW,
                self.clock() + timedelta(seconds=self.unknown_review_seconds),
            )
            return SettlementResult(SettlementStatus.AMBIGUOUS, exception_item=item)

        if interval.outcome is MeteringOutcome.INCOMPLETE:
            item = self.raise_exception(
                session,
                ExceptionKind.CALL_MISSING_TERMINAL_EVENT,
                f"call:{attempt.id}",
                "a destination leg answered and never reported ending; the "
                "hold is not released while the call may still be connected",
            )
            self.schedule(
                session,
                attempt,
                DeadlineKind.MISSING_TERMINAL_EVENT,
                self.clock() + timedelta(seconds=self.missing_terminal_seconds),
            )
            return SettlementResult(SettlementStatus.DEFERRED, exception_item=item)

        reservation = self._reservation(session, attempt)
        seconds = interval.seconds or 0
        metered = charge_for(
            seconds=seconds,
            per_minute_amount=attempt.rate_per_minute_amount,
            setup_amount=attempt.rate_setup_amount,
            minimum_seconds=attempt.rate_minimum_seconds,
            increment_seconds=attempt.rate_increment_seconds,
            currency=attempt.currency,
        )
        window = self._window(legs)

        if metered.total <= 0:
            charge = self._write_charge(
                session,
                attempt,
                metered_seconds=0,
                setup=round_money(Decimal(0), attempt.currency),
                usage=round_money(Decimal(0), attempt.currency),
                basis=ChargeBasis.PROVIDER_EVENTS,
                state=ChargeState.PROVISIONAL,
                window=window,
                settled_at=self.clock(),
            )
            self.schedule(
                session,
                attempt,
                DeadlineKind.SUPPLIER_COST_WAIT,
                self.clock() + timedelta(seconds=self.supplier_cost_wait_seconds),
            )
            return SettlementResult(SettlementStatus.NOTHING_TO_CHARGE, charge)

        debit = self._funding_account(session, attempt)
        credit = revenue_account or self.ledger.account(
            session, attempt.currency, AccountKind.REVENUE
        )
        self._assert_currencies(attempt, reservation, debit, credit)

        outstanding = (
            reservation.amount
            - reservation.settled_amount
            - reservation.released_amount
        )
        payable = metered.total
        shortfall: Decimal | None = None
        if payable > outstanding:
            # The authorized maximum binds us, not just the customer. Charging
            # past it would spend money nobody agreed to release.
            shortfall = round_money(payable - outstanding, attempt.currency)
            payable = outstanding

        setup = metered.setup_amount
        usage = metered.usage_amount
        if shortfall is not None:
            # Keep the stored breakdown equal to what actually posted: the
            # database constraint requires it, and a receipt whose parts do not
            # add up to its total cannot be explained to the person who paid it.
            usage = round_money(payable - setup, attempt.currency)
            if usage < 0:
                setup, usage = payable, round_money(Decimal(0), attempt.currency)

        _, entry = self.ledger.settle(
            session,
            reservation,
            payable,
            f"call:{attempt.id}:settlement",
            credit,
            occurred_at=window[1],
        )
        charge = self._write_charge(
            session,
            attempt,
            metered_seconds=metered.billable_seconds,
            setup=setup,
            usage=usage,
            basis=ChargeBasis.PROVIDER_EVENTS,
            # Provisional until the supplier's own record either confirms it or
            # corrects it. The customer sees the amount now; the books stay open.
            state=ChargeState.PROVISIONAL,
            window=window,
            journal_entry_id=entry.id,
            settled_at=self.clock(),
        )
        # Keep the unused authorization held while the supplier can still
        # correct this provisional amount. Releasing it here would let another
        # call spend those funds and make a higher CDR correction overdraw the
        # payer or consume money reserved for somebody else.
        self.schedule(
            session,
            attempt,
            DeadlineKind.SUPPLIER_COST_WAIT,
            self.clock() + timedelta(seconds=self.supplier_cost_wait_seconds),
        )

        shortfall_item: ExceptionItem | None = None
        if shortfall is not None:
            shortfall_item = self.raise_exception(
                session,
                ExceptionKind.CALL_SETTLEMENT_SHORTFALL,
                f"call:{attempt.id}",
                f"metered {metered.total} {attempt.currency} against an "
                f"authorized hold of {outstanding} {attempt.currency}; the "
                f"difference of {shortfall} is unrecovered exposure",
            )
        return SettlementResult(
            SettlementStatus.SETTLED,
            charge,
            shortfall=shortfall,
            exception_item=shortfall_item,
        )

    def correct(
        self,
        session: Session,
        charge: CallCharge,
        *,
        billable_seconds: int,
        setup_amount: Decimal,
        usage_amount: Decimal,
        basis: ChargeBasis,
        detail: str,
        revenue_account: LedgerAccount | None = None,
    ) -> CallCharge:
        """Replace a charge with a corrected one, moving only the difference.

        Chunk 16's rule, applied to calls: the original entry is never touched.
        Reversing and re-posting would put two transactions in the books where
        one adjustment happened, and a customer reading their history would see
        a refund and a charge for a call that was simply mispriced by four
        seconds.
        """
        self._lock(session, f"call-settlement:{charge.attempt_id}")
        current = session.exec(
            select(CallCharge)
            .where(CallCharge.id == charge.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if current is None:  # pragma: no cover - caller holds the row
            raise ChargingError("charge_not_found")
        if current.state is ChargeState.SUPERSEDED:
            raise ChargingError(
                "charge_already_superseded",
                "correct the charge that is live, not one it replaced",
            )
        attempt = session.get(CallAttempt, current.attempt_id)
        if attempt is None:  # pragma: no cover - FK guarantees this
            raise ChargingError("attempt_not_found")

        setup = round_money(setup_amount, current.currency)
        usage = round_money(usage_amount, current.currency)
        requested_total = round_money(setup + usage, current.currency)
        if requested_total < 0:
            raise ChargingError("negative_correction")

        # A late supplier record cannot enlarge the customer's authorization.
        # The excess is our exposure and goes to the queue, just as it does in
        # initial settlement.
        total = min(requested_total, attempt.max_charge_amount)
        total = round_money(total, current.currency)
        if total != requested_total:
            usage = round_money(total - setup, current.currency)
            if usage < 0:
                setup, usage = total, round_money(Decimal(0), current.currency)
            self.raise_exception(
                session,
                ExceptionKind.CALL_SETTLEMENT_SHORTFALL,
                f"call:{attempt.id}",
                f"corrected charge of {requested_total} {current.currency} "
                f"exceeds the authorized maximum of {total} "
                f"{current.currency}; the difference is unrecovered exposure",
            )
        difference = round_money(total - current.charged_amount, current.currency)
        reservation = self._reservation(session, attempt)
        outstanding = round_money(
            reservation.amount
            - reservation.settled_amount
            - reservation.released_amount,
            current.currency,
        )
        if difference > outstanding:
            unrecovered = round_money(difference - outstanding, current.currency)
            total = round_money(
                current.charged_amount + outstanding, current.currency
            )
            difference = outstanding
            setup = min(setup, total)
            usage = round_money(total - setup, current.currency)
            self.raise_exception(
                session,
                ExceptionKind.CALL_SETTLEMENT_SHORTFALL,
                f"call:{attempt.id}",
                f"a late correction could recover only {difference} "
                f"{current.currency}; {unrecovered} {current.currency} was no "
                "longer covered by the authorized hold",
            )

        current.state = ChargeState.SUPERSEDED
        session.add(current)
        session.flush()

        replacement = self._write_charge(
            session,
            attempt,
            metered_seconds=billable_seconds,
            setup=setup,
            usage=usage,
            basis=basis,
            state=ChargeState.FINAL,
            window=(current.metered_from, current.metered_to),
            corrects_id=current.id,
            settled_at=self.clock(),
        )

        if difference > 0:
            debit = self._funding_account(session, attempt)
            credit = revenue_account or self.ledger.account(
                session, current.currency, AccountKind.REVENUE
            )
            self._assert_account_currencies(current.currency, debit, credit)
            _, entry = self.ledger.settle(
                session,
                reservation,
                difference,
                f"call:{attempt.id}:correction:{replacement.id}",
                credit,
                occurred_at=current.metered_to,
            )
            replacement.journal_entry_id = entry.id
            session.add(replacement)
            session.flush()
        elif difference < 0:
            debit = self._funding_account(session, attempt)
            credit = revenue_account or self.ledger.account(
                session, current.currency, AccountKind.REVENUE
            )
            self._assert_account_currencies(current.currency, debit, credit)
            entry = self.ledger.post(
                session,
                f"call:{attempt.id}:correction:{replacement.id}",
                [
                    Posting(credit, Direction.DEBIT, abs(difference)),
                    Posting(debit, Direction.CREDIT, abs(difference)),
                ],
                occurred_at=current.metered_to,
                reference=f"correction of call charge {current.id}",
            )
            replacement.journal_entry_id = entry.id
            session.add(replacement)
            session.flush()

        self._release_everything(session, self._reservation(session, attempt))

        if basis is ChargeBasis.MANUAL_CORRECTION:
            # A human decided this amount. The queue keeps the reason beside the
            # money, so the correction can be answered later without asking who
            # remembers why.
            self.raise_exception(
                session,
                ExceptionKind.SETTLEMENT_MISMATCH,
                f"call-correction:{replacement.id}",
                detail[:1000],
            )
        return replacement

    # --- supplier cost ----------------------------------------------------

    def record_supplier_cost(
        self,
        session: Session,
        *,
        provider: str,
        provider_reference: str,
        component: SupplierCostComponent,
        currency: str,
        amount: Decimal,
        attempt: CallAttempt | None = None,
        leg: CallLeg | None = None,
        billable_seconds: int | None = None,
        occurred_at: datetime | None = None,
    ) -> CallSupplierCost:
        """Record what the supplier says one component cost us. Once.

        A redelivered CDR is the ordinary case, not the exception, so the second
        delivery returns the first row rather than doubling our recorded cost.
        An observation we cannot attach to an attempt is kept and queued: a
        charge we cannot explain is exactly the one worth looking at.
        """
        self._lock(
            session,
            f"call-supplier-cost:{provider}:{provider_reference}:{component.value}",
        )
        existing = session.exec(
            select(CallSupplierCost).where(
                CallSupplierCost.provider == provider,
                CallSupplierCost.provider_reference == provider_reference,
                CallSupplierCost.component == component,
            )
        ).first()
        if existing is not None:
            expected_attempt_id = (
                attempt.id
                if attempt is not None
                else (leg.attempt_id if leg is not None else None)
            )
            if (
                existing.attempt_id != expected_attempt_id
                or existing.leg_id != (leg.id if leg is not None else None)
                or existing.currency != currency
                or existing.amount != round_money(amount, currency)
                or existing.billable_seconds != billable_seconds
            ):
                raise ChargingError(
                    "supplier_cost_idempotency_conflict",
                    "the supplier reference was replayed with different facts",
                )
            return existing

        if leg is not None:
            if attempt is not None and leg.attempt_id != attempt.id:
                raise ChargingError("supplier_cost_attempt_mismatch")
            if attempt is None:
                attempt = session.get(CallAttempt, leg.attempt_id)

        record = CallSupplierCost(
            attempt_id=attempt.id if attempt is not None else None,
            leg_id=leg.id if leg is not None else None,
            provider=provider,
            provider_reference=provider_reference,
            component=component,
            currency=currency,
            amount=round_money(amount, currency),
            billable_seconds=billable_seconds,
            occurred_at=occurred_at,
            recorded_at=self.clock(),
        )
        session.add(record)
        session.flush()

        if attempt is None:
            self.raise_exception(
                session,
                ExceptionKind.CALL_SUPPLIER_COST_UNMATCHED,
                f"supplier-cost:{provider}:{provider_reference}",
                f"{amount} {currency} billed for {component.value} with no "
                "call attempt we can attach it to",
            )
        return record

    def supplier_cost_total(
        self, session: Session, attempt: CallAttempt, currency: str
    ) -> Decimal:
        """What this attempt has cost us so far, in one supplier currency.

        Deliberately takes the currency rather than assuming the customer's:
        the supplier bills in its own, and adding the two would be the
        cross-currency arithmetic `app/money.py` exists to prevent.
        """
        total = session.exec(
            select(func.coalesce(func.sum(CallSupplierCost.amount), 0)).where(
                CallSupplierCost.attempt_id == attempt.id,
                CallSupplierCost.currency == currency,
                col(CallSupplierCost.superseded_by_id).is_(None),
            )
        ).first()
        return round_money(Decimal(total or 0), currency)

    # --- durable deadlines ------------------------------------------------

    def schedule(
        self,
        session: Session,
        attempt: CallAttempt,
        kind: DeadlineKind,
        due_at: datetime,
    ) -> CallDeadline:
        """Write down that something must happen later. One row per attempt/kind.

        A restarted worker re-registering its renewals finds the existing row
        instead of creating a second one that fires twice.
        """
        self._lock(session, f"call-deadline:{attempt.id}:{kind.value}")
        existing = session.exec(
            select(CallDeadline).where(
                CallDeadline.attempt_id == attempt.id,
                CallDeadline.kind == kind,
                col(CallDeadline.state).in_(
                    [DeadlineState.PENDING, DeadlineState.CLAIMED]
                ),
            )
        ).first()
        if existing is not None:
            return existing
        deadline = CallDeadline(
            attempt_id=attempt.id,
            kind=kind,
            state=DeadlineState.PENDING,
            due_at=due_at,
            created_at=self.clock(),
        )
        session.add(deadline)
        session.flush()
        return deadline

    def claim_due(
        self, session: Session, *, now: datetime | None = None, limit: int = 10
    ) -> Sequence[CallDeadline]:
        """Take due work, skipping what another worker already holds.

        Workers commit a claim before doing provider work. A claim older than
        `claim_timeout_seconds` is therefore eligible again: the database lock
        prevents concurrent claims, while the lease recovers a worker that died
        after committing its claim.
        """
        moment = now or self.clock()
        stale_before = moment - timedelta(seconds=self.claim_timeout_seconds)
        rows = session.exec(
            select(CallDeadline)
            .where(
                col(CallDeadline.due_at) <= moment,
                or_(
                    col(CallDeadline.state) == DeadlineState.PENDING,
                    (
                        (col(CallDeadline.state) == DeadlineState.CLAIMED)
                        & (col(CallDeadline.claimed_at) <= stale_before)
                    ),
                ),
            )
            .order_by(col(CallDeadline.due_at))
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            row.state = DeadlineState.CLAIMED
            row.claimed_at = moment
            row.attempts = row.attempts + 1
            session.add(row)
        session.flush()
        return rows

    def renew(self, session: Session, attempt: CallAttempt) -> EnforcementOutcome:
        """Recheck policy and extend the hold lease for one worker interval."""
        outcome = self.enforce(session, attempt)
        if outcome.decision is EnforcementDecision.STOP:
            return outcome
        reservation = session.exec(
            select(Reservation)
            .where(Reservation.id == attempt.reservation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        new_expiry = self.clock() + timedelta(
            seconds=self.renewal_interval_seconds * 2
        )
        if reservation.expires_at is None or reservation.expires_at < new_expiry:
            reservation.expires_at = new_expiry
            session.add(reservation)
            session.flush()
        return outcome

    def finalize_provisional(
        self, session: Session, attempt: CallAttempt
    ) -> CallCharge | None:
        """Close an event-derived charge and release its remaining hold."""
        self._lock(session, f"call-settlement:{attempt.id}")
        charge = self.charge_for_attempt(session, attempt)
        if charge is not None and charge.state is ChargeState.PROVISIONAL:
            charge.state = ChargeState.FINAL
            session.add(charge)
            self._release_everything(session, self._reservation(session, attempt))
            session.flush()
        return charge

    def complete(
        self, session: Session, deadline: CallDeadline, *, detail: str | None = None
    ) -> CallDeadline:
        deadline.state = DeadlineState.DONE
        deadline.resolved_at = self.clock()
        deadline.last_detail = detail[:500] if detail else deadline.last_detail
        session.add(deadline)
        session.flush()
        return deadline

    def release_claim(
        self, session: Session, deadline: CallDeadline, *, detail: str | None = None
    ) -> CallDeadline:
        """Put unfinished work back. A crash between claim and completion.

        The row returns to `PENDING` with its attempt count intact, so a
        deadline that keeps failing is visible as a number rather than as
        silence.
        """
        deadline.state = DeadlineState.PENDING
        deadline.claimed_at = None
        deadline.last_detail = detail[:500] if detail else deadline.last_detail
        session.add(deadline)
        session.flush()
        return deadline

    def abandon(
        self, session: Session, deadline: CallDeadline, detail: str
    ) -> CallDeadline:
        deadline.state = DeadlineState.ABANDONED
        deadline.resolved_at = self.clock()
        deadline.last_detail = detail[:500]
        session.add(deadline)
        session.flush()
        return deadline

    # --- enforcement ------------------------------------------------------

    def enforce(
        self,
        session: Session,
        attempt: CallAttempt,
        *,
        carrier_bounded: bool = False,
    ) -> EnforcementOutcome:
        """May this call keep running?

        Asked again at every renewal deadline, because the answers change while
        a call is up: a colleague can spend the organization's remaining budget,
        and a second device can hold the same funds.
        """
        if attempt.state in TERMINAL_ATTEMPT_STATES:
            return EnforcementOutcome(
                EnforcementDecision.STOP, "the attempt has already ended"
            )
        reservation = self._reservation(session, attempt)
        if reservation.state is not ReservationState.HELD:
            return EnforcementOutcome(
                EnforcementDecision.STOP,
                "the hold that funds this call is no longer open",
            )
        if (
            reservation.expires_at is not None
            and self.clock() >= reservation.expires_at
        ):
            return EnforcementOutcome(
                EnforcementDecision.STOP, "the reservation lease expired"
            )
        if self.clock() >= attempt.expires_at and attempt.grant_consumed_at is None:
            return EnforcementOutcome(
                EnforcementDecision.STOP, "the authorization expired unused"
            )
        if attempt.payer_kind is PayerKind.ORGANIZATION:
            headroom = self.organization_call_headroom(
                session,
                attempt.organization_id,
                attempt.currency,
                self._period_start(),
            )
            if headroom is not None and headroom < 0:
                return EnforcementOutcome(
                    EnforcementDecision.STOP,
                    "this organization is past its recorded spending cap",
                )
        if not carrier_bounded:
            # The amendment: without independently bounded carrier exposure there
            # is no unrestricted common pool. Internet calling keeps running on
            # its own hold; what stays disabled is treating the two as one.
            return EnforcementOutcome(
                EnforcementDecision.CONTINUE,
                "funded by this call's own hold; carrier and internet spend "
                "are not pooled while carrier exposure is unbounded",
            )
        return EnforcementOutcome(
            EnforcementDecision.CONTINUE, "funds and budget still permit this call"
        )

    def organization_call_headroom(
        self,
        session: Session,
        organization_id: UUID | None,
        currency: str,
        since: datetime,
    ) -> Decimal | None:
        """What an organization may still spend on calls this period.

        Composed rather than copied: chunk 17 answers "cap minus top-ups", and
        this subtracts call spend from that. Rewriting chunk 17's query to count
        calls would change what an accepted chunk refuses, which is not this
        chunk's decision to make.

        `None` means nobody has recorded a policy and therefore no
        organization-specific cap is applied here.
        """
        if organization_id is None or self.controls is None:
            return None
        headroom = self.controls.budget_headroom(
            session, organization_id, currency, since
        )
        if headroom is None:
            return None
        spent = session.exec(
            select(func.coalesce(func.sum(CallCharge.charged_amount), 0))
            .join(CallAttempt, col(CallCharge.attempt_id) == col(CallAttempt.id))
            .where(
                CallAttempt.organization_id == organization_id,
                CallCharge.currency == currency,
                CallCharge.state != ChargeState.SUPERSEDED,
                col(CallCharge.created_at) >= since,
            )
        ).first()
        committed = session.exec(
            select(func.coalesce(func.sum(Reservation.amount), 0))
            .join(
                CallAttempt, col(CallAttempt.reservation_id) == col(Reservation.id)
            )
            .where(
                CallAttempt.organization_id == organization_id,
                Reservation.currency == currency,
                Reservation.state == ReservationState.HELD,
                col(CallAttempt.created_at) >= since,
            )
        ).first()
        return round_money(
            headroom - Decimal(spent or 0) - Decimal(committed or 0), currency
        )

    # --- queue ------------------------------------------------------------

    def raise_exception(
        self,
        session: Session,
        kind: ExceptionKind,
        subject_reference: str,
        detail: str,
    ) -> ExceptionItem:
        """Chunk 14's queue, not a second one.

        An operations team watching two lists watches neither.
        """
        subject_reference = subject_reference[:200]
        self._lock(session, f"exception:{kind.value}:{subject_reference}")
        existing = session.exec(
            select(ExceptionItem).where(
                ExceptionItem.kind == kind,
                ExceptionItem.subject_reference == subject_reference,
            )
        ).first()
        if existing is not None:
            return existing
        item = ExceptionItem(
            kind=kind,
            subject_reference=subject_reference,
            detail=detail[:1000],
            raised_at=self.clock(),
        )
        session.add(item)
        session.flush()
        return item

    # --- internals --------------------------------------------------------

    def charge_for_attempt(
        self, session: Session, attempt: CallAttempt
    ) -> CallCharge | None:
        return self._live_charge(session, attempt)

    def _live_charge(
        self, session: Session, attempt: CallAttempt
    ) -> CallCharge | None:
        return session.exec(
            select(CallCharge).where(
                CallCharge.attempt_id == attempt.id,
                CallCharge.state != ChargeState.SUPERSEDED,
            ).execution_options(populate_existing=True)
        ).first()

    def _write_charge(
        self,
        session: Session,
        attempt: CallAttempt,
        *,
        metered_seconds: int,
        setup: Decimal,
        usage: Decimal,
        basis: ChargeBasis,
        state: ChargeState,
        window: tuple[datetime | None, datetime | None],
        corrects_id: UUID | None = None,
        journal_entry_id: UUID | None = None,
        settled_at: datetime | None = None,
    ) -> CallCharge:
        charge = CallCharge(
            attempt_id=attempt.id,
            state=state,
            basis=basis,
            corrects_id=corrects_id,
            currency=attempt.currency,
            billable_seconds=metered_seconds,
            setup_amount=setup,
            usage_amount=usage,
            charged_amount=round_money(setup + usage, attempt.currency),
            metered_from=window[0],
            metered_to=window[1],
            journal_entry_id=journal_entry_id,
            settled_at=settled_at,
            created_at=self.clock(),
        )
        session.add(charge)
        session.flush()
        return charge

    def _release_everything(
        self, session: Session, reservation: Reservation
    ) -> None:
        """Give back whatever the settlement did not spend.

        Called only once liability is final. Everywhere liability is *not*
        final, the code above returns before reaching here — that omission is
        the feature.
        """
        current = session.get(Reservation, reservation.id)
        if current is None:  # pragma: no cover - FK guarantees this
            return
        outstanding = (
            current.amount - current.settled_amount - current.released_amount
        )
        if outstanding > 0:
            self.ledger.release(session, current, outstanding)

    def _legs(self, session: Session, attempt: CallAttempt) -> Sequence[CallLeg]:
        return session.exec(
            select(CallLeg).where(CallLeg.attempt_id == attempt.id)
        ).all()

    def _window(
        self, legs: Sequence[CallLeg]
    ) -> tuple[datetime | None, datetime | None]:
        for leg in legs:
            if (
                leg.role is LegRole.DESTINATION
                and leg.answered_at is not None
                and leg.ended_at is not None
            ):
                return leg.answered_at, leg.ended_at
        return None, None

    def _reservation(self, session: Session, attempt: CallAttempt) -> Reservation:
        reservation = session.get(Reservation, attempt.reservation_id)
        if reservation is None:  # pragma: no cover - FK guarantees this
            raise ChargingError("reservation_not_found")
        return reservation

    def _funding_account(
        self, session: Session, attempt: CallAttempt
    ) -> LedgerAccount:
        if attempt.payer_kind is PayerKind.ORGANIZATION:
            if attempt.organization_id is None:  # pragma: no cover - constraint
                raise ChargingError("payer_not_resolvable")
            return self.ledger.account(
                session,
                attempt.currency,
                AccountKind.SERVICE_CREDIT,
                OwnerKind.ORGANIZATION,
                owner_organization_id=attempt.organization_id,
            )
        return self.ledger.account(
            session,
            attempt.currency,
            AccountKind.SERVICE_CREDIT,
            OwnerKind.USER,
            owner_user_id=attempt.owner_user_id,
        )

    def _assert_currencies(
        self,
        attempt: CallAttempt,
        reservation: Reservation,
        debit: LedgerAccount,
        credit: LedgerAccount,
    ) -> None:
        if reservation.currency != attempt.currency:
            raise ChargingError(
                "currency_mismatch",
                "the hold and the attempt disagree about the currency; "
                "settling would pick one of them silently",
            )
        self._assert_account_currencies(attempt.currency, debit, credit)

    def _assert_account_currencies(
        self, currency: str, debit: LedgerAccount, credit: LedgerAccount
    ) -> None:
        if debit.currency != currency or credit.currency != currency:
            raise ChargingError(
                "currency_mismatch",
                f"a {currency} call cannot settle through "
                f"{debit.currency}/{credit.currency} accounts",
            )
        if (
            debit.kind is not AccountKind.SERVICE_CREDIT
            or credit.kind is not AccountKind.REVENUE
            or credit.owner_kind is not OwnerKind.SYSTEM
        ):
            raise ChargingError(
                "account_mismatch",
                "call charges move from the payer's service credit to revenue",
            )

    def _period_start(self) -> datetime:
        return self.clock() - timedelta(days=30)

    @staticmethod
    def _lock(session: Session, key: str) -> None:
        """Serialize one logical settlement for this transaction.

        The unique index stays the final guard; this makes two concurrent
        settlements of the same call converge on one row instead of one of them
        failing after both found none.
        """
        if session.get_bind().dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
                .bindparams(key=key)
            )
