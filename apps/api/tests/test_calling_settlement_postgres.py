"""Settlement on real PostgreSQL — US-46, chunk V03.

Money, idempotency and concurrency are strict-TDD categories in `AGENTS.md` and
all three are here at once. None of it is testable on SQLite: one live charge per
attempt is a partial unique index, two devices settling the same call race
through `SELECT … FOR UPDATE` inside the ledger, and the deadline queue depends
on `FOR UPDATE SKIP LOCKED`. A passing SQLite run would prove none of them exist.

The expected amounts below are computed **by hand in the test**, not by calling
the code under test. `AGENTS.md` forbids tests that mirror the implementation,
and the assignment asks specifically for "an independent expected-cost ledger
fixture, not just implementation-mirroring assertions".
"""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from app import model_registry  # noqa: F401
from app.auth.models import (
    AdminRole,
    AdminUser,
    Locale,
    Organization,
    OrganizationType,
    Platform,
    User,
)
from app.calling.charging import (
    CallChargingService,
    ChargingError,
    EnforcementDecision,
    SettlementStatus,
)
from app.calling.contract import LegRole, LegState
from app.calling.models import (
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
    SupplierCostComponent,
)
from app.calling.service import CallAuthorizationService
from app.catalog.market import PublicationStatus
from app.catalog.models import Product, ProductKind
from app.catalog.tariffs import DestinationKind, OriginKind, Tariff, TariffRate
from app.ledger.models import (
    AccountKind,
    Direction,
    JournalEntry,
    JournalLine,
    OwnerKind,
    Reservation,
    ReservationState,
)
from app.ledger.service import LedgerService, Posting
from app.operations.models import OperatorActionKind
from app.operations.service import OperationsService
from app.refunds.models import ExceptionItem, ExceptionKind
from app.worker import _resolve_deadline

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="settlement's guarantees are database guarantees",
)

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
TABLES = (
    "operator_actions, call_deadlines, call_supplier_costs, call_charges, call_events, "
    "call_operations, call_legs, call_attempts, calling_client_credentials, "
    "exception_items, journal_lines, journal_entries, ledger_reservations, "
    "ledger_accounts, tariff_rates, tariffs, products, organization_members, "
    "organizations, admin_users, users"
)

#: NGN 30.00 per minute, 60-second increments, no minimum and no setup fee.
#: Invented for the test; B2 is open and no Nigeria rate deck exists.
PER_MINUTE = Decimal("30.0000000000")


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: float) -> None:
        self.value += timedelta(**kwargs)


@pytest.fixture
def engine():
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        session.exec(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        session.commit()
        yield session
        session.rollback()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def ledger(clock):
    return LedgerService(clock=clock)


@pytest.fixture
def authorization(ledger, clock):
    return CallAuthorizationService(
        ledger, clock=clock, supported_countries=frozenset({"NG"}), route_enabled=True
    )


@pytest.fixture
def charging(ledger, clock):
    return CallChargingService(ledger, clock=clock)


def _user(session: Session, label: str = "caller") -> User:
    user = User(
        phone_number=f"+23480{uuid4().int % 10**8:08d}",
        first_name=label,
        platform=Platform.ANDROID,
    )
    session.add(user)
    session.flush()
    return user


def _tariff(
    session: Session,
    clock: Clock,
    *,
    per_minute: Decimal = PER_MINUTE,
    setup: Decimal = Decimal("0.000000"),
    minimum_seconds: int = 0,
    increment_seconds: int = 60,
) -> Tariff:
    product = Product(
        sku=f"voice-{uuid4().hex[:8]}", name="Internet calling", kind=ProductKind.VOICE
    )
    session.add(product)
    session.flush()
    tariff = Tariff(
        product_id=product.id,
        currency="NGN",
        version=1,
        status=PublicationStatus.PUBLISHED,
        effective_from=clock() - timedelta(days=1),
        evidence_reference="test fixture — not a rate claim (B2 open)",
        verified_at=clock() - timedelta(days=1),
    )
    session.add(tariff)
    session.flush()
    session.add(
        TariffRate(
            tariff_id=tariff.id,
            origin_kind=OriginKind.INTERNET,
            origin_country=None,
            destination_country="NG",
            destination_kind=DestinationKind.MOBILE,
            per_minute_amount=per_minute,
            setup_amount=setup,
            minimum_seconds=minimum_seconds,
            increment_seconds=increment_seconds,
        )
    )
    session.flush()
    return tariff


def _fund(session, ledger, user, amount="10000.00"):
    credit = ledger.account(
        session,
        "NGN",
        AccountKind.SERVICE_CREDIT,
        OwnerKind.USER,
        owner_user_id=user.id,
    )
    clearing = ledger.account(session, "NGN", AccountKind.SETTLEMENT_CLEARING)
    ledger.post(
        session,
        f"funding:{uuid4()}",
        [
            Posting(clearing, Direction.DEBIT, Decimal(amount)),
            Posting(credit, Direction.CREDIT, Decimal(amount)),
        ],
    )
    session.flush()
    return credit


def _authorize(authorization, session, user, **overrides):
    destination = overrides.pop("destination", "+2348031234567")
    kwargs = dict(
        idempotency_key=f"key-{uuid4()}",
        currency="NGN",
        identity_e164="+2347000000001",
        requested_seconds=600,
    )
    kwargs.update(overrides)
    return authorization.authorize(session, user, destination, **kwargs)


def _legs(
    session: Session,
    attempt: CallAttempt,
    *,
    answered: int | None = None,
    ended: int | None = None,
    role: LegRole = LegRole.DESTINATION,
    state: LegState = LegState.ENDED,
    client_ended: int | None = None,
) -> CallLeg:
    """Write the provider's account of the call, as converged legs."""
    if client_ended is not None:
        session.add(
            CallLeg(
                attempt_id=attempt.id,
                role=LegRole.CLIENT,
                provider="telnyx",
                provider_call_control_id=f"client-{uuid4().hex[:12]}",
                state=LegState.ENDED,
                started_at=NOW,
                answered_at=NOW,
                ended_at=NOW + timedelta(seconds=client_ended),
                created_at=NOW,
            )
        )
    leg = CallLeg(
        attempt_id=attempt.id,
        role=role,
        provider="telnyx",
        provider_call_control_id=f"dest-{uuid4().hex[:12]}",
        state=state,
        started_at=NOW,
        answered_at=NOW + timedelta(seconds=answered) if answered is not None else None,
        ended_at=NOW + timedelta(seconds=ended) if ended is not None else None,
        created_at=NOW,
    )
    session.add(leg)
    session.flush()
    return leg


def _finish(session, attempt, state=AttemptState.COMPLETED):
    attempt.state = state
    attempt.ended_at = NOW + timedelta(minutes=5)
    session.add(attempt)
    session.flush()
    return attempt


def _ready_call(session, authorization, charging, ledger, clock, **kwargs):
    """An authorized, finished, answered call ready to settle."""
    user = _user(session)
    credit = _fund(session, ledger, user, kwargs.pop("funding", "10000.00"))
    _tariff(session, clock, **kwargs.pop("tariff", {}))
    attempt = _authorize(authorization, session, user, **kwargs.pop("authorize", {}))
    _legs(
        session,
        attempt,
        answered=kwargs.pop("answered", 10),
        ended=kwargs.pop("ended", 130),
        client_ended=kwargs.pop("client_ended", 200),
    )
    _finish(session, attempt)
    return user, credit, attempt


class TestSettlementMovesTheRightMoney:
    def test_an_answered_call_charges_metered_minutes_and_retains_the_remainder(
        self, session, authorization, charging, ledger, clock
    ):
        """120 seconds at NGN 30/min is NGN 60.00. Computed here, by hand."""
        user, credit, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        # 600s authorized at 30/min = NGN 300 held.
        assert ledger.available(session, credit) == Decimal("9700.00")

        result = charging.settle(session, attempt)

        assert result.status is SettlementStatus.SETTLED
        assert result.charge is not None
        assert result.charge.billable_seconds == 120
        assert result.charge.charged_amount == Decimal("60.00")
        assert result.shortfall is None
        # NGN 60 is spent. The remaining NGN 240 stays held until the supplier
        # reconciliation window closes, so a higher CDR cannot overdraw funds
        # that another call has since reserved.
        assert ledger.balance(session, credit) == Decimal("9940.00")
        assert ledger.available(session, credit) == Decimal("9700.00")
        reservation = session.get(Reservation, attempt.reservation_id)
        assert reservation.settled_amount == Decimal("60.00")
        assert reservation.released_amount == Decimal("0.00")
        assert reservation.state is ReservationState.HELD

    def test_the_entry_posted_is_the_charge_recorded(
        self, session, authorization, charging, ledger, clock
    ):
        _, credit, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        charge = charging.settle(session, attempt).charge

        entry = session.get(JournalEntry, charge.journal_entry_id)
        assert entry is not None
        lines = session.exec(
            select(JournalLine).where(JournalLine.entry_id == entry.id)
        ).all()
        debited = [line for line in lines if line.direction is Direction.DEBIT]
        assert len(debited) == 1
        assert debited[0].account_id == credit.id
        assert debited[0].amount == charge.charged_amount

    def test_the_client_legs_duration_is_not_what_is_charged(
        self, session, authorization, charging, ledger, clock
    ):
        """The client was connected for 200s; the destination answered 120s.

        Charging the client leg, or the sum, is the defect the amendment names.
        """
        _, _, attempt = _ready_call(
            session,
            authorization,
            charging,
            ledger,
            clock,
            answered=10,
            ended=130,
            client_ended=200,
        )
        charge = charging.settle(session, attempt).charge
        assert charge.billable_seconds == 120
        assert charge.charged_amount == Decimal("60.00")
        assert charge.metered_from == NOW + timedelta(seconds=10)
        assert charge.metered_to == NOW + timedelta(seconds=130)

    def test_a_call_nobody_answered_stays_provisional_until_reconciliation(
        self, session, authorization, charging, ledger, clock
    ):
        user = _user(session)
        credit = _fund(session, ledger, user)
        _tariff(session, clock)
        attempt = _authorize(authorization, session, user)
        _legs(session, attempt, ended=45, client_ended=45)
        _finish(session, attempt, AttemptState.FAILED)

        result = charging.settle(session, attempt)

        assert result.status is SettlementStatus.NOTHING_TO_CHARGE
        assert result.charge.charged_amount == Decimal("0.00")
        assert result.charge.journal_entry_id is None
        assert result.charge.state is ChargeState.PROVISIONAL
        assert ledger.available(session, credit) == Decimal("9700.00")
        reservation = session.get(Reservation, attempt.reservation_id)
        assert reservation.state is ReservationState.HELD
        assert reservation.settled_amount == Decimal("0")

    def test_a_rate_change_mid_call_does_not_reprice_the_call(
        self, session, authorization, charging, ledger, clock
    ):
        """The attempt's frozen snapshot is the only rate settlement can see."""
        user = _user(session)
        _fund(session, ledger, user)
        tariff = _tariff(session, clock)
        attempt = _authorize(authorization, session, user)
        _legs(session, attempt, answered=10, ended=130)
        _finish(session, attempt)

        rate = session.exec(
            select(TariffRate).where(TariffRate.tariff_id == tariff.id)
        ).one()
        rate.per_minute_amount = Decimal("300.0000000000")
        session.add(rate)
        session.flush()

        charge = charging.settle(session, attempt).charge
        assert charge.charged_amount == Decimal("60.00")

    def test_a_partially_connected_call_pays_for_what_connected(
        self, session, authorization, charging, ledger, clock
    ):
        """Answered and dropped after 9 seconds: one 60-second increment."""
        _, _, attempt = _ready_call(
            session, authorization, charging, ledger, clock, answered=10, ended=19
        )
        charge = charging.settle(session, attempt).charge
        assert charge.billable_seconds == 60
        assert charge.charged_amount == Decimal("30.00")


class TestSettlementHappensOnce:
    def test_settling_twice_posts_once(
        self, session, authorization, charging, ledger, clock
    ):
        _, credit, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        first = charging.settle(session, attempt)
        second = charging.settle(session, attempt)

        assert first.charge.id == second.charge.id
        assert ledger.balance(session, credit) == Decimal("9940.00")
        charges = session.exec(
            select(CallCharge).where(CallCharge.attempt_id == attempt.id)
        ).all()
        assert len(charges) == 1

    def test_two_concurrent_settlements_produce_one_charge(
        self, engine, authorization, charging, ledger, clock, session
    ):
        """Two workers, one call. The second finds the charge, not a race."""
        _, credit, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        session.commit()
        attempt_id = attempt.id
        credit_id = credit.id
        barrier = Barrier(2)

        def settle_once():
            with Session(engine) as worker_session:
                local = CallChargingService(LedgerService(clock=clock), clock=clock)
                subject = worker_session.get(CallAttempt, attempt_id)
                barrier.wait(timeout=10)
                outcome = local.settle(worker_session, subject)
                worker_session.commit()
                return outcome.charge.id

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(settle_once) for _ in range(2)]
            ids = {future.result(timeout=30) for future in results}

        assert len(ids) == 1
        with Session(engine) as check:
            charges = check.exec(
                select(CallCharge).where(CallCharge.attempt_id == attempt_id)
            ).all()
            assert len(charges) == 1
            account = check.get(type(credit), credit_id)
            assert LedgerService(clock=clock).balance(check, account) == Decimal(
                "9940.00"
            )

    def test_an_unfinished_call_cannot_be_settled(
        self, session, authorization, charging, ledger, clock
    ):
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)
        attempt = _authorize(authorization, session, user)
        _legs(session, attempt, answered=10, ended=130)

        with pytest.raises(ChargingError) as excinfo:
            charging.settle(session, attempt)
        assert excinfo.value.code == "call_not_finished"


class TestUnknownLiabilityIsNotReleased:
    def test_an_unknown_destination_command_without_a_leg_is_not_free(
        self, session, authorization, charging, ledger, clock
    ):
        user = _user(session)
        credit = _fund(session, ledger, user)
        _tariff(session, clock)
        attempt = _authorize(authorization, session, user)
        _finish(session, attempt, AttemptState.UNKNOWN)

        result = charging.settle(session, attempt)

        assert result.status is SettlementStatus.DEFERRED
        assert result.charge is None
        assert ledger.available(session, credit) == Decimal("9700.00")
        assert session.exec(
            select(ExceptionItem).where(
                ExceptionItem.kind == ExceptionKind.CALL_UNKNOWN_OUTCOME
            )
        ).one()

    def test_an_answered_leg_with_no_end_keeps_the_hold(
        self, session, authorization, charging, ledger, clock
    ):
        """The one case where releasing would un-fund a live call."""
        user = _user(session)
        credit = _fund(session, ledger, user)
        _tariff(session, clock)
        attempt = _authorize(authorization, session, user)
        _legs(session, attempt, answered=10, state=LegState.ANSWERED)
        _finish(session, attempt, AttemptState.UNKNOWN)

        result = charging.settle(session, attempt)

        assert result.status is SettlementStatus.DEFERRED
        assert result.charge is None
        assert ledger.available(session, credit) == Decimal("9700.00")
        reservation = session.get(Reservation, attempt.reservation_id)
        assert reservation.state is ReservationState.HELD

    def test_a_deferred_call_raises_an_exception_and_a_deadline(
        self, session, authorization, charging, ledger, clock
    ):
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)
        attempt = _authorize(authorization, session, user)
        _legs(session, attempt, answered=10, state=LegState.ANSWERED)
        _finish(session, attempt, AttemptState.UNKNOWN)

        charging.settle(session, attempt)

        item = session.exec(
            select(ExceptionItem).where(
                ExceptionItem.kind == ExceptionKind.CALL_MISSING_TERMINAL_EVENT
            )
        ).one()
        assert item.subject_reference == f"call:{attempt.id}"
        deadline = session.exec(
            select(CallDeadline).where(
                CallDeadline.attempt_id == attempt.id,
                CallDeadline.kind == DeadlineKind.MISSING_TERMINAL_EVENT,
            )
        ).one()
        assert deadline.state is DeadlineState.PENDING

    def test_two_answered_destination_legs_are_never_settled_automatically(
        self, session, authorization, charging, ledger, clock
    ):
        user = _user(session)
        credit = _fund(session, ledger, user)
        _tariff(session, clock)
        attempt = _authorize(authorization, session, user)
        _legs(session, attempt, answered=10, ended=70)
        _legs(session, attempt, answered=100, ended=160)
        _finish(session, attempt)

        result = charging.settle(session, attempt)

        assert result.status is SettlementStatus.AMBIGUOUS
        assert result.charge is None
        assert ledger.available(session, credit) == Decimal("9700.00")
        assert (
            session.exec(
                select(ExceptionItem).where(
                    ExceptionItem.kind
                    == ExceptionKind.CALL_DUPLICATE_BILLABLE_LEG
                )
            ).one()
            is not None
        )


class TestTheAuthorizedMaximumBindsBothSides:
    def test_metered_cost_above_the_hold_charges_the_hold_and_queues_the_rest(
        self, session, authorization, charging, ledger, clock
    ):
        """A 10-minute grant, a 20-minute call. The customer pays what they agreed.

        By hand: 600s authorized at NGN 30/min = NGN 300 held. The provider
        reports 1200s of talk time = NGN 600 metered. NGN 300 settles; NGN 300
        is our exposure, not a surprise on the customer's balance.
        """
        user = _user(session)
        credit = _fund(session, ledger, user)
        _tariff(session, clock)
        attempt = _authorize(authorization, session, user, requested_seconds=600)
        _legs(session, attempt, answered=0, ended=1200)
        _finish(session, attempt)

        result = charging.settle(session, attempt)

        assert result.status is SettlementStatus.SETTLED
        assert result.shortfall == Decimal("300.00")
        assert result.charge.charged_amount == Decimal("300.00")
        assert ledger.balance(session, credit) == Decimal("9700.00")
        item = session.exec(
            select(ExceptionItem).where(
                ExceptionItem.kind == ExceptionKind.CALL_SETTLEMENT_SHORTFALL
            )
        ).one()
        assert "300.00" in item.detail

    def test_the_stored_breakdown_always_adds_up_to_what_posted(
        self, session, authorization, charging, ledger, clock
    ):
        """The database constraint, proven rather than assumed."""
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock, setup=Decimal("5.000000"))
        attempt = _authorize(authorization, session, user, requested_seconds=600)
        _legs(session, attempt, answered=0, ended=1200)
        _finish(session, attempt)

        charge = charging.settle(session, attempt).charge
        session.commit()

        assert charge.setup_amount + charge.usage_amount == charge.charged_amount


class TestCorrectionsMoveOnlyTheDifference:
    def test_an_operator_correction_reuses_the_bounded_call_path(
        self, session, authorization, charging, ledger, clock
    ):
        """The operations surface cannot invent accounts or exceed the call hold."""
        _, credit, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        original = charging.settle(session, attempt).charge
        operator = AdminUser(
            email=f"ops-{uuid4().hex[:8]}@example.test",
            password_hash="x",
            locale=Locale.EN,
            role=AdminRole.ADMIN,
        )
        exception = ExceptionItem(
            kind=ExceptionKind.CALL_SETTLEMENT_SHORTFALL,
            subject_reference=f"call:{attempt.id}",
            detail="supplier CDR differs from the event-derived charge",
            raised_at=clock(),
        )
        session.add_all([operator, exception])
        session.flush()

        operations = OperationsService(ledger, clock=clock)
        action = operations.correct_call_settlement(
            session,
            original,
            charging=charging,
            actor=operator,
            billable_seconds=180,
            setup_amount=Decimal("0.00"),
            usage_amount=Decimal("90.00"),
            reason="supplier CDR reviewed against the original call",
            idempotency_key="call-correction-1",
            exception_item=exception,
        )
        replay = operations.correct_call_settlement(
            session,
            original,
            charging=charging,
            actor=operator,
            billable_seconds=180,
            setup_amount=Decimal("0.0"),
            usage_amount=Decimal("90.0"),
            reason="supplier CDR reviewed against the original call",
            idempotency_key="call-correction-1",
            exception_item=exception,
        )

        assert action.kind is OperatorActionKind.CORRECT_CALL_SETTLEMENT
        assert replay.id == action.id
        assert action.ledger_entry_id is not None
        assert session.get(CallCharge, original.id).state is ChargeState.SUPERSEDED
        assert ledger.balance(session, credit) == Decimal("9910.00")
        assert exception.resolved_at is not None
        assert session.exec(
            select(ExceptionItem).where(
                ExceptionItem.kind == ExceptionKind.SETTLEMENT_MISMATCH,
                ExceptionItem.resolved_at.is_(None),
            )
        ).all() == []

    def test_a_higher_supplier_record_posts_the_difference_only(
        self, session, authorization, charging, ledger, clock
    ):
        """NGN 60 settled, NGN 90 confirmed: NGN 30 moves, not 150."""
        _, credit, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        original = charging.settle(session, attempt).charge

        corrected = charging.correct(
            session,
            original,
            billable_seconds=180,
            setup_amount=Decimal("0.00"),
            usage_amount=Decimal("90.00"),
            basis=ChargeBasis.SUPPLIER_CDR,
            detail="supplier CDR reports 150 seconds",
        )

        assert corrected.charged_amount == Decimal("90.00")
        assert corrected.corrects_id == original.id
        assert session.get(CallCharge, original.id).state is ChargeState.SUPERSEDED
        # 10000 - 60 - 30.
        assert ledger.balance(session, credit) == Decimal("9910.00")

    def test_a_lower_supplier_record_gives_the_difference_back(
        self, session, authorization, charging, ledger, clock
    ):
        _, credit, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        original = charging.settle(session, attempt).charge

        charging.correct(
            session,
            original,
            billable_seconds=60,
            setup_amount=Decimal("0.00"),
            usage_amount=Decimal("30.00"),
            basis=ChargeBasis.SUPPLIER_CDR,
            detail="supplier CDR reports 45 seconds",
        )

        assert ledger.balance(session, credit) == Decimal("9970.00")

    def test_the_original_entry_is_never_touched(
        self, session, authorization, charging, ledger, clock
    ):
        _, _, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        original = charging.settle(session, attempt).charge
        entry_id = original.journal_entry_id
        lines_before = session.exec(
            select(JournalLine).where(JournalLine.entry_id == entry_id)
        ).all()
        amounts_before = sorted(line.amount for line in lines_before)

        charging.correct(
            session,
            original,
            billable_seconds=180,
            setup_amount=Decimal("0.00"),
            usage_amount=Decimal("90.00"),
            basis=ChargeBasis.SUPPLIER_CDR,
            detail="supplier CDR",
        )

        lines_after = session.exec(
            select(JournalLine).where(JournalLine.entry_id == entry_id)
        ).all()
        assert sorted(line.amount for line in lines_after) == amounts_before

    def test_a_correction_that_changes_nothing_posts_nothing(
        self, session, authorization, charging, ledger, clock
    ):
        _, credit, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        original = charging.settle(session, attempt).charge
        before = ledger.balance(session, credit)

        corrected = charging.correct(
            session,
            original,
            billable_seconds=120,
            setup_amount=Decimal("0.00"),
            usage_amount=Decimal("60.00"),
            basis=ChargeBasis.SUPPLIER_CDR,
            detail="supplier CDR agrees",
        )

        assert corrected.journal_entry_id is None
        assert ledger.balance(session, credit) == before

    def test_a_superseded_charge_cannot_be_corrected_again(
        self, session, authorization, charging, ledger, clock
    ):
        _, _, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        original = charging.settle(session, attempt).charge
        charging.correct(
            session,
            original,
            billable_seconds=180,
            setup_amount=Decimal("0.00"),
            usage_amount=Decimal("90.00"),
            basis=ChargeBasis.SUPPLIER_CDR,
            detail="first",
        )

        with pytest.raises(ChargingError) as excinfo:
            charging.correct(
                session,
                original,
                billable_seconds=240,
                setup_amount=Decimal("0.00"),
                usage_amount=Decimal("120.00"),
                basis=ChargeBasis.SUPPLIER_CDR,
                detail="second",
            )
        assert excinfo.value.code == "charge_already_superseded"

    def test_a_correction_cannot_charge_past_the_authorized_maximum(
        self, session, authorization, charging, ledger, clock
    ):
        _, credit, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        original = charging.settle(session, attempt).charge

        corrected = charging.correct(
            session,
            original,
            billable_seconds=1_200,
            setup_amount=Decimal("0.00"),
            usage_amount=Decimal("600.00"),
            basis=ChargeBasis.SUPPLIER_CDR,
            detail="supplier amount exceeds the customer authorization",
        )

        assert corrected.charged_amount == Decimal("300.00")
        assert ledger.balance(session, credit) == Decimal("9700.00")
        assert session.exec(
            select(ExceptionItem).where(
                ExceptionItem.kind == ExceptionKind.CALL_SETTLEMENT_SHORTFALL
            )
        ).one()

    def test_a_late_increase_cannot_overdraw_a_released_hold(
        self, session, authorization, charging, ledger, clock
    ):
        _, credit, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        original = charging.settle(session, attempt).charge
        charging.finalize_provisional(session, attempt)

        corrected = charging.correct(
            session,
            original,
            billable_seconds=180,
            setup_amount=Decimal("0.00"),
            usage_amount=Decimal("90.00"),
            basis=ChargeBasis.SUPPLIER_CDR,
            detail="late supplier adjustment",
        )

        assert corrected.charged_amount == Decimal("60.00")
        assert ledger.balance(session, credit) == Decimal("9940.00")
        assert session.exec(
            select(ExceptionItem).where(
                ExceptionItem.kind == ExceptionKind.CALL_SETTLEMENT_SHORTFALL
            )
        ).one()


class TestSupplierCostIsADifferentNumber:
    def test_supplier_cost_is_recorded_without_touching_the_customer_charge(
        self, session, authorization, charging, ledger, clock
    ):
        _, credit, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        charge = charging.settle(session, attempt).charge
        balance_before = ledger.balance(session, credit)

        charging.record_supplier_cost(
            session,
            provider="telnyx",
            provider_reference="cdr-1",
            component=SupplierCostComponent.PSTN_TERMINATION,
            currency="USD",
            amount=Decimal("0.004"),
            attempt=attempt,
        )

        assert ledger.balance(session, credit) == balance_before
        assert session.get(CallCharge, charge.id).charged_amount == Decimal("60.00")
        assert charging.supplier_cost_total(session, attempt, "USD") == Decimal("0.00")

    def test_a_redelivered_cdr_is_not_counted_twice(
        self, session, authorization, charging, ledger, clock
    ):
        _, _, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        for _ in range(2):
            charging.record_supplier_cost(
                session,
                provider="telnyx",
                provider_reference="cdr-7",
                component=SupplierCostComponent.VOICE_API,
                currency="USD",
                amount=Decimal("0.10"),
                attempt=attempt,
            )
        rows = session.exec(
            select(CallSupplierCost).where(CallSupplierCost.attempt_id == attempt.id)
        ).all()
        assert len(rows) == 1
        assert charging.supplier_cost_total(session, attempt, "USD") == Decimal("0.10")

    def test_two_components_of_one_call_are_both_recorded(
        self, session, authorization, charging, ledger, clock
    ):
        """V01 could not establish how many components a call bills. So: count them."""
        _, _, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        charging.record_supplier_cost(
            session,
            provider="telnyx",
            provider_reference="cdr-9",
            component=SupplierCostComponent.WEBRTC,
            currency="USD",
            amount=Decimal("0.01"),
            attempt=attempt,
        )
        charging.record_supplier_cost(
            session,
            provider="telnyx",
            provider_reference="cdr-9",
            component=SupplierCostComponent.PSTN_TERMINATION,
            currency="USD",
            amount=Decimal("0.02"),
            attempt=attempt,
        )
        assert charging.supplier_cost_total(session, attempt, "USD") == Decimal("0.03")

    def test_a_cost_we_cannot_attribute_is_kept_and_queued(
        self, session, charging
    ):
        record = charging.record_supplier_cost(
            session,
            provider="telnyx",
            provider_reference="cdr-orphan",
            component=SupplierCostComponent.PSTN_TERMINATION,
            currency="USD",
            amount=Decimal("0.50"),
        )
        assert record.attempt_id is None
        item = session.exec(
            select(ExceptionItem).where(
                ExceptionItem.kind == ExceptionKind.CALL_SUPPLIER_COST_UNMATCHED
            )
        ).one()
        assert "cdr-orphan" in item.subject_reference

    def test_a_supplier_reference_replayed_with_different_facts_is_rejected(
        self, session, charging
    ):
        charging.record_supplier_cost(
            session,
            provider="telnyx",
            provider_reference="cdr-conflict",
            component=SupplierCostComponent.PSTN_TERMINATION,
            currency="USD",
            amount=Decimal("0.10"),
        )

        with pytest.raises(ChargingError) as excinfo:
            charging.record_supplier_cost(
                session,
                provider="telnyx",
                provider_reference="cdr-conflict",
                component=SupplierCostComponent.PSTN_TERMINATION,
                currency="USD",
                amount=Decimal("0.11"),
            )

        assert excinfo.value.code == "supplier_cost_idempotency_conflict"


class TestDeadlinesSurviveTheWorker:
    def test_a_due_deadline_is_claimed_once_by_one_worker(
        self, engine, session, authorization, charging, ledger, clock
    ):
        _, _, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        charging.schedule(
            session,
            attempt,
            DeadlineKind.RESERVATION_RENEWAL,
            clock() - timedelta(seconds=1),
        )
        session.commit()
        barrier = Barrier(2)

        def claim():
            with Session(engine) as worker:
                local = CallChargingService(LedgerService(clock=clock), clock=clock)
                barrier.wait(timeout=10)
                rows = local.claim_due(worker, now=clock())
                worker.commit()
                return [row.id for row in rows]

        with ThreadPoolExecutor(max_workers=2) as pool:
            claimed = [future.result(timeout=30) for future in (
                pool.submit(claim), pool.submit(claim)
            )]

        assert sorted(len(batch) for batch in claimed) == [0, 1]

    def test_scheduling_the_same_deadline_twice_keeps_one_row(
        self, session, authorization, charging, ledger, clock
    ):
        _, _, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        first = charging.schedule(
            session, attempt, DeadlineKind.RESERVATION_RENEWAL, clock()
        )
        second = charging.schedule(
            session, attempt, DeadlineKind.RESERVATION_RENEWAL, clock()
        )
        assert first.id == second.id

    def test_an_abandoned_claim_returns_to_the_queue(
        self, session, authorization, charging, ledger, clock
    ):
        """A worker that died between claiming and finishing."""
        _, _, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        deadline = charging.schedule(
            session,
            attempt,
            DeadlineKind.UNKNOWN_OUTCOME_REVIEW,
            clock() - timedelta(seconds=1),
        )
        claimed = charging.claim_due(session, now=clock())
        assert [row.id for row in claimed] == [deadline.id]

        charging.release_claim(session, deadline, detail="worker restarted")
        again = charging.claim_due(session, now=clock())

        assert [row.id for row in again] == [deadline.id]
        assert deadline.attempts == 2

    def test_a_claim_from_a_dead_worker_is_reclaimed_after_its_lease(
        self, session, authorization, charging, ledger, clock
    ):
        _, _, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        deadline = charging.schedule(
            session,
            attempt,
            DeadlineKind.UNKNOWN_OUTCOME_REVIEW,
            clock() - timedelta(seconds=1),
        )
        assert charging.claim_due(session, now=clock()) == [deadline]
        session.commit()  # the worker dies after this commit

        clock.advance(seconds=charging.claim_timeout_seconds + 1)
        reclaimed = charging.claim_due(session, now=clock())

        assert [row.id for row in reclaimed] == [deadline.id]
        assert reclaimed[0].attempts == 2

    def test_a_future_deadline_is_not_claimed_early(
        self, session, authorization, charging, ledger, clock
    ):
        _, _, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        charging.schedule(
            session,
            attempt,
            DeadlineKind.SUPPLIER_COST_WAIT,
            clock() + timedelta(hours=1),
        )
        assert charging.claim_due(session, now=clock()) == []

    def test_settling_schedules_the_supplier_wait(
        self, session, authorization, charging, ledger, clock
    ):
        _, _, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        charge = charging.settle(session, attempt).charge

        assert charge.state is ChargeState.PROVISIONAL
        deadline = session.exec(
            select(CallDeadline).where(
                CallDeadline.attempt_id == attempt.id,
                CallDeadline.kind == DeadlineKind.SUPPLIER_COST_WAIT,
            )
        ).one()
        assert deadline.due_at > clock()

    def test_finalizing_after_the_supplier_window_releases_the_remainder(
        self, session, authorization, charging, ledger, clock
    ):
        _, credit, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        charging.settle(session, attempt)

        charge = charging.finalize_provisional(session, attempt)

        assert charge.state is ChargeState.FINAL
        assert ledger.available(session, credit) == Decimal("9940.00")
        reservation = session.get(Reservation, attempt.reservation_id)
        assert reservation.released_amount == Decimal("240.00")

    def test_a_missing_cdr_is_queued_when_the_worker_finalizes_the_charge(
        self, session, authorization, charging, ledger, clock
    ):
        _, credit, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        charge = charging.settle(session, attempt).charge
        deadline = session.exec(
            select(CallDeadline).where(
                CallDeadline.attempt_id == attempt.id,
                CallDeadline.kind == DeadlineKind.SUPPLIER_COST_WAIT,
            )
        ).one()

        _resolve_deadline(
            session, charging, object(), deadline  # type: ignore[arg-type]
        )

        assert charge.state is ChargeState.FINAL
        assert ledger.available(session, credit) == Decimal("9940.00")
        item = session.exec(
            select(ExceptionItem).where(
                ExceptionItem.kind == ExceptionKind.SETTLEMENT_MISMATCH
            )
        ).one()
        assert item.subject_reference == f"call-missing-cdr:{attempt.id}"

    def test_a_supplier_cdr_correction_satisfies_the_evidence_wait(
        self, session, authorization, charging, ledger, clock
    ):
        _, _, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        original = charging.settle(session, attempt).charge
        deadline = session.exec(
            select(CallDeadline).where(
                CallDeadline.attempt_id == attempt.id,
                CallDeadline.kind == DeadlineKind.SUPPLIER_COST_WAIT,
            )
        ).one()
        corrected = charging.correct(
            session,
            original,
            billable_seconds=120,
            setup_amount=Decimal("0.00"),
            usage_amount=Decimal("60.00"),
            basis=ChargeBasis.SUPPLIER_CDR,
            detail="supplier CDR agrees",
        )

        _resolve_deadline(
            session, charging, object(), deadline  # type: ignore[arg-type]
        )

        assert corrected.state is ChargeState.FINAL
        assert session.exec(select(ExceptionItem)).all() == []


class TestEnforcementWhileTheCallRuns:
    def test_a_finished_call_is_not_kept_alive(
        self, session, authorization, charging, ledger, clock
    ):
        _, _, attempt = _ready_call(
            session, authorization, charging, ledger, clock
        )
        outcome = charging.enforce(session, attempt)
        assert outcome.decision is EnforcementDecision.STOP

    def test_a_live_call_on_an_open_hold_continues(
        self, session, authorization, charging, ledger, clock
    ):
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)
        attempt = _authorize(authorization, session, user)
        attempt.state = AttemptState.ANSWERED
        attempt.grant_consumed_at = clock()
        session.add(attempt)
        session.flush()

        outcome = charging.enforce(session, attempt)
        assert outcome.decision is EnforcementDecision.CONTINUE

    def test_carrier_and_internet_spend_are_not_pooled_by_default(
        self, session, authorization, charging, ledger, clock
    ):
        """The amendment forbids an unrestricted common pool while carrier
        exposure is unbounded. The reason is returned, not implied."""
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)
        attempt = _authorize(authorization, session, user)
        attempt.state = AttemptState.ANSWERED
        attempt.grant_consumed_at = clock()
        session.add(attempt)
        session.flush()

        outcome = charging.enforce(session, attempt, carrier_bounded=False)
        assert outcome.decision is EnforcementDecision.CONTINUE
        assert "not pooled" in outcome.reason

    def test_a_closed_hold_stops_the_call(
        self, session, authorization, charging, ledger, clock
    ):
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)
        attempt = _authorize(authorization, session, user)
        attempt.state = AttemptState.ANSWERED
        attempt.grant_consumed_at = clock()
        session.add(attempt)
        reservation = session.get(Reservation, attempt.reservation_id)
        ledger.release(session, reservation)

        outcome = charging.enforce(session, attempt)
        assert outcome.decision is EnforcementDecision.STOP
        assert "hold" in outcome.reason

    def test_an_expired_reservation_stops_the_call(
        self, session, authorization, charging, ledger, clock
    ):
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)
        attempt = _authorize(authorization, session, user)
        attempt.state = AttemptState.ANSWERED
        attempt.grant_consumed_at = clock()
        reservation = session.get(Reservation, attempt.reservation_id)
        reservation.expires_at = clock() - timedelta(seconds=1)
        session.add_all([attempt, reservation])
        session.flush()

        outcome = charging.enforce(session, attempt)

        assert outcome.decision is EnforcementDecision.STOP
        assert "expired" in outcome.reason

    def test_the_deadline_worker_issues_a_durable_hangup_when_enforcement_stops(
        self, session, authorization, charging, ledger, clock
    ):
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)
        attempt = _authorize(authorization, session, user)
        attempt.state = AttemptState.ANSWERED
        attempt.grant_consumed_at = clock()
        leg = _legs(
            session,
            attempt,
            answered=10,
            state=LegState.ANSWERED,
        )
        reservation = session.get(Reservation, attempt.reservation_id)
        reservation.expires_at = clock() - timedelta(seconds=1)
        deadline = charging.schedule(
            session,
            attempt,
            DeadlineKind.RESERVATION_RENEWAL,
            clock(),
        )
        session.add_all([attempt, reservation])
        session.flush()

        class RecordingLifecycle:
            def __init__(self):
                self.legs = []

            def hangup(self, _session, _attempt, stopped_leg):
                self.legs.append(stopped_leg)

        lifecycle = RecordingLifecycle()
        _resolve_deadline(session, charging, lifecycle, deadline)  # type: ignore[arg-type]

        assert attempt.stop_requested_at is not None
        assert lifecycle.legs == [leg]
        assert deadline.state is DeadlineState.DONE


class TestConcurrentCallsCannotOverspend:
    def test_two_simultaneous_calls_cannot_both_reserve_the_last_funds(
        self, engine, session, authorization, ledger, clock
    ):
        """Mobile and browser, one balance. AC-46.1's overspend case.

        NGN 400 funded, each call wanting NGN 300 held. One succeeds.
        """
        user = _user(session)
        _fund(session, ledger, user, "400.00")
        _tariff(session, clock)
        session.commit()
        user_id = user.id
        barrier = Barrier(2)

        def place_call(tag: str):
            with Session(engine) as worker:
                local = CallAuthorizationService(
                    LedgerService(clock=clock),
                    clock=clock,
                    supported_countries=frozenset({"NG"}),
                    route_enabled=True,
                )
                caller = worker.get(User, user_id)
                barrier.wait(timeout=10)
                try:
                    local.authorize(
                        worker,
                        caller,
                        "+2348031234567",
                        idempotency_key=f"race-{tag}",
                        currency="NGN",
                        identity_e164="+2347000000001",
                        requested_seconds=600,
                    )
                    worker.commit()
                    return "authorized"
                except Exception as error:  # noqa: BLE001 - the code is the assertion
                    worker.rollback()
                    return getattr(error, "code", "error")

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = (pool.submit(place_call, "a"), pool.submit(place_call, "b"))
            outcomes = sorted(future.result(timeout=30) for future in futures)

        assert outcomes == ["authorized", "insufficient_funds"]
        with Session(engine) as check:
            held = check.exec(
                select(Reservation).where(Reservation.state == ReservationState.HELD)
            ).all()
            assert len(held) == 1


class TestOrganizationBudgets:
    def test_call_spend_counts_against_a_recorded_organization_cap(
        self, session, charging, ledger, clock
    ):
        """Without a recorded policy the answer is None — not zero, not unlimited."""
        organization = Organization(
            name=f"Org {uuid4().hex[:6]}",
            primary_contact_name="Contact",
            phone_number=f"+23490{uuid4().int % 10**8:08d}",
            email=f"org-{uuid4().hex[:8]}@example.test",
            password_hash="x",
            org_type=OrganizationType.ENTERPRISE,
        )
        session.add(organization)
        session.flush()
        assert (
            charging.organization_call_headroom(
                session, organization.id, "NGN", clock() - timedelta(days=30)
            )
            is None
        )
