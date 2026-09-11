"""US-36 chunk 16 — usage reconciliation and carrier charging, on PostgreSQL.

The invariant the chunk turns on: **usage is counted once.** Every test here is
a way that fails — a counter read as a delta, a replayed page, a late CDR
arriving twice, a supplier correcting itself, the same bytes reported by two
sources, a WebRTC record summed into a carrier line.

The second invariant is quieter and matters as much: **a number nobody measured
is not a measurement.** `prd.md` AC-36.4 forbids presenting a delayed app-side
figure as a guaranteed one, so a balance carries when it was observed and
whether that is fresh, stale or unknown.

PostgreSQL, not SQLite: the deduplication guard is a unique constraint, the
channel rule is a CHECK, and the ledger's balance trigger is what stops a
compensating entry from being written wrong.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app import model_registry  # noqa: F401  -- completes SQLModel.metadata
from app.auth.models import Locale, Organization, OrganizationType, Platform, User
from app.catalog.market import PublicationStatus
from app.catalog.models import (
    LegalEntity,
    Product,
    ProductAllowance,
    ProductKind,
)
from app.catalog.tariffs import DestinationKind, OriginKind, Tariff, TariffRate
from app.connectivity.contract import AdapterChannel
from app.connectivity.models import CarrierLine, Entitlement
from app.ledger.models import AccountKind, JournalEntry, JournalLine, OwnerKind
from app.ledger.service import LedgerService
from app.orders.models import Order, OrderItem
from app.refunds.models import ExceptionItem, ExceptionKind
from app.usage.contract import CounterSnapshot, UsageEvent, UsageKind
from app.usage.models import (
    CounterReading,
    CursorState,
    UsageRecord,
    UsageSource,
    UsageState,
)
from app.usage.service import (
    Freshness,
    UsageError,
    UsageService,
    price_call,
)

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="usage deduplication and the ledger's balance trigger need PostgreSQL",
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
TABLES = (
    "usage_records, usage_counter_readings, usage_cursors, exception_items, "
    "journal_lines, journal_entries, ledger_accounts, tariff_rates, tariffs, "
    "carrier_lines, esim_installations, entitlements, order_items, orders, "
    "product_allowances, products, legal_entities, organizations, users"
)


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
def clock() -> Clock:
    return Clock()


@pytest.fixture
def ledger(clock: Clock) -> LedgerService:
    return LedgerService(clock=clock)


@pytest.fixture
def service(ledger: LedgerService, clock: Clock) -> UsageService:
    return UsageService(ledger, clock=clock)


def _line(
    session: Session,
    data_bytes: int = 5_000_000_000,
    voice_seconds: int = 3600,
    authoritative: str | None = None,
    payer_organization: Organization | None = None,
) -> CarrierLine:
    """A provisioned line with an entitlement behind it."""
    entity = LegalEntity(code=f"E{uuid4().hex[:6]}", name="Seller", country="NG")
    product = Product(
        sku=f"sku-{uuid4().hex[:8]}", name="Global 5GB", kind=ProductKind.BUNDLE
    )
    payer = User(
        phone_number=f"+23488{uuid4().int % 10**8:08d}",
        first_name="payer",
        platform=Platform.ANDROID,
    )
    session.add_all([entity, product, payer])
    session.flush()
    session.add(
        ProductAllowance(
            product_id=product.id,
            data_bytes=data_bytes,
            voice_seconds=voice_seconds,
            validity_days=30,
            created_at=NOW,
        )
    )
    order = Order(
        reference=f"ord-{uuid4().hex[:12]}",
        seller_legal_entity_id=entity.id,
        payer_user_id=None if payer_organization else payer.id,
        payer_organization_id=payer_organization.id if payer_organization else None,
        currency="NGN",
        total_amount=Decimal("5000.00"),
    )
    session.add(order)
    session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        recipient_user_id=payer.id,
        unit_currency="NGN",
        unit_amount=Decimal("5000.00"),
    )
    session.add(item)
    session.flush()
    entitlement = Entitlement(
        order_item_id=item.id,
        holder_user_id=payer.id,
        product_id=product.id,
        data_bytes_total=data_bytes,
        voice_seconds_total=voice_seconds,
        granted_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )
    session.add(entitlement)
    session.flush()
    line = CarrierLine(
        entitlement_id=entitlement.id,
        carrier="telnyx",
        carrier_line_reference=f"sim-{uuid4().hex[:10]}",
        authoritative_data_source=authoritative,
        created_at=NOW,
    )
    session.add(line)
    session.flush()
    return line


def _entitlement(session: Session, line: CarrierLine) -> Entitlement:
    entitlement = session.get(Entitlement, line.entitlement_id)
    assert entitlement is not None
    return entitlement


def _tariff(session: Session, line: CarrierLine, **rate_kwargs) -> Tariff:
    entitlement = _entitlement(session, line)
    tariff = Tariff(
        product_id=entitlement.product_id,
        currency="NGN",
        version=1,
        status=PublicationStatus.PUBLISHED,
        effective_from=NOW - timedelta(days=1),
        evidence_reference="fixture rate deck",
        verified_at=NOW - timedelta(days=1),
        created_at=NOW,
    )
    session.add(tariff)
    session.flush()
    defaults = {
        "per_minute_amount": Decimal("25.000000"),
        "setup_amount": Decimal("0.00"),
        "minimum_seconds": 0,
        "increment_seconds": 60,
    }
    defaults.update(rate_kwargs)
    session.add(
        TariffRate(
            tariff_id=tariff.id,
            origin_kind=OriginKind.CARRIER_VISITED_NETWORK,
            origin_country=None,
            destination_country="NG",
            destination_kind=DestinationKind.MOBILE,
            **defaults,
        )
    )
    session.flush()
    return tariff


def _call(line: CarrierLine, seconds: int, **overrides) -> UsageEvent:
    payload = {
        "provider_reference": line.carrier_line_reference,
        "kind": UsageKind.VOICE,
        "quantity": seconds,
        "started_at": NOW,
        "ended_at": NOW + timedelta(seconds=seconds),
        "received_at": NOW + timedelta(minutes=5),
        "destination_country": "NG",
        "destination_kind": "mobile",
        "origin_country": "NG",
    }
    payload.update(overrides)
    return UsageEvent(**payload)


# --- counters ----------------------------------------------------------------


def test_a_cumulative_counter_is_read_as_a_delta_not_a_total(
    session: Session, service: UsageService
) -> None:
    """The single most common way a usage integration overcharges.

    `current_billing_period_consumed_data` is cumulative. Treating each reading
    as consumption charges the whole cycle again on every poll — a customer on a
    five-minute poller would exhaust a 5 GB plan within the hour.
    """
    line = _line(session)
    service.ingest_counter(
        session,
        line,
        CounterSnapshot(line.carrier_line_reference, 1_000_000_000, NOW),
    )
    service.ingest_counter(
        session,
        line,
        CounterSnapshot(
            line.carrier_line_reference, 1_400_000_000, NOW + timedelta(minutes=5)
        ),
    )
    session.commit()

    allowance = service.allowance(
        session, _entitlement(session, line), now=NOW + timedelta(minutes=6)
    )
    assert allowance.data_bytes_used == 1_400_000_000
    assert allowance.data_bytes_remaining == 3_600_000_000


def test_an_unchanged_counter_writes_no_record(
    session: Session, service: UsageService
) -> None:
    """A poll that finds nothing new is the common case, not an event.

    Writing a zero-quantity row every minute would bury the real records and
    make `occurred_to` say a line was observed when nothing was measured.
    """
    line = _line(session)
    service.ingest_counter(
        session, line, CounterSnapshot(line.carrier_line_reference, 500, NOW)
    )
    second = service.ingest_counter(
        session,
        line,
        CounterSnapshot(
            line.carrier_line_reference, 500, NOW + timedelta(minutes=5)
        ),
    )
    session.commit()
    assert second is None
    assert len(session.exec(select(UsageRecord)).all()) == 1
    # The reading is still kept: the next delta needs a predecessor.
    assert len(session.exec(select(CounterReading)).all()) == 2


def test_a_replayed_counter_poll_produces_no_second_delta(
    session: Session, service: UsageService
) -> None:
    line = _line(session)
    snapshot = CounterSnapshot(line.carrier_line_reference, 900_000, NOW)
    service.ingest_counter(session, line, snapshot)
    again = service.ingest_counter(session, line, snapshot)
    session.commit()
    assert again is None
    assert len(session.exec(select(UsageRecord)).all()) == 1


def test_an_out_of_order_counter_reading_cannot_add_usage_twice(
    session: Session, service: UsageService
) -> None:
    line = _line(session)
    service.ingest_counter(
        session,
        line,
        CounterSnapshot(
            line.carrier_line_reference, 150, NOW + timedelta(minutes=5)
        ),
    )

    stale = service.ingest_counter(
        session,
        line,
        CounterSnapshot(line.carrier_line_reference, 100, NOW),
    )
    session.commit()

    assert stale is None
    balance = service.allowance(session, _entitlement(session, line))
    assert balance.data_bytes_used == 150


def test_a_changed_cycle_counts_the_new_counter_in_full_even_when_it_is_higher(
    session: Session, service: UsageService
) -> None:
    line = _line(session)
    service.ingest_counter(
        session,
        line,
        CounterSnapshot(
            line.carrier_line_reference, 100, NOW, cycle_reference="cycle-1"
        ),
    )
    service.ingest_counter(
        session,
        line,
        CounterSnapshot(
            line.carrier_line_reference,
            200,
            NOW + timedelta(days=30),
            cycle_reference="cycle-2",
        ),
    )
    session.commit()

    balance = service.allowance(session, _entitlement(session, line))
    assert balance.data_bytes_used == 300


def test_a_counter_snapshot_cannot_be_attributed_to_another_line(
    session: Session, service: UsageService
) -> None:
    line = _line(session)
    with pytest.raises(UsageError) as caught:
        service.ingest_counter(
            session,
            line,
            CounterSnapshot("another-line", 100, NOW),
        )
    assert caught.value.code == "provider_line_mismatch"


def test_a_counter_reset_does_not_credit_the_customer(
    session: Session, service: UsageService
) -> None:
    """A decrease is a reset, never negative usage.

    Recording the difference as a negative delta would hand back bytes the
    customer really used. Telnyx exposes no billing-cycle boundary, so the
    conservative reading is the only defensible one — and it raises an exception
    so somebody checks it against supplier billing.
    """
    line = _line(session)
    service.ingest_counter(
        session,
        line,
        CounterSnapshot(line.carrier_line_reference, 2_000_000_000, NOW),
    )
    reset = service.ingest_counter(
        session,
        line,
        CounterSnapshot(
            line.carrier_line_reference, 30_000_000, NOW + timedelta(hours=1)
        ),
    )
    session.commit()

    assert reset is not None
    assert reset.quantity == 30_000_000
    assert reset.source is UsageSource.DERIVED
    assert reset.note is not None and "counter reset" in reset.note

    allowance = service.allowance(
        session, _entitlement(session, line), now=NOW + timedelta(hours=1)
    )
    # Prior consumption stands; the new cycle adds to it. Nothing is credited.
    assert allowance.data_bytes_used == 2_030_000_000

    raised = session.exec(
        select(ExceptionItem).where(
            ExceptionItem.kind == ExceptionKind.USAGE_COUNTER_RESET
        )
    ).all()
    assert len(raised) == 1
    assert "supplier billing" in raised[0].detail


def test_the_first_reading_counts_in_full(
    session: Session, service: UsageService
) -> None:
    """There is no earlier reading to subtract, and the bytes are still ours.

    Starting at zero would give away whatever was consumed before the first
    poll, which for a line enabled minutes before a worker starts is real.
    """
    line = _line(session)
    record = service.ingest_counter(
        session, line, CounterSnapshot(line.carrier_line_reference, 42_000_000, NOW)
    )
    session.commit()
    assert record is not None
    assert record.quantity == 42_000_000
    assert record.occurred_from == line.created_at


# --- events ------------------------------------------------------------------


def test_a_redelivered_event_is_counted_once(
    session: Session, service: UsageService
) -> None:
    """Suppliers redeliver. That has to be harmless, not an incident."""
    line = _line(session)
    event = UsageEvent(
        provider_reference=line.carrier_line_reference,
        kind=UsageKind.DATA,
        quantity=41_000_000,
        started_at=NOW,
        ended_at=NOW + timedelta(minutes=12),
        received_at=NOW + timedelta(minutes=20),
        provider_event_id="wdr-1",
    )
    first = service.ingest_event(session, line, event)
    second = service.ingest_event(session, line, event)
    session.commit()

    assert first.id == second.id
    assert len(session.exec(select(UsageRecord)).all()) == 1


def test_concurrent_event_redelivery_converges_on_one_record(
    engine, session: Session, service: UsageService
) -> None:
    line = _line(session)
    session.commit()
    barrier = Barrier(2)

    def ingest() -> str:
        with Session(engine) as worker:
            worker_line = worker.get(CarrierLine, line.id)
            assert worker_line is not None
            event = UsageEvent(
                provider_reference=worker_line.carrier_line_reference,
                kind=UsageKind.DATA,
                quantity=41,
                started_at=NOW,
                ended_at=NOW + timedelta(minutes=1),
                received_at=NOW + timedelta(minutes=2),
                provider_event_id="wdr-concurrent",
            )
            barrier.wait(timeout=10)
            record = service.ingest_event(worker, worker_line, event)
            worker.commit()
            return str(record.id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = [future.result() for future in [pool.submit(ingest), pool.submit(ingest)]]

    assert len(set(ids)) == 1
    session.rollback()
    assert len(session.exec(select(UsageRecord)).all()) == 1


def test_an_event_cannot_be_attributed_to_another_line(
    session: Session, service: UsageService
) -> None:
    line = _line(session)
    with pytest.raises(UsageError) as caught:
        service.ingest_event(
            session,
            line,
            UsageEvent(
                provider_reference="another-line",
                kind=UsageKind.DATA,
                quantity=1,
                started_at=NOW,
                ended_at=NOW,
                received_at=NOW,
                provider_event_id="wrong-line",
            ),
        )
    assert caught.value.code == "provider_line_mismatch"


def test_an_event_with_no_supplier_id_deduplicates_on_its_documented_fields(
    session: Session, service: UsageService
) -> None:
    """Telnyx publishes no WDR record id, so the key is composed.

    Imperfect, and knowingly so: two genuinely distinct sessions with identical
    boundaries and volume collapse into one. That under-counts, in the
    customer's favour, which is the right direction to be wrong when a supplier
    will not give us an id.
    """
    line = _line(session)
    event = UsageEvent(
        provider_reference=line.carrier_line_reference,
        kind=UsageKind.DATA,
        quantity=1_000,
        started_at=NOW,
        ended_at=NOW + timedelta(seconds=30),
        received_at=NOW + timedelta(minutes=1),
    )
    service.ingest_event(session, line, event)
    service.ingest_event(session, line, event)
    session.commit()
    assert len(session.exec(select(UsageRecord)).all()) == 1
    assert service.natural_key(event).startswith("derived:")


def test_a_late_and_out_of_order_cdr_is_still_counted(
    session: Session, service: UsageService
) -> None:
    """Rejecting a late record is how usage goes missing.

    A watermark is about coverage, not about whether a record is welcome.
    Nothing in ingestion compares an event against one.
    """
    line = _line(session)
    recent = UsageEvent(
        provider_reference=line.carrier_line_reference,
        kind=UsageKind.DATA,
        quantity=500,
        started_at=NOW,
        ended_at=NOW + timedelta(minutes=1),
        received_at=NOW + timedelta(minutes=2),
        provider_event_id="wdr-recent",
    )
    stale = UsageEvent(
        provider_reference=line.carrier_line_reference,
        kind=UsageKind.DATA,
        quantity=700,
        started_at=NOW - timedelta(days=2),
        ended_at=NOW - timedelta(days=2) + timedelta(minutes=3),
        received_at=NOW + timedelta(minutes=10),
        provider_event_id="wdr-stale",
    )
    service.ingest_event(session, line, recent)
    late = service.ingest_event(session, line, stale)
    session.commit()

    assert late.quantity == 700
    allowance = service.allowance(
        session, _entitlement(session, line), now=NOW + timedelta(minutes=3)
    )
    assert allowance.data_bytes_used == 1_200
    # And the allowance's observation time is the newest usage, not the newest
    # arrival: a two-day-old session does not make the balance older.
    assert allowance.observed_at == NOW + timedelta(minutes=1)


def test_a_session_record_is_final_and_a_counter_reading_is_not(
    session: Session, service: UsageService
) -> None:
    """The distinction the assignment asks for, and the one a customer sees."""
    line = _line(session, authoritative="event")
    record = service.ingest_event(
        session,
        line,
        UsageEvent(
            provider_reference=line.carrier_line_reference,
            kind=UsageKind.DATA,
            quantity=10,
            started_at=NOW,
            ended_at=NOW,
            received_at=NOW,
            provider_event_id="wdr-final",
        ),
    )
    session.commit()
    assert record.state is UsageState.FINAL

    other = _line(session)
    provisional = service.ingest_counter(
        session, other, CounterSnapshot(other.carrier_line_reference, 10, NOW)
    )
    session.commit()
    assert provisional is not None
    assert provisional.state is UsageState.PROVISIONAL
    assert service.allowance(session, _entitlement(session, other)).has_provisional


# --- two sources -------------------------------------------------------------


def test_the_same_bytes_from_two_sources_are_counted_once(
    session: Session, service: UsageService
) -> None:
    """`AGENTS.md`: avoid charging the same data via two sources.

    The counter and the session records describe the same megabytes. Summing
    both bills the customer twice for one download.
    """
    line = _line(session, authoritative="counter")
    service.ingest_counter(
        session,
        line,
        CounterSnapshot(line.carrier_line_reference, 100_000_000, NOW),
    )
    evidence = service.ingest_event(
        session,
        line,
        UsageEvent(
            provider_reference=line.carrier_line_reference,
            kind=UsageKind.DATA,
            quantity=100_000_000,
            started_at=NOW - timedelta(minutes=30),
            ended_at=NOW,
            received_at=NOW + timedelta(minutes=5),
            provider_event_id="wdr-same-bytes",
        ),
    )
    session.commit()

    assert evidence.state is UsageState.EVIDENCE
    allowance = service.allowance(session, _entitlement(session, line))
    assert allowance.data_bytes_used == 100_000_000


def test_a_counter_reset_stays_evidence_when_events_are_authoritative(
    session: Session, service: UsageService
) -> None:
    line = _line(session, authoritative="event")
    service.ingest_counter(
        session,
        line,
        CounterSnapshot(line.carrier_line_reference, 100, NOW),
    )
    reset = service.ingest_counter(
        session,
        line,
        CounterSnapshot(
            line.carrier_line_reference,
            10,
            NOW + timedelta(minutes=1),
        ),
    )

    assert reset is not None
    assert reset.source is UsageSource.DERIVED
    assert reset.state is UsageState.EVIDENCE
    assert service.allowance(session, _entitlement(session, line)).data_bytes_used == 0


def test_evidence_from_the_other_source_is_kept_and_compared(
    session: Session, service: UsageService
) -> None:
    """Kept rather than dropped, because it is how a discrepancy is found.

    Nothing is adjusted automatically: which source is right is a conversation
    with the supplier, not an arithmetic default.
    """
    line = _line(session, authoritative="counter")
    service.ingest_counter(
        session, line, CounterSnapshot(line.carrier_line_reference, 90_000_000, NOW)
    )
    service.ingest_event(
        session,
        line,
        UsageEvent(
            provider_reference=line.carrier_line_reference,
            kind=UsageKind.DATA,
            quantity=120_000_000,
            started_at=NOW - timedelta(hours=1),
            ended_at=NOW,
            received_at=NOW,
            provider_event_id="wdr-disagrees",
        ),
    )
    difference = service.compare_sources(session, line)
    session.commit()

    assert difference == -30_000_000
    raised = session.exec(
        select(ExceptionItem).where(
            ExceptionItem.kind == ExceptionKind.USAGE_DISCREPANCY
        )
    ).one()
    assert "90000000" in raised.detail and "120000000" in raised.detail
    # Neither figure was changed.
    allowance = service.allowance(session, _entitlement(session, line))
    assert allowance.data_bytes_used == 90_000_000


def test_voice_is_not_silenced_by_the_data_source_choice(
    session: Session, service: UsageService
) -> None:
    """There is only ever one voice source.

    Forcing voice through the data source's authoritative-source rule would
    make a whole stream evidence-only because a data counter arrived first.
    """
    line = _line(session, authoritative="counter")
    tariff = _tariff(session, line)
    record = service.ingest_event(session, line, _call(line, 90), tariff=tariff)
    session.commit()
    assert record.state is UsageState.FINAL
    assert record.kind is UsageKind.VOICE


# --- the calling amendment ---------------------------------------------------


def test_an_internet_record_cannot_name_a_carrier_line(
    session: Session, service: UsageService
) -> None:
    """`VOICE-EXPANSION.md`: WebRTC CDRs cannot prove native-carrier usage.

    Enforced by a CHECK rather than by a query that remembers to exclude them,
    so an internet record has no line to be summed against in the first place.
    """
    line = _line(session)
    session.add(
        UsageRecord(
            channel=AdapterChannel.INTERNET,
            carrier_line_id=line.id,
            entitlement_id=line.entitlement_id,
            provider="telnyx",
            kind=UsageKind.VOICE,
            source=UsageSource.EVENT,
            state=UsageState.FINAL,
            natural_key=f"internet:{uuid4()}",
            quantity=60,
            occurred_from=NOW,
            occurred_to=NOW + timedelta(seconds=60),
            received_at=NOW,
            created_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_a_carrier_record_must_name_a_line(session: Session) -> None:
    line = _line(session)
    session.add(
        UsageRecord(
            channel=AdapterChannel.CARRIER,
            carrier_line_id=None,
            entitlement_id=line.entitlement_id,
            provider="telnyx",
            kind=UsageKind.DATA,
            source=UsageSource.EVENT,
            state=UsageState.FINAL,
            natural_key=f"carrier:{uuid4()}",
            quantity=10,
            occurred_from=NOW,
            occurred_to=NOW,
            received_at=NOW,
            created_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_an_internet_record_without_a_line_is_accepted(
    session: Session, service: UsageService
) -> None:
    """Internet calling must not require a carrier line foreign key.

    V03 owns internet metering; chunk 16 ingests only the carrier channel. This
    asserts the schema will not force V03 to migrate it.
    """
    line = _line(session)
    session.add(
        UsageRecord(
            channel=AdapterChannel.INTERNET,
            carrier_line_id=None,
            entitlement_id=line.entitlement_id,
            provider="telnyx",
            kind=UsageKind.VOICE,
            source=UsageSource.EVENT,
            state=UsageState.FINAL,
            natural_key=f"internet:{uuid4()}",
            quantity=60,
            occurred_from=NOW,
            occurred_to=NOW + timedelta(seconds=60),
            received_at=NOW,
            created_at=NOW,
        )
    )
    session.flush()
    assert len(session.exec(select(UsageRecord)).all()) == 1


def test_carrier_ingestion_always_records_the_carrier_channel(
    session: Session, service: UsageService
) -> None:
    line = _line(session)
    record = service.ingest_counter(
        session, line, CounterSnapshot(line.carrier_line_reference, 5, NOW)
    )
    session.commit()
    assert record is not None
    assert record.channel is AdapterChannel.CARRIER


# --- pricing -----------------------------------------------------------------


def test_a_call_is_priced_from_the_pinned_tariff_version(
    session: Session, service: UsageService
) -> None:
    """And the pin is what stops a later rate change repricing a past call."""
    line = _line(session)
    tariff = _tariff(session, line)
    record = service.ingest_event(session, line, _call(line, 60), tariff=tariff)
    session.commit()
    assert record.tariff_id == tariff.id
    assert record.charged_currency == "NGN"
    assert record.charged_amount == Decimal("25.00")


def test_billing_increments_round_up_to_the_unit_not_the_money() -> None:
    """A 61-second call on a 60-second increment is two units.

    Computing `61/60 * rate` and rounding the money instead charges for 1.0167
    units — a quiet, systematic undercharge that looks like rounding.
    """
    rate = TariffRate(
        tariff_id=uuid4(),
        origin_kind=OriginKind.CARRIER_VISITED_NETWORK,
        destination_country="NG",
        destination_kind=DestinationKind.MOBILE,
        per_minute_amount=Decimal("25.000000"),
        setup_amount=Decimal("0.00"),
        minimum_seconds=0,
        increment_seconds=60,
    )
    assert price_call(rate, 61, "NGN") == Decimal("50.00")
    assert price_call(rate, 60, "NGN") == Decimal("25.00")
    assert price_call(rate, 1, "NGN") == Decimal("25.00")


def test_a_minimum_duration_and_a_setup_fee_both_apply() -> None:
    rate = TariffRate(
        tariff_id=uuid4(),
        origin_kind=OriginKind.CARRIER_VISITED_NETWORK,
        destination_country="NG",
        destination_kind=DestinationKind.MOBILE,
        per_minute_amount=Decimal("12.000000"),
        setup_amount=Decimal("5.00"),
        minimum_seconds=30,
        increment_seconds=1,
    )
    # A five-second call is billed at the thirty-second minimum, plus setup.
    assert price_call(rate, 5, "NGN") == Decimal("11.00")


def test_a_call_with_no_destination_is_refused_rather_than_priced_at_zero(
    session: Session, service: UsageService
) -> None:
    """A free call is a commercial decision; a missing field is a gap."""
    line = _line(session)
    tariff = _tariff(session, line)
    with pytest.raises(UsageError) as caught:
        service.ingest_event(
            session,
            line,
            _call(line, 30, destination_country=None),
            tariff=tariff,
        )
    assert caught.value.code == "unpriceable_call"


def test_a_missing_rate_is_refused_rather_than_guessed(
    session: Session, service: UsageService
) -> None:
    line = _line(session)
    tariff = _tariff(session, line)
    with pytest.raises(UsageError) as caught:
        service.ingest_event(
            session,
            line,
            _call(line, 30, destination_country="GB"),
            tariff=tariff,
        )
    assert caught.value.code == "rate_not_found"


def test_an_internet_origin_rate_never_prices_a_carrier_call(
    session: Session, service: UsageService
) -> None:
    """Chunk 09's rule, exercised from the usage side.

    A roaming carrier rate is not a substitute for a missing internet rate, and
    the reverse is equally wrong: they describe different calls that cost us
    different amounts.
    """
    line = _line(session)
    entitlement = _entitlement(session, line)
    tariff = Tariff(
        product_id=entitlement.product_id,
        currency="NGN",
        version=1,
        status=PublicationStatus.PUBLISHED,
        effective_from=NOW - timedelta(days=1),
        evidence_reference="fixture",
        verified_at=NOW - timedelta(days=1),
        created_at=NOW,
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
            per_minute_amount=Decimal("9.000000"),
            setup_amount=Decimal("0.00"),
            minimum_seconds=0,
            increment_seconds=60,
        )
    )
    session.flush()
    with pytest.raises(UsageError) as caught:
        service.ingest_event(session, line, _call(line, 60), tariff=tariff)
    assert caught.value.code == "rate_not_found"


# --- corrections -------------------------------------------------------------


def test_a_correction_converges_without_double_counting(
    session: Session, service: UsageService
) -> None:
    """The assignment's own words: converges without double debit.

    The original stops counting and keeps its numbers; the correction carries
    the corrected figure. The balance lands on the corrected value and was never
    the sum of the two.
    """
    line = _line(session)
    original = service.ingest_event(
        session,
        line,
        UsageEvent(
            provider_reference=line.carrier_line_reference,
            kind=UsageKind.DATA,
            quantity=800_000_000,
            started_at=NOW,
            ended_at=NOW + timedelta(minutes=10),
            received_at=NOW,
            provider_event_id="wdr-overstated",
        ),
    )
    session.commit()
    assert (
        service.allowance(session, _entitlement(session, line)).data_bytes_used
        == 800_000_000
    )

    correction = service.apply_correction(
        session, original, 500_000_000, "supplier restated the session"
    )
    session.commit()

    session.refresh(original)
    assert original.state is UsageState.SUPERSEDED
    assert original.quantity == 800_000_000  # history is readable
    assert correction.corrects_id == original.id
    assert (
        service.allowance(session, _entitlement(session, line)).data_bytes_used
        == 500_000_000
    )


def test_correcting_a_superseded_record_is_refused(
    session: Session, service: UsageService
) -> None:
    """Correct the correction, not the thing it replaced."""
    line = _line(session)
    original = service.ingest_event(
        session,
        line,
        UsageEvent(
            provider_reference=line.carrier_line_reference,
            kind=UsageKind.DATA,
            quantity=100,
            started_at=NOW,
            ended_at=NOW,
            received_at=NOW,
            provider_event_id="wdr-c",
        ),
    )
    service.apply_correction(session, original, 50, "restated")
    with pytest.raises(UsageError) as caught:
        service.apply_correction(session, original, 25, "again")
    assert caught.value.code == "already_superseded"


def test_only_a_derived_record_may_claim_to_correct_another(
    session: Session,
) -> None:
    """A supplier feed cannot rewrite history by asserting a `corrects_id`."""
    line = _line(session)
    session.add(
        UsageRecord(
            channel=AdapterChannel.CARRIER,
            carrier_line_id=line.id,
            entitlement_id=line.entitlement_id,
            provider="telnyx",
            kind=UsageKind.DATA,
            source=UsageSource.EVENT,
            state=UsageState.FINAL,
            natural_key=f"forged:{uuid4()}",
            quantity=1,
            occurred_from=NOW,
            occurred_to=NOW,
            received_at=NOW,
            corrects_id=uuid4(),
            created_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_usage_history_rejects_direct_rewrite_and_delete(
    session: Session, service: UsageService
) -> None:
    line = _line(session)
    record = service.ingest_event(
        session,
        line,
        UsageEvent(
            provider_reference=line.carrier_line_reference,
            kind=UsageKind.DATA,
            quantity=10,
            started_at=NOW,
            ended_at=NOW,
            received_at=NOW,
            provider_event_id="immutable",
        ),
    )
    session.commit()

    with pytest.raises(DBAPIError, match="usage history is immutable"):
        session.exec(
            text("UPDATE usage_records SET quantity = 1 WHERE id = :id"),
            params={"id": record.id},
        )
        session.commit()
    session.rollback()

    with pytest.raises(DBAPIError, match="usage history is immutable"):
        session.exec(
            text("DELETE FROM usage_records WHERE id = :id"),
            params={"id": record.id},
        )
        session.commit()
    session.rollback()


def test_a_carrier_record_cannot_name_another_lines_entitlement(
    session: Session,
) -> None:
    first = _line(session)
    second = _line(session)
    session.add(
        UsageRecord(
            channel=AdapterChannel.CARRIER,
            carrier_line_id=first.id,
            entitlement_id=second.entitlement_id,
            provider=first.carrier,
            kind=UsageKind.DATA,
            source=UsageSource.EVENT,
            state=UsageState.FINAL,
            natural_key=f"cross-entitlement:{uuid4()}",
            quantity=1,
            occurred_from=NOW,
            occurred_to=NOW,
            received_at=NOW,
            created_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_a_charged_correction_must_carry_its_revised_amount(
    session: Session, service: UsageService
) -> None:
    line = _line(session)
    tariff = _tariff(session, line)
    original = service.ingest_event(session, line, _call(line, 60), tariff=tariff)

    with pytest.raises(UsageError) as caught:
        service.apply_correction(session, original, 30, "restated")
    assert caught.value.code == "correction_charge_required"


def test_a_correction_posts_only_the_difference(
    session: Session, service: UsageService, ledger: LedgerService
) -> None:
    """A compensating entry, not a reversal and a repost.

    Reversing and re-posting would put two transactions in the books where one
    adjustment happened, and chunk 10's history is immutable anyway.
    """
    line = _line(session)
    tariff = _tariff(session, line)
    entitlement = _entitlement(session, line)
    holder = entitlement.holder_user_id
    assert holder is not None
    credit_account = ledger.account(
        session,
        "NGN",
        AccountKind.SERVICE_CREDIT,
        OwnerKind.USER,
        owner_user_id=holder,
    )
    revenue = ledger.account(session, "NGN", AccountKind.REVENUE)

    original = service.ingest_event(session, line, _call(line, 120), tariff=tariff)
    service.settle_charge(session, original, credit_account, revenue)
    session.commit()
    assert original.charged_amount == Decimal("50.00")

    correction = service.apply_correction(
        session,
        original,
        60,
        "supplier restated the call duration",
        corrected_amount=Decimal("25.00"),
    )
    service.settle_charge(session, correction, credit_account, revenue)
    session.commit()

    entries = session.exec(select(JournalEntry)).all()
    assert len(entries) == 2
    lines = session.exec(
        select(JournalLine).where(JournalLine.entry_id == entries[1].id)
    ).all()
    # 50 was charged, 25 is right, so 25 moves back -- not 25 charged afresh.
    assert {line_.amount for line_ in lines} == {Decimal("25.000000")}


def test_settling_the_same_record_twice_posts_once(
    session: Session, service: UsageService, ledger: LedgerService
) -> None:
    """A replayed worker must not bill a call twice."""
    line = _line(session)
    tariff = _tariff(session, line)
    entitlement = _entitlement(session, line)
    holder = entitlement.holder_user_id
    assert holder is not None
    credit_account = ledger.account(
        session, "NGN", AccountKind.SERVICE_CREDIT, OwnerKind.USER, owner_user_id=holder
    )
    revenue = ledger.account(session, "NGN", AccountKind.REVENUE)
    record = service.ingest_event(session, line, _call(line, 60), tariff=tariff)
    service.settle_charge(session, record, credit_account, revenue)
    service.settle_charge(session, record, credit_account, revenue)
    session.commit()
    assert len(session.exec(select(JournalEntry)).all()) == 1


def test_a_charge_cannot_post_to_accounts_in_another_currency(
    session: Session, service: UsageService, ledger: LedgerService
) -> None:
    line = _line(session)
    tariff = _tariff(session, line)
    record = service.ingest_event(session, line, _call(line, 60), tariff=tariff)
    debit = ledger.account(session, "USD", AccountKind.SERVICE_CREDIT)
    credit = ledger.account(session, "USD", AccountKind.REVENUE)

    with pytest.raises(UsageError) as caught:
        service.settle_charge(session, record, debit, credit)
    assert caught.value.code == "charge_currency_mismatch"


def test_a_charge_cannot_debit_another_customers_account(
    session: Session, service: UsageService, ledger: LedgerService
) -> None:
    line = _line(session)
    other = _line(session)
    tariff = _tariff(session, line)
    record = service.ingest_event(session, line, _call(line, 60), tariff=tariff)
    other_holder = _entitlement(session, other).holder_user_id
    assert other_holder is not None
    debit = ledger.account(
        session,
        "NGN",
        AccountKind.SERVICE_CREDIT,
        OwnerKind.USER,
        owner_user_id=other_holder,
    )
    revenue = ledger.account(session, "NGN", AccountKind.REVENUE)

    with pytest.raises(UsageError) as caught:
        service.settle_charge(session, record, debit, revenue)
    assert caught.value.code == "charge_payer_mismatch"


def test_evidence_is_never_charged(
    session: Session, service: UsageService, ledger: LedgerService
) -> None:
    line = _line(session, authoritative="counter")
    entitlement = _entitlement(session, line)
    holder = entitlement.holder_user_id
    assert holder is not None
    credit_account = ledger.account(
        session, "NGN", AccountKind.SERVICE_CREDIT, OwnerKind.USER, owner_user_id=holder
    )
    revenue = ledger.account(session, "NGN", AccountKind.REVENUE)
    # Insert the already-bad external state in one append. History protection
    # correctly prevents manufacturing it by mutating a stored record.
    record = UsageRecord(
        channel=AdapterChannel.CARRIER,
        carrier_line_id=line.id,
        entitlement_id=entitlement.id,
        provider=line.carrier,
        kind=UsageKind.DATA,
        source=UsageSource.EVENT,
        state=UsageState.EVIDENCE,
        natural_key="wdr-evidence",
        quantity=10,
        occurred_from=NOW,
        occurred_to=NOW,
        received_at=NOW,
        charged_amount=Decimal("5.00"),
        charged_currency="NGN",
        created_at=NOW,
    )
    session.add(record)
    session.flush()
    with pytest.raises(UsageError) as caught:
        service.settle_charge(session, record, credit_account, revenue)
    assert caught.value.code == "evidence_is_not_charged"


# --- cursors -----------------------------------------------------------------


def test_a_watermark_never_moves_backwards(
    session: Session, service: UsageService
) -> None:
    """Nothing ever looks behind a watermark again, so it has to be true."""
    cursor = service.cursor(session, "telnyx", "data_events", NOW)
    service.advance(session, cursor, NOW + timedelta(hours=1))
    session.commit()
    with pytest.raises(UsageError) as caught:
        service.advance(session, cursor, NOW)
    assert caught.value.code == "cursor_would_move_backwards"


def test_a_missed_window_is_backfilled_not_skipped(
    session: Session, service: UsageService, clock: Clock
) -> None:
    """Starting from now would look healthy and lose every byte in the gap."""
    cursor = service.cursor(session, "telnyx", "data_events", NOW)
    clock.advance(hours=30)
    service.check_for_missed_window(session, cursor)
    session.commit()

    assert cursor.state is CursorState.BACKFILLING
    assert cursor.backfill_from == NOW
    assert cursor.backfill_to == clock.value
    # And the live watermark cannot be advanced while catching up.
    with pytest.raises(UsageError) as caught:
        service.advance(session, cursor, clock.value)
    assert caught.value.code == "cursor_backfilling"


def test_closing_a_backfill_moves_the_watermark_to_the_window_end(
    session: Session, service: UsageService, clock: Clock
) -> None:
    """Not to "now": time after the window still has not been covered."""
    cursor = service.cursor(session, "telnyx", "data_events", NOW)
    service.open_backfill(session, cursor, NOW, NOW + timedelta(hours=6))
    clock.advance(hours=12)
    service.close_backfill(session, cursor)
    session.commit()
    assert cursor.state is CursorState.ACTIVE
    assert cursor.position_at == NOW + timedelta(hours=6)
    assert cursor.backfill_from is None


def test_a_poller_that_keeps_failing_stalls_loudly(
    session: Session, service: UsageService
) -> None:
    """A silently stalled usage poller is a balance that stopped moving."""
    cursor = service.cursor(session, "telnyx", "data_counter", NOW)
    for attempt in range(5):
        service.record_failure(session, cursor, f"connection reset ({attempt})")
    session.commit()

    assert cursor.state is CursorState.STALLED
    assert cursor.consecutive_failures == 5
    raised = session.exec(
        select(ExceptionItem).where(
            ExceptionItem.kind == ExceptionKind.USAGE_POLLING_STALLED
        )
    ).one()
    assert "watermark" in raised.detail


def test_a_successful_poll_clears_a_stall(
    session: Session, service: UsageService
) -> None:
    cursor = service.cursor(session, "telnyx", "data_counter", NOW)
    for _ in range(5):
        service.record_failure(session, cursor, "down")
    service.advance(session, cursor, NOW + timedelta(minutes=5))
    session.commit()
    assert cursor.state is CursorState.ACTIVE
    assert cursor.consecutive_failures == 0
    assert cursor.last_error is None


def test_a_backfilling_cursor_must_name_its_window(session: Session) -> None:
    """`ck_usage_cursors_backfill_window`, at the database."""
    from app.usage.models import UsageCursor

    session.add(
        UsageCursor(
            provider="telnyx",
            stream="data_events",
            scope_reference="",
            position_at=NOW,
            state=CursorState.BACKFILLING,
            created_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_one_cursor_per_provider_stream_and_scope(session: Session) -> None:
    from app.usage.models import UsageCursor

    for _ in range(2):
        session.add(
            UsageCursor(
                provider="telnyx",
                stream="data_events",
                scope_reference="",
                position_at=NOW,
                created_at=NOW,
            )
        )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_concurrent_cursor_creation_converges_on_one_row(
    engine, service: UsageService
) -> None:
    barrier = Barrier(2)

    def create() -> str:
        with Session(engine) as worker:
            barrier.wait(timeout=10)
            cursor = service.cursor(worker, "telnyx", "voice_events", NOW)
            worker.commit()
            return str(cursor.id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = [future.result() for future in [pool.submit(create), pool.submit(create)]]

    assert len(set(ids)) == 1


def test_concurrent_cursor_failures_do_not_lose_an_increment(
    engine, session: Session, service: UsageService
) -> None:
    cursor = service.cursor(session, "telnyx", "voice_events", NOW)
    session.commit()
    barrier = Barrier(2)

    def fail() -> None:
        with Session(engine) as worker:
            stale = worker.get(type(cursor), cursor.id)
            assert stale is not None
            barrier.wait(timeout=10)
            service.record_failure(worker, stale, "down")
            worker.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        [future.result() for future in [pool.submit(fail), pool.submit(fail)]]

    session.expire_all()
    current = session.get(type(cursor), cursor.id)
    assert current is not None
    assert current.consecutive_failures == 2


# --- what a balance is worth -------------------------------------------------


def test_an_unpolled_line_reports_unknown_not_full(
    session: Session, service: UsageService
) -> None:
    """"Refreshing an initialized database balance is not reconciliation."

    The grant is all we have. Presenting it as a measurement is exactly what
    AC-36.4 forbids, so the freshness says so.
    """
    line = _line(session)
    allowance = service.allowance(session, _entitlement(session, line))
    assert allowance.freshness is Freshness.UNKNOWN
    assert allowance.is_observed is False
    assert allowance.observed_at is None
    assert allowance.data_bytes_remaining == 5_000_000_000


def test_an_old_reading_reports_stale(
    session: Session, service: UsageService, clock: Clock
) -> None:
    line = _line(session)
    service.ingest_counter(
        session, line, CounterSnapshot(line.carrier_line_reference, 1_000, NOW)
    )
    session.commit()

    assert (
        service.allowance(session, _entitlement(session, line)).freshness
        is Freshness.FRESH
    )
    clock.advance(minutes=30)
    later = service.allowance(session, _entitlement(session, line))
    assert later.freshness is Freshness.STALE
    assert later.observed_at == NOW


def test_an_exhausted_allowance_reports_zero_not_a_negative(
    session: Session, service: UsageService
) -> None:
    """A negative remaining figure reads as a credit in a UI."""
    line = _line(session, data_bytes=1_000)
    service.ingest_counter(
        session, line, CounterSnapshot(line.carrier_line_reference, 5_000, NOW)
    )
    session.commit()
    allowance = service.allowance(session, _entitlement(session, line))
    assert allowance.data_bytes_used == 5_000
    assert allowance.data_bytes_remaining == 0


def test_voice_consumption_reduces_the_right_lines_allowance(
    session: Session, service: UsageService
) -> None:
    """And nobody else's. Two lines, one call, one balance moves."""
    line = _line(session)
    other = _line(session)
    tariff = _tariff(session, line)
    service.ingest_event(session, line, _call(line, 180), tariff=tariff)
    session.commit()

    assert (
        service.allowance(session, _entitlement(session, line)).voice_seconds_used
        == 180
    )
    assert (
        service.allowance(session, _entitlement(session, other)).voice_seconds_used
        == 0
    )


# --- tenancy -----------------------------------------------------------------


def test_usage_does_not_leak_across_tenants(
    session: Session, service: UsageService
) -> None:
    """`AGENTS.md` calls a cross-tenant read a breach, not a bug."""
    organization = Organization(
        org_type=OrganizationType.ENTERPRISE,
        name="Globex",
        primary_contact_name="Contact",
        email=f"globex-{uuid4().hex[:8]}@example.test",
        password_hash="unused",
        phone_number="+2348000000000",
        locale=Locale.EN,
    )
    session.add(organization)
    session.flush()
    consumer_line = _line(session)
    enterprise_line = _line(session, payer_organization=organization)

    for line in (consumer_line, enterprise_line):
        service.ingest_counter(
            session, line, CounterSnapshot(line.carrier_line_reference, 1_000, NOW)
        )
    session.commit()

    consumer_entitlement = _entitlement(session, consumer_line)
    payer_id = session.exec(
        select(Order.payer_user_id)
        .join(OrderItem, Order.id == OrderItem.order_id)  # type: ignore[arg-type]
        .where(OrderItem.id == consumer_entitlement.order_item_id)
    ).one()

    mine = service.records_for_payer(session, user_id=payer_id)
    theirs = service.records_for_payer(session, organization_id=organization.id)

    assert len(mine) == 1
    assert len(theirs) == 1
    assert {record.id for record in mine}.isdisjoint({record.id for record in theirs})


def test_a_scope_that_means_either_tenant_is_refused(
    session: Session, service: UsageService
) -> None:
    """A query meaning "either" returns both tenants' usage."""
    with pytest.raises(UsageError) as caught:
        service.records_for_payer(session)
    assert caught.value.code == "ambiguous_scope"
    with pytest.raises(UsageError):
        service.records_for_payer(session, user_id=uuid4(), organization_id=uuid4())
