"""US-32 chunk 11 — durable recovery, on real PostgreSQL.

`AGENTS.md` calls the accepted-but-response-lost case the single most expensive
failure mode in this product, so most of this file is that one scenario from
several angles: a supplier that accepts and then times out, a worker killed
after the request, a duplicate delivery, a cancellation racing a fulfilment.

The measure every test applies is the same one the assignment states: **at most
one purchased profile and one accounting effect.**
"""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.models import Platform, User
from app.catalog.models import LegalEntity, Product, ProductKind
from app.fulfilment.models import (
    AttemptOutcome,
    OutboxMessage,
    OutboxStatus,
    SupplierAttempt,
)
from app.fulfilment.service import (
    FulfilmentError,
    FulfilmentService,
    SupplierResult,
    SupplierTimeout,
)
from app.ledger.models import AccountKind, Direction, JournalEntry
from app.ledger.service import LedgerService, Posting
from app.orders.models import Order, OrderItem, ProvisioningState

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="leases, SKIP LOCKED and partial indexes require PostgreSQL",
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
TABLES = (
    "supplier_attempts, outbox_messages, inbox_messages, order_items, orders, "
    "products, legal_entities, users"
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
def clock():
    return Clock()


@pytest.fixture
def service(clock):
    return FulfilmentService(clock=clock)


def _item(session: Session) -> OrderItem:
    entity = LegalEntity(code=f"E{uuid4().hex[:6]}", name="Seller", country="NG")
    product = Product(
        sku=f"sku-{uuid4().hex[:8]}", name="Plan", kind=ProductKind.DATA
    )
    session.add(entity)
    session.add(product)
    session.flush()
    # Chunk 05's ck_orders_exactly_one_payer requires exactly one payer, so
    # the fixture names one. An order with no payer is not a shape this system
    # allows, and it was right to refuse the first version of this fixture.
    payer = User(
        phone_number=f"+23486{uuid4().int % 10**8:08d}",
        first_name="payer",
        platform=Platform.ANDROID,
    )
    session.add(payer)
    session.flush()
    order = Order(
        reference=f"ord-{uuid4().hex[:12]}",
        seller_legal_entity_id=entity.id,
        payer_user_id=payer.id,
        currency="NGN",
        total_amount=Decimal("1000.00"),
    )
    session.add(order)
    session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        unit_currency="NGN",
        unit_amount=Decimal("1000.00"),
    )
    session.add(item)
    session.flush()
    return item


class RecordingSupplier:
    """A supplier that can be made to behave like a real one on a bad day."""

    def __init__(self, name: str = "telnyx") -> None:
        self.name = name
        self.provision_calls: list[str] = []
        self.reconcile_calls: list[str] = []
        self.accepted: set[str] = set()
        self.timeout_after_accepting = False
        self.reconcile_answer: SupplierResult | None = None
        self.reconcile_knows = True

    def provision(self, idempotency_key: str, payload: dict) -> SupplierResult:
        del payload
        self.provision_calls.append(idempotency_key)
        if self.timeout_after_accepting:
            # The expensive case: the supplier accepted and charged us, and we
            # never saw the answer.
            self.accepted.add(idempotency_key)
            raise SupplierTimeout("no response")
        self.accepted.add(idempotency_key)
        return SupplierResult(
            accepted=True, provider_reference=f"prov-{idempotency_key[-8:]}"
        )

    def reconcile(self, idempotency_key: str) -> SupplierResult | None:
        self.reconcile_calls.append(idempotency_key)
        if not self.reconcile_knows:
            return None
        if self.reconcile_answer is not None:
            return self.reconcile_answer
        if idempotency_key in self.accepted:
            return SupplierResult(
                accepted=True, provider_reference=f"prov-{idempotency_key[-8:]}"
            )
        return SupplierResult(accepted=False, rejection_reason="never received")


# --- the expensive case ------------------------------------------------------


class TestLostResponse:
    def test_a_lost_response_is_unknown_not_failed(self, session, service):
        """The distinction the whole chunk turns on.

        Marking this FAILED makes it look retryable, and the retry buys a second
        line the supplier has already sold us.
        """
        item = _item(session)
        supplier = RecordingSupplier()
        supplier.timeout_after_accepting = True
        attempt = service.begin_attempt(session, item, supplier.name)
        session.commit()

        try:
            supplier.provision(attempt.idempotency_key, {})
        except SupplierTimeout as exc:
            service.record_unknown(session, attempt, str(exc))
        session.commit()

        session.refresh(attempt)
        session.refresh(item)
        assert attempt.outcome is AttemptOutcome.OUTCOME_UNKNOWN
        assert item.provisioning_state is ProvisioningState.OUTCOME_UNKNOWN

    def test_reconciliation_finds_the_accepted_purchase_and_buys_nothing(
        self, session, service
    ):
        item = _item(session)
        supplier = RecordingSupplier()
        supplier.timeout_after_accepting = True
        attempt = service.begin_attempt(session, item, supplier.name)
        session.commit()
        try:
            supplier.provision(attempt.idempotency_key, {})
        except SupplierTimeout as exc:
            service.record_unknown(session, attempt, str(exc))
        session.commit()

        service.reconcile(session, attempt, supplier)
        session.commit()

        session.refresh(attempt)
        session.refresh(item)
        assert attempt.outcome is AttemptOutcome.ACCEPTED
        assert item.provisioning_state is ProvisioningState.PROVISIONED
        # One purchase. Exactly the property the assignment names.
        assert len(supplier.provision_calls) == 1
        assert supplier.reconcile_calls == [attempt.idempotency_key]

    def test_reconciliation_uses_the_same_key_we_sent(self, session, service):
        item = _item(session)
        supplier = RecordingSupplier()
        attempt = service.begin_attempt(session, item, supplier.name)
        service.record_unknown(session, attempt, "timeout")
        session.commit()

        service.reconcile(session, attempt, supplier)
        assert supplier.reconcile_calls == [f"order-item:{item.id}:attempt:1"]

    def test_an_unknown_outcome_never_reconciles_against_another_supplier(
        self, session, service
    ):
        """AGENTS.md, verbatim: never fails over to another vendor."""
        item = _item(session)
        original = RecordingSupplier("telnyx")
        attempt = service.begin_attempt(session, item, original.name)
        service.record_unknown(session, attempt, "timeout")
        session.commit()

        other = RecordingSupplier("someone-else")
        with pytest.raises(FulfilmentError) as excinfo:
            service.reconcile(session, attempt, other)
        assert excinfo.value.code == "wrong_supplier"
        assert other.reconcile_calls == []

    def test_an_unanswerable_reconciliation_is_held_for_a_human(
        self, session, service
    ):
        # Guessing costs money one way or leaves a customer without service the
        # other. Neither is this function's decision to make.
        item = _item(session)
        supplier = RecordingSupplier()
        supplier.reconcile_knows = False
        attempt = service.begin_attempt(session, item, supplier.name)
        service.record_unknown(session, attempt, "timeout")
        session.commit()

        service.reconcile(session, attempt, supplier)
        session.commit()
        session.refresh(attempt)
        assert attempt.outcome is AttemptOutcome.HELD_FOR_REVIEW
        assert "operations review" in (attempt.review_reason or "")

    def test_reconciliation_confirming_nothing_landed_frees_the_item(
        self, session, service
    ):
        item = _item(session)
        supplier = RecordingSupplier()
        supplier.reconcile_answer = SupplierResult(
            accepted=False, rejection_reason="never received"
        )
        attempt = service.begin_attempt(session, item, supplier.name)
        service.record_unknown(session, attempt, "timeout")
        session.commit()

        service.reconcile(session, attempt, supplier)
        session.commit()
        session.refresh(item)
        assert item.provisioning_state is ProvisioningState.FAILED

        # And only now may a fresh attempt be made -- as a new attempt, with
        # its own number, not as a retry of the old one.
        second = service.begin_attempt(session, item, supplier.name)
        session.commit()
        assert second.attempt_number == 2
        # A new request, with its own key. Reusing the first key would make the
        # supplier de-duplicate this purchase against the refusal it already
        # gave us, and the order would never be fulfilled.
        assert second.idempotency_key != attempt.idempotency_key


class TestNoDoublePurchase:
    def test_a_second_attempt_while_one_is_live_returns_the_first(
        self, session, service
    ):
        item = _item(session)
        first = service.begin_attempt(session, item, "telnyx")
        session.commit()
        second = service.begin_attempt(session, item, "telnyx")
        session.commit()
        assert first.id == second.id

    def test_the_database_refuses_two_live_attempts_for_one_item(
        self, session, service
    ):
        # The partial unique index, not the service. A second concurrent
        # attempt is not a retry; it is a second purchase.
        item = _item(session)
        service.begin_attempt(session, item, "telnyx")
        session.commit()
        session.add(
            SupplierAttempt(
                order_item_id=item.id,
                provider="telnyx",
                idempotency_key=f"order-item:{item.id}:attempt:2",
                attempt_number=2,
                outcome=AttemptOutcome.IN_FLIGHT,
                requested_at=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_concurrent_workers_produce_one_attempt(self, engine, service):
        with Session(engine) as setup:
            setup.exec(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
            setup.commit()
            item = _item(setup)
            setup.commit()
            item_id = item.id

        barrier = Barrier(2)

        def fulfil(_: int) -> str:
            with Session(engine) as scoped:
                scoped_item = scoped.get(OrderItem, item_id)
                barrier.wait(timeout=10)
                try:
                    service.begin_attempt(scoped, scoped_item, "telnyx")
                    scoped.commit()
                    return "ok"
                except Exception:
                    scoped.rollback()
                    return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(fulfil, range(2)))

        with Session(engine) as check:
            attempts = check.exec(
                select(SupplierAttempt).where(
                    SupplierAttempt.order_item_id == item_id
                )
            ).all()
            assert len(attempts) == 1


# --- outbox and worker recovery ----------------------------------------------


class TestOutbox:
    def test_the_same_work_enqueued_twice_is_one_message(self, session, service):
        item = _item(session)
        key = f"order_item:{item.id}:provision"
        first = service.enqueue(session, "provision", key, {"item": str(item.id)})
        second = service.enqueue(session, "provision", key, {"item": str(item.id)})
        session.commit()
        assert first.id == second.id

    def test_the_database_refuses_a_duplicate_dedupe_key(self, session, service):
        item = _item(session)
        key = f"order_item:{item.id}:provision"
        service.enqueue(session, "provision", key, {})
        session.commit()
        session.add(
            OutboxMessage(
                topic="provision", dedupe_key=key, payload={}, available_at=NOW
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_a_claimed_message_is_not_claimed_twice(self, session, service):
        service.enqueue(session, "provision", "work:1", {})
        session.commit()
        first = service.claim(session, "worker-a")
        session.commit()
        second = service.claim(session, "worker-b")
        session.commit()
        assert first is not None
        assert second is None

    def test_an_expired_lease_makes_the_work_claimable_again(
        self, session, service, clock
    ):
        """How a killed worker's work is recovered.

        Without lease expiry the message is stranded forever and the order
        silently never completes -- which is worse than failing, because
        nothing alerts.
        """
        service.enqueue(session, "provision", "work:1", {})
        session.commit()
        claimed = service.claim(session, "worker-a")
        session.commit()
        assert claimed is not None

        clock.advance(minutes=6)  # the worker died holding the lease
        recovered = service.claim(session, "worker-b")
        session.commit()
        assert recovered is not None
        assert recovered.id == claimed.id
        assert recovered.leased_by == "worker-b"
        assert recovered.attempts == 2

    def test_a_live_lease_is_respected(self, session, service, clock):
        service.enqueue(session, "provision", "work:1", {})
        session.commit()
        service.claim(session, "worker-a")
        session.commit()
        clock.advance(minutes=1)
        assert service.claim(session, "worker-b") is None

    def test_a_failure_backs_off_rather_than_spinning(self, session, service):
        service.enqueue(session, "provision", "work:1", {})
        session.commit()
        message = service.claim(session, "worker-a")
        assert message is not None
        service.fail(session, message, "supplier unavailable")
        session.commit()

        session.refresh(message)
        assert message.status is OutboxStatus.PENDING
        assert message.available_at.replace(tzinfo=timezone.utc) > NOW
        assert message.last_error == "supplier unavailable"

    def test_a_poison_message_is_dead_lettered_not_retried_forever(
        self, session, service, clock
    ):
        service.enqueue(session, "provision", "work:1", {})
        session.commit()
        for _ in range(FulfilmentService.MAX_ATTEMPTS):
            clock.advance(minutes=10)
            message = service.claim(session, "worker-a")
            assert message is not None
            service.fail(session, message, "always fails")
            session.commit()

        session.refresh(message)
        assert message.status is OutboxStatus.DEAD_LETTER
        clock.advance(hours=1)
        assert service.claim(session, "worker-a") is None

    def test_workers_do_not_queue_behind_each_other(self, engine, service):
        # SKIP LOCKED: two workers draining one queue take different rows
        # rather than one waiting on the other.
        with Session(engine) as setup:
            setup.exec(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
            setup.commit()
            service.enqueue(setup, "provision", "work:1", {})
            service.enqueue(setup, "provision", "work:2", {})
            setup.commit()

        barrier = Barrier(2)

        def drain(index: int) -> str | None:
            with Session(engine) as scoped:
                barrier.wait(timeout=10)
                message = service.claim(scoped, f"worker-{index}")
                scoped.commit()
                return message.dedupe_key if message else None

        with ThreadPoolExecutor(max_workers=2) as pool:
            claimed = list(pool.map(drain, range(2)))

        assert sorted(filter(None, claimed)) == ["work:1", "work:2"]

    def test_the_outbox_message_and_its_cause_commit_together(
        self, session, service
    ):
        """The whole reason for an outbox.

        A worker told to do something before the database commits may act on a
        state that then rolls back.
        """
        item = _item(session)
        session.commit()
        before = len(session.exec(select(OutboxMessage)).all())

        try:
            item.provisioning_state = ProvisioningState.REQUESTED
            session.add(item)
            service.enqueue(session, "provision", f"order_item:{item.id}:provision", {})
            raise RuntimeError("something failed before commit")
        except RuntimeError:
            session.rollback()

        session.refresh(item)
        assert item.provisioning_state is ProvisioningState.NOT_STARTED
        assert len(session.exec(select(OutboxMessage)).all()) == before


# --- inbox -------------------------------------------------------------------


class TestInbox:
    def test_a_redelivered_message_is_handled_once(self, session, service):
        assert service.accept_once(session, "telnyx", "evt-1", "provisioned") is True
        session.commit()
        assert service.accept_once(session, "telnyx", "evt-1", "provisioned") is False
        session.commit()

    def test_two_sources_may_share_an_external_id(self, session, service):
        # Providers number their own events; "evt-1" from two of them is two
        # different events.
        assert service.accept_once(session, "telnyx", "evt-1", "x") is True
        assert service.accept_once(session, "paystack", "evt-1", "y") is True
        session.commit()

    def test_concurrent_deliveries_are_handled_once(self, engine, service):
        with Session(engine) as setup:
            setup.exec(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
            setup.commit()

        barrier = Barrier(2)

        def deliver(_: int) -> bool:
            with Session(engine) as scoped:
                barrier.wait(timeout=10)
                try:
                    accepted = service.accept_once(scoped, "telnyx", "evt-9", "x")
                    scoped.commit()
                    return accepted
                except Exception:
                    scoped.rollback()
                    return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(deliver, range(2)))
        assert results.count(True) == 1, results


# --- cancellation ------------------------------------------------------------


class TestCancellation:
    def test_cancelling_while_a_request_is_outstanding_is_refused(
        self, session, service
    ):
        """The cancel-versus-fulfil race.

        The supplier may be about to accept. Marking the item cancelled now
        produces a cancelled order with a purchased line behind it.
        """
        item = _item(session)
        service.begin_attempt(session, item, "telnyx")
        session.commit()

        with pytest.raises(FulfilmentError) as excinfo:
            service.cancel(session, item)
        assert excinfo.value.code == "cancel_conflicts_with_attempt"

    def test_cancelling_an_unstarted_item_drops_its_queued_work(
        self, session, service
    ):
        item = _item(session)
        service.enqueue(session, "provision", f"order_item:{item.id}:provision", {})
        session.commit()

        service.cancel(session, item)
        session.commit()

        session.refresh(item)
        assert item.provisioning_state is ProvisioningState.CANCELLED
        message = session.exec(
            select(OutboxMessage).where(
                OutboxMessage.dedupe_key == f"order_item:{item.id}:provision"
            )
        ).one()
        # So a worker claiming it later does not provision something cancelled.
        assert message.status is OutboxStatus.DONE

    def test_a_provisioned_item_cannot_be_cancelled(self, session, service):
        item = _item(session)
        attempt = service.begin_attempt(session, item, "telnyx")
        service.record_result(
            session, attempt, SupplierResult(accepted=True, provider_reference="p-1")
        )
        session.commit()

        with pytest.raises(FulfilmentError) as excinfo:
            service.cancel(session, item)
        assert excinfo.value.code == "already_provisioned"

    def test_cancellation_is_allowed_once_an_attempt_is_definitively_rejected(
        self, session, service
    ):
        item = _item(session)
        attempt = service.begin_attempt(session, item, "telnyx")
        service.record_result(
            session,
            attempt,
            SupplierResult(accepted=False, rejection_reason="no stock"),
        )
        session.commit()

        service.cancel(session, item)
        session.commit()
        session.refresh(item)
        assert item.provisioning_state is ProvisioningState.CANCELLED


# --- crash and restart -------------------------------------------------------


class TestCrashRecovery:
    """The assignment's own scenario, end to end.

    "Simulate supplier acceptance followed by lost response and process crash,
    then restart workers: at most one purchased profile and one accounting
    effect."

    The crash is simulated by abandoning the session mid-flight and starting a
    fresh one, which is what a killed process leaves behind: a committed attempt
    row, an outbox message under a lease nobody is holding, and no answer.
    """

    def test_a_crash_after_acceptance_produces_one_purchase_and_one_posting(
        self, engine, clock
    ):
        service = FulfilmentService(clock=clock)
        ledger = LedgerService(clock=clock)
        supplier = RecordingSupplier()
        supplier.timeout_after_accepting = True

        with Session(engine) as setup:
            setup.exec(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
            setup.exec(
                text(
                    "TRUNCATE journal_lines, journal_entries, ledger_accounts "
                    "RESTART IDENTITY CASCADE"
                )
            )
            setup.commit()
            item = _item(setup)
            service.enqueue(
                setup, "provision", f"order_item:{item.id}:provision", {}
            )
            setup.commit()
            item_id = item.id

        # --- worker one: claims, records the attempt, calls, and dies --------
        with Session(engine) as worker_one:
            message = service.claim(worker_one, "worker-1")
            assert message is not None
            claimed_item = worker_one.get(OrderItem, item_id)
            attempt = service.begin_attempt(worker_one, claimed_item, supplier.name)
            # Committed *before* the call. This is the ordering the whole
            # design rests on.
            worker_one.commit()
            key = attempt.idempotency_key

            with pytest.raises(SupplierTimeout):
                supplier.provision(key, {})
            # ...and the process dies here. Nothing else is written.

        # --- the lease expires; a new worker picks it up ---------------------
        clock.advance(minutes=6)

        with Session(engine) as worker_two:
            recovered = service.claim(worker_two, "worker-2")
            assert recovered is not None

            live = worker_two.exec(
                select(SupplierAttempt).where(
                    SupplierAttempt.order_item_id == item_id
                )
            ).one()
            # The recovering worker finds an attempt it did not make, still in
            # flight. It must not provision again.
            assert live.outcome is AttemptOutcome.IN_FLIGHT

            service.record_unknown(worker_two, live, "worker restarted mid-flight")
            resolved = service.reconcile(worker_two, live, supplier)

            if resolved.outcome is AttemptOutcome.ACCEPTED:
                credit = ledger.account(
                    worker_two, "NGN", AccountKind.SETTLEMENT_CLEARING
                )
                revenue = ledger.account(worker_two, "NGN", AccountKind.REVENUE)
                ledger.post(
                    worker_two,
                    f"order-item:{item_id}:fulfilled",
                    [
                        Posting(credit, Direction.DEBIT, Decimal("1000.00")),
                        Posting(revenue, Direction.CREDIT, Decimal("1000.00")),
                    ],
                )
            service.complete(worker_two, recovered)
            worker_two.commit()

        # --- the measures the assignment names -------------------------------
        with Session(engine) as check:
            assert len(supplier.provision_calls) == 1, "bought more than once"
            attempts = check.exec(
                select(SupplierAttempt).where(
                    SupplierAttempt.order_item_id == item_id
                )
            ).all()
            assert len(attempts) == 1
            assert attempts[0].outcome is AttemptOutcome.ACCEPTED

            item = check.get(OrderItem, item_id)
            assert item.provisioning_state is ProvisioningState.PROVISIONED

            entries = check.exec(
                select(JournalEntry).where(
                    JournalEntry.business_event_id
                    == f"order-item:{item_id}:fulfilled"
                )
            ).all()
            assert len(entries) == 1, "posted more than one accounting effect"

    def test_replaying_the_whole_recovery_still_posts_once(self, engine, clock):
        """A second recovery pass -- a rerun, a duplicate alert -- adds nothing."""
        service = FulfilmentService(clock=clock)
        ledger = LedgerService(clock=clock)
        supplier = RecordingSupplier()

        with Session(engine) as setup:
            setup.exec(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
            setup.exec(
                text(
                    "TRUNCATE journal_lines, journal_entries, ledger_accounts "
                    "RESTART IDENTITY CASCADE"
                )
            )
            setup.commit()
            item = _item(setup)
            setup.commit()
            item_id = item.id

        for _ in range(2):
            with Session(engine) as scoped:
                scoped_item = scoped.get(OrderItem, item_id)
                attempt = service.begin_attempt(scoped, scoped_item, supplier.name)
                if attempt.outcome is AttemptOutcome.IN_FLIGHT:
                    result = supplier.provision(attempt.idempotency_key, {})
                    service.record_result(scoped, attempt, result)
                credit = ledger.account(
                    scoped, "NGN", AccountKind.SETTLEMENT_CLEARING
                )
                revenue = ledger.account(scoped, "NGN", AccountKind.REVENUE)
                ledger.post(
                    scoped,
                    f"order-item:{item_id}:fulfilled",
                    [
                        Posting(credit, Direction.DEBIT, Decimal("1000.00")),
                        Posting(revenue, Direction.CREDIT, Decimal("1000.00")),
                    ],
                )
                scoped.commit()

        assert len(supplier.provision_calls) == 1
        with Session(engine) as check:
            assert len(check.exec(select(JournalEntry)).all()) == 1
