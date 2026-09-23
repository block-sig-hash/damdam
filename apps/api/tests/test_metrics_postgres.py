"""Operational metrics against real data — US-42, chunk 26C.

Metrics are queries, and a query that quietly returns the wrong set is the kind
of defect that shows a green dashboard during an outage. So these assert the
boundaries rather than the happy path: what counts as "still owed", what `None`
means, and that carrier work and calling work stay in separate numbers.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from app import model_registry  # noqa: F401
from app.auth.models import Platform, User
from app.calling.models import (
    AttemptState,
    CallAttempt,
    CallEvent,
    EventDisposition,
    PayerKind,
)
from app.catalog.market import PublicationStatus
from app.catalog.models import LegalEntity, Product, ProductKind
from app.catalog.tariffs import DestinationKind, OriginKind, Tariff, TariffRate
from app.fulfilment.models import AttemptOutcome, SupplierAttempt
from app.ledger.models import AccountKind, Direction, OwnerKind
from app.ledger.service import LedgerService, Posting
from app.metrics import collect_metrics, render_prometheus
from app.orders.models import Order, OrderItem, PaymentState, ProvisioningState
from app.refunds.models import ExceptionItem, ExceptionKind

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="these metrics are database queries and must be proved against one",
)

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
TABLES = (
    "call_events, call_legs, call_attempts, exception_items, supplier_attempts, "
    "usage_counter_readings, carrier_lines, entitlements, order_items, orders, "
    "tariff_rates, tariffs, journal_lines, journal_entries, ledger_reservations, "
    "ledger_accounts, products, legal_entities, users"
)


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


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
def clock() -> Clock:
    return Clock()


def _unknown_call(session: Session) -> CallAttempt:
    """One call whose outcome we lost. Everything else is scaffolding."""
    caller = User(
        phone_number=f"+23487{uuid4().int % 10**8:08d}",
        first_name="Caller",
        platform=Platform.ANDROID,
    )
    voice = Product(
        sku=f"voice-{uuid4().hex[:8]}",
        name="Internet calling",
        kind=ProductKind.VOICE,
    )
    session.add_all([caller, voice])
    session.flush()
    tariff = Tariff(
        product_id=voice.id,
        currency="NGN",
        version=1,
        status=PublicationStatus.PUBLISHED,
        effective_from=NOW - timedelta(days=1),
        evidence_reference="test fixture — not a rate claim (B2 open)",
        verified_at=NOW - timedelta(days=1),
    )
    session.add(tariff)
    session.flush()
    session.add(
        TariffRate(
            tariff_id=tariff.id,
            origin_kind=OriginKind.INTERNET,
            origin_country=None,
            destination_country="GB",
            destination_kind=DestinationKind.LANDLINE,
            per_minute_amount=Decimal("120.000000"),
            setup_amount=Decimal("0.000000"),
            minimum_seconds=0,
            increment_seconds=60,
        )
    )
    # `call_attempts.reservation_id` is NOT NULL: V02's design is that no
    # attempt exists without money already held, so a fixture cannot skip it
    # without describing a call the schema does not permit.
    ledger = LedgerService()
    credit = ledger.account(
        session, "NGN", AccountKind.SERVICE_CREDIT, OwnerKind.USER,
        owner_user_id=caller.id,
    )
    clearing = ledger.account(session, "NGN", AccountKind.SETTLEMENT_CLEARING)
    ledger.post(
        session,
        f"funding:{uuid4()}",
        [
            Posting(clearing, Direction.DEBIT, Decimal("10000.00")),
            Posting(credit, Direction.CREDIT, Decimal("10000.00")),
        ],
    )
    session.flush()
    reservation = ledger.reserve(
        session, credit, Decimal("1200.000000"), f"call:{uuid4()}"
    )

    attempt = CallAttempt(
        owner_user_id=caller.id,
        reservation_id=reservation.id,
        payer_kind=PayerKind.USER,
        currency="NGN",
        e164_destination="+441632960011",
        destination_country="GB",
        destination_kind=DestinationKind.LANDLINE,
        origin_kind=OriginKind.INTERNET,
        identity_e164="+2348000000001",
        tariff_id=tariff.id,
        tariff_version=1,
        rate_per_minute_amount=Decimal("120.000000"),
        rate_setup_amount=Decimal("0.000000"),
        rate_minimum_seconds=0,
        rate_increment_seconds=60,
        idempotency_key=f"call-{uuid4().hex[:8]}",
        max_seconds=600,
        max_charge_amount=Decimal("1200.000000"),
        state=AttemptState.UNKNOWN,
        expires_at=NOW + timedelta(minutes=10),
        created_at=NOW,
    )
    session.add(attempt)
    session.flush()
    return attempt


def _order_item(
    session: Session,
    *,
    state: ProvisioningState,
    placed_at: datetime,
    payment_state: PaymentState = PaymentState.PAID,
) -> OrderItem:
    entity = LegalEntity(code=f"E{uuid4().hex[:6]}", name="Seller", country="NG")
    product = Product(
        sku=f"sku-{uuid4().hex[:8]}", name="Nigeria 5GB", kind=ProductKind.DATA
    )
    user = User(
        phone_number=f"+23488{uuid4().int % 10**8:08d}",
        first_name="Payer",
        platform=Platform.ANDROID,
    )
    session.add_all([entity, product, user])
    session.flush()
    order = Order(
        reference=f"ORD-{uuid4().hex[:8].upper()}",
        seller_legal_entity_id=entity.id,
        payer_user_id=user.id,
        currency="NGN",
        total_amount=Decimal("5000.00"),
        payment_state=payment_state,
        placed_at=placed_at,
    )
    session.add(order)
    session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        recipient_user_id=user.id,
        quantity=1,
        unit_currency="NGN",
        unit_amount=Decimal("5000.00"),
        provisioning_state=state,
    )
    session.add(item)
    session.flush()
    return item


class TestNothingMeasuredIsNotZero:
    def test_an_empty_system_reports_none_rather_than_zero(
        self, session, clock
    ) -> None:
        """The distinction the whole module is built around.

        A system that has never observed usage and one whose usage is perfectly
        fresh would both report `0` if absence collapsed to zero. One is healthy
        and the other has a poller that never started.
        """
        metrics = collect_metrics(session, clock)

        assert metrics.oldest_unprovisioned_order_seconds is None
        assert metrics.webhook_lag_seconds is None
        assert metrics.usage_staleness_seconds is None
        assert metrics.unknown_supplier_outcomes == 0

    def test_prometheus_omits_a_missing_series_instead_of_exporting_zero(
        self, session, clock
    ) -> None:
        rendered = render_prometheus(collect_metrics(session, clock))

        # The HELP/TYPE lines are present so the series is documented; no
        # sample line is, because there is nothing to sample.
        assert "# TYPE damdam_usage_staleness_seconds gauge" in rendered
        assert "\ndamdam_usage_staleness_seconds " not in rendered
        # A real zero is still exported.
        assert "\ndamdam_unknown_supplier_outcomes 0" in rendered


class TestOldestUnprovisionedOrder:
    def test_it_measures_the_oldest_order_that_still_owes_a_service(
        self, session, clock
    ) -> None:
        _order_item(
            session,
            state=ProvisioningState.REQUESTED,
            placed_at=NOW - timedelta(hours=3),
        )
        _order_item(
            session,
            state=ProvisioningState.NOT_STARTED,
            placed_at=NOW - timedelta(minutes=5),
        )

        metrics = collect_metrics(session, clock)

        assert metrics.oldest_unprovisioned_order_seconds == pytest.approx(10_800)

    def test_a_provisioned_order_does_not_count(self, session, clock) -> None:
        _order_item(
            session,
            state=ProvisioningState.PROVISIONED,
            placed_at=NOW - timedelta(days=30),
        )

        metrics = collect_metrics(session, clock)
        assert metrics.oldest_unprovisioned_order_seconds is None

    @pytest.mark.parametrize(
        "closed", [ProvisioningState.FAILED, ProvisioningState.CANCELLED]
    )
    def test_a_closed_item_does_not_pin_the_metric_forever(
        self, session, clock, closed
    ) -> None:
        """Otherwise one bad order in March keeps the alarm on until December.

        A metric that never returns to zero stops being read, and then it is
        not a metric.
        """
        _order_item(session, state=closed, placed_at=NOW - timedelta(days=90))

        metrics = collect_metrics(session, clock)
        assert metrics.oldest_unprovisioned_order_seconds is None

    def test_an_unpaid_order_is_not_waiting_on_us(self, session, clock) -> None:
        _order_item(
            session,
            state=ProvisioningState.NOT_STARTED,
            placed_at=NOW - timedelta(days=2),
            payment_state=PaymentState.UNPAID,
        )

        metrics = collect_metrics(session, clock)
        assert metrics.oldest_unprovisioned_order_seconds is None


class TestCarrierAndCallingStaySeparate:
    def test_a_lost_call_outcome_is_not_counted_as_a_lost_purchase(
        self, session, clock
    ) -> None:
        """The calling amendment requires exactly this separation.

        They share a supplier and nothing else: a stalled eSIM issuance and a
        lost call outcome need different people and different runbooks. One
        combined number would read green while either half was on fire.
        """
        item = _order_item(
            session, state=ProvisioningState.OUTCOME_UNKNOWN, placed_at=NOW
        )
        session.add(
            SupplierAttempt(
                order_item_id=item.id,
                provider="telnyx",
                idempotency_key=f"item:{item.id}:1",
                attempt_number=1,
                outcome=AttemptOutcome.OUTCOME_UNKNOWN,
                requested_at=NOW,
                created_at=NOW,
            )
        )
        _unknown_call(session)

        metrics = collect_metrics(session, clock)

        assert metrics.unknown_supplier_outcomes == 1
        assert metrics.unknown_call_outcomes == 1


class TestEventHealth:
    def test_a_quarantined_event_is_counted_apart_from_one_that_arrived_early(
        self, session, clock
    ) -> None:
        """Unmatched is ordinary; quarantined is a security signal.

        Filing a contradicted event under "arrived early" is how a credential
        mismatch becomes invisible.
        """
        for disposition in (
            EventDisposition.QUARANTINED,
            EventDisposition.UNMATCHED,
            EventDisposition.UNMATCHED,
            EventDisposition.APPLIED,
        ):
            session.add(
                CallEvent(
                    provider="telnyx",
                    provider_event_id=uuid4().hex,
                    event_type="call.answered",
                    occurred_at=NOW - timedelta(minutes=2),
                    received_at=NOW - timedelta(minutes=1),
                    disposition=disposition,
                )
            )
        session.flush()

        metrics = collect_metrics(session, clock)

        assert metrics.quarantined_events == 1
        assert metrics.unmatched_events == 2
        assert metrics.webhook_lag_seconds == pytest.approx(60)


class TestOpenExceptions:
    def test_only_unresolved_items_are_counted_and_they_are_grouped_by_kind(
        self, session, clock
    ) -> None:
        session.add(
            ExceptionItem(
                kind=ExceptionKind.SETTLEMENT_MISMATCH,
                subject_reference="payment:1",
                detail="open",
                raised_at=NOW,
            )
        )
        session.add(
            ExceptionItem(
                kind=ExceptionKind.SETTLEMENT_MISMATCH,
                subject_reference="payment:2",
                detail="open",
                raised_at=NOW,
            )
        )
        session.add(
            ExceptionItem(
                kind=ExceptionKind.USAGE_DISCREPANCY,
                subject_reference="line:1",
                detail="resolved",
                raised_at=NOW,
                resolved_at=NOW,
            )
        )
        session.flush()

        metrics = collect_metrics(session, clock)

        assert metrics.open_exceptions == {"settlement_mismatch": 2}
        assert metrics.open_exception_total == 2


class TestClockSkew:
    def test_a_future_timestamp_reports_zero_rather_than_a_negative_age(
        self, session, clock
    ) -> None:
        """A negative age on a dashboard reads as a broken dashboard.

        It is clock skew between this process and the database, and clamping to
        zero says "as fresh as it gets" instead of inviting somebody to debug
        the wrong system.
        """
        session.add(
            CallEvent(
                provider="telnyx",
                provider_event_id=uuid4().hex,
                event_type="call.answered",
                occurred_at=NOW,
                received_at=NOW + timedelta(minutes=5),
                disposition=EventDisposition.APPLIED,
            )
        )
        session.flush()

        assert collect_metrics(session, clock).webhook_lag_seconds == 0.0
