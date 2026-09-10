"""US-33 chunk 12 — payment routing and authoritative capture, on PostgreSQL.

Payments are a strict-TDD category, and every test here is somebody trying to
get an order marked paid without paying for it, or paying for it twice: a forged
webhook, a replayed one, a redirect the customer navigated to themselves, an
amount that does not match, a second successful charge.

The two measures the assignment names: **one business order cannot be credited
or fulfilled twice**, and **excess payment is recorded and resolvable, never
lost**.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app import model_registry  # noqa: F401  -- completes SQLModel.metadata
from app.auth.models import Platform, User
from app.catalog.models import LegalEntity
from app.orders.models import Order, PaymentState
from app.payments.contract import (
    AttemptStatus,
    ExcessPayment,
    MerchantAccount,
    PaymentAttempt,
    PaymentMethodKind,
)
from app.payments.routing import (
    PaymentRouter,
    PaymentRoutingError,
    ProcessorCharge,
    verify_hmac_sha512,
)

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="the one-success index and capture races require PostgreSQL",
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
TABLES = (
    "excess_payments, payment_attempts, payment_intents, merchant_accounts, "
    "order_items, orders, legal_entities, users"
)
SECRET = "whsec_test_only_never_a_real_key"


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
def router():
    return PaymentRouter(clock=Clock())


def _seller(session: Session) -> LegalEntity:
    entity = LegalEntity(code=f"E{uuid4().hex[:6]}", name="Seller", country="NG")
    session.add(entity)
    session.flush()
    return entity


def _merchant(
    session: Session,
    entity: LegalEntity,
    currency: str = "NGN",
    live: bool = True,
    processor: str = "paystack",
) -> MerchantAccount:
    account = MerchantAccount(
        processor=processor,
        legal_entity_id=entity.id,
        currency=currency,
        live_enabled=live,
        approval_reference="D4 fixture approval" if live else None,
        created_at=NOW,
    )
    session.add(account)
    session.flush()
    return account


def _order(
    session: Session,
    entity: LegalEntity,
    amount: str = "5000.00",
    currency: str = "NGN",
) -> Order:
    payer = User(
        phone_number=f"+23487{uuid4().int % 10**8:08d}",
        first_name="payer",
        platform=Platform.ANDROID,
    )
    session.add(payer)
    session.flush()
    order = Order(
        reference=f"ord-{uuid4().hex[:12]}",
        seller_legal_entity_id=entity.id,
        payer_user_id=payer.id,
        currency=currency,
        total_amount=Decimal(amount),
    )
    session.add(order)
    session.flush()
    return order


def _ready(session, router, amount="5000.00"):
    entity = _seller(session)
    merchant = _merchant(session, entity)
    order = _order(session, entity, amount=amount)
    intent = router.create_intent(session, order, merchant, Decimal(amount))
    attempt = router.begin_attempt(
        session, intent, merchant, PaymentMethodKind.CARD
    )
    session.commit()
    return order, intent, attempt, merchant


def _charge(
    attempt, amount="5000.00", currency="NGN", succeeded=True, status="success"
):
    return ProcessorCharge(
        processor_reference=attempt.idempotency_key,
        status=status,
        amount=Decimal(amount),
        currency=currency,
        succeeded=succeeded,
    )


# --- routing -----------------------------------------------------------------


class TestRouting:
    def test_routes_by_seller_and_currency(self, session, router):
        entity = _seller(session)
        ngn = _merchant(session, entity, "NGN")
        _merchant(session, entity, "USD", processor="other")
        session.commit()

        chosen = router.route(session, entity.id, "NGN", PaymentMethodKind.CARD)
        assert chosen.id == ngn.id

    def test_an_unroutable_currency_is_refused(self, session, router):
        entity = _seller(session)
        _merchant(session, entity, "NGN")
        session.commit()
        with pytest.raises(PaymentRoutingError) as excinfo:
            router.route(session, entity.id, "GBP", PaymentMethodKind.CARD)
        assert excinfo.value.code == "no_merchant_account"

    def test_live_collection_is_refused_without_approval(self, session, router):
        """Where D3 and D4 bite. A sandbox that works is not merchant approval."""
        entity = _seller(session)
        _merchant(session, entity, "NGN", live=False)
        session.commit()
        with pytest.raises(PaymentRoutingError) as excinfo:
            router.route(session, entity.id, "NGN", PaymentMethodKind.CARD)
        assert excinfo.value.code == "live_collection_disabled"
        assert "D3/D4" in (excinfo.value.detail or "")

    def test_a_test_mode_route_is_available_explicitly(self, session, router):
        # Sandbox work is possible; it just cannot happen by accident.
        entity = _seller(session)
        _merchant(session, entity, "NGN", live=False)
        session.commit()
        chosen = router.route(
            session, entity.id, "NGN", PaymentMethodKind.CARD, require_live=False
        )
        assert chosen.live_enabled is False

    def test_the_database_refuses_going_live_without_an_approval_reference(
        self, session
    ):
        entity = _seller(session)
        session.add(
            MerchantAccount(
                processor="paystack",
                legal_entity_id=entity.id,
                currency="NGN",
                live_enabled=True,
                approval_reference=None,
                created_at=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


# --- webhook verification ----------------------------------------------------


class TestWebhookVerification:
    def _signature(self, body: bytes) -> str:
        import hashlib
        import hmac

        return hmac.new(SECRET.encode(), body, hashlib.sha512).hexdigest()

    def test_a_valid_signature_verifies(self):
        body = json.dumps({"event": "charge.success"}).encode()
        assert verify_hmac_sha512(SECRET, body, self._signature(body)) is True

    def test_a_forged_signature_is_refused(self):
        body = json.dumps({"event": "charge.success"}).encode()
        assert verify_hmac_sha512(SECRET, body, "0" * 128) is False

    def test_a_tampered_body_is_refused(self):
        # The attack: keep the signature, change the amount.
        original = json.dumps({"amount": 100}).encode()
        signature = self._signature(original)
        tampered = json.dumps({"amount": 1}).encode()
        assert verify_hmac_sha512(SECRET, tampered, signature) is False

    def test_a_missing_signature_is_refused_rather_than_crashing(self):
        body = b"{}"
        assert verify_hmac_sha512(SECRET, body, "") is False

    def test_the_wrong_secret_is_refused(self):
        body = b"{}"
        assert (
            verify_hmac_sha512("another-secret", body, self._signature(body))
            is False
        )


# --- capture -----------------------------------------------------------------


class TestCapture:
    def test_a_matching_charge_marks_the_order_paid(self, session, router):
        order, intent, attempt, _ = _ready(session, router)
        result = router.capture(session, _charge(attempt), "paystack")
        session.commit()

        assert isinstance(result, PaymentAttempt)
        assert result.status is AttemptStatus.SUCCEEDED
        session.refresh(order)
        assert order.payment_state is PaymentState.PAID

    def test_a_wrong_amount_does_not_mark_it_paid(self, session, router):
        order, intent, attempt, _ = _ready(session, router)
        result = router.capture(
            session, _charge(attempt, amount="1.00"), "paystack"
        )
        session.commit()

        assert isinstance(result, ExcessPayment)
        assert "amount" in result.reason
        session.refresh(order)
        assert order.payment_state is PaymentState.UNPAID

    def test_a_wrong_currency_does_not_mark_it_paid(self, session, router):
        order, intent, attempt, _ = _ready(session, router)
        result = router.capture(
            session, _charge(attempt, currency="USD"), "paystack"
        )
        session.commit()
        assert isinstance(result, ExcessPayment)
        session.refresh(order)
        assert order.payment_state is PaymentState.UNPAID

    def test_an_unknown_reference_is_recorded_as_excess_not_dropped(
        self, session, router
    ):
        """Somebody paid something. Dropping it loses their money."""
        _ready(session, router)
        stray = ProcessorCharge(
            processor_reference="chg-nobody-knows",
            status="success",
            amount=Decimal("5000.00"),
            currency="NGN",
            succeeded=True,
        )
        result = router.capture(session, stray, "paystack")
        session.commit()

        assert isinstance(result, ExcessPayment)
        assert result.amount == Decimal("5000.00")
        assert result.resolved_at is None

    def test_a_replayed_webhook_captures_once(self, session, router):
        order, intent, attempt, _ = _ready(session, router)
        first = router.capture(session, _charge(attempt), "paystack")
        session.commit()
        second = router.capture(session, _charge(attempt), "paystack")
        session.commit()

        assert isinstance(first, PaymentAttempt)
        assert isinstance(second, PaymentAttempt)
        assert first.id == second.id
        assert (
            len(
                session.exec(
                    select(PaymentAttempt).where(
                        PaymentAttempt.status == AttemptStatus.SUCCEEDED
                    )
                ).all()
            )
            == 1
        )

    def test_two_successful_attempts_credit_the_order_once(self, session, router):
        """The measure the assignment names.

        A customer whose card attempt succeeded late *and* whose bank transfer
        also landed has paid twice. The order is credited once and the second
        payment is recorded as excess for chunk 14 to refund.
        """
        order, intent, first_attempt, merchant = _ready(session, router)
        router.capture(session, _charge(first_attempt), "paystack")
        session.commit()

        # The customer had also started a bank transfer, which now lands.
        second = PaymentAttempt(
            intent_id=intent.id,
            processor="paystack",
            method=PaymentMethodKind.BANK_TRANSFER,
            idempotency_key=f"intent:{intent.id}:attempt:2",
            currency="NGN",
            amount=Decimal("5000.00"),
            status=AttemptStatus.PENDING,
            created_at=NOW,
        )
        session.add(second)
        session.commit()

        result = router.capture(session, _charge(second), "paystack")
        session.commit()

        assert isinstance(result, ExcessPayment)
        assert "already paid" in result.reason
        # One credit, and the second payment is not lost.
        successes = session.exec(
            select(PaymentAttempt).where(
                PaymentAttempt.status == AttemptStatus.SUCCEEDED
            )
        ).all()
        assert len(successes) == 1
        assert result.amount == Decimal("5000.00")

    def test_the_database_refuses_two_successes_on_one_intent(self, session, router):
        # The partial unique index, not the service.
        order, intent, attempt, _ = _ready(session, router)
        router.capture(session, _charge(attempt), "paystack")
        session.commit()
        session.add(
            PaymentAttempt(
                intent_id=intent.id,
                processor="paystack",
                method=PaymentMethodKind.CARD,
                idempotency_key=f"intent:{intent.id}:attempt:9",
                processor_reference="chg-9",
                currency="NGN",
                amount=Decimal("5000.00"),
                status=AttemptStatus.SUCCEEDED,
                captured_at=NOW,
                created_at=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_a_failed_charge_leaves_the_order_unpaid(self, session, router):
        order, intent, attempt, _ = _ready(session, router)
        router.capture(
            session,
            _charge(attempt, succeeded=False, status="declined"),
            "paystack",
        )
        session.commit()
        session.refresh(order)
        session.refresh(attempt)
        assert attempt.status is AttemptStatus.FAILED
        assert order.payment_state is PaymentState.UNPAID

    def test_a_new_attempt_is_refused_once_one_has_succeeded(self, session, router):
        order, intent, attempt, merchant = _ready(session, router)
        router.capture(session, _charge(attempt), "paystack")
        session.commit()
        with pytest.raises(PaymentRoutingError) as excinfo:
            router.begin_attempt(
                session, intent, merchant, PaymentMethodKind.BANK_TRANSFER
            )
        assert excinfo.value.code == "already_paid"

    def test_concurrent_captures_credit_once(self, engine):
        router = PaymentRouter(clock=Clock())
        with Session(engine) as setup:
            setup.exec(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
            setup.commit()
            order, intent, attempt, _ = _ready(setup, router)
            key = attempt.idempotency_key
            intent_id = intent.id

        barrier = Barrier(2)

        def deliver(_: int) -> str:
            with Session(engine) as scoped:
                scoped_attempt = scoped.exec(
                    select(PaymentAttempt).where(
                        PaymentAttempt.idempotency_key == key
                    )
                ).one()
                barrier.wait(timeout=10)
                try:
                    router.capture(scoped, _charge(scoped_attempt), "paystack")
                    scoped.commit()
                    return "ok"
                except Exception:
                    scoped.rollback()
                    return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(deliver, range(2)))

        with Session(engine) as check:
            successes = check.exec(
                select(PaymentAttempt).where(
                    PaymentAttempt.intent_id == intent_id,
                    PaymentAttempt.status == AttemptStatus.SUCCEEDED,
                )
            ).all()
            assert len(successes) == 1


# --- what a redirect can and cannot do ---------------------------------------


class TestRedirectIsNotEvidence:
    def test_nothing_in_this_module_marks_an_order_paid_from_a_redirect(self):
        """A browser return URL is a message from the customer's own browser.

        Anyone can navigate to a URL. The redirect is a hint to show a spinner,
        never evidence that money moved — so the only path to `PAID` is
        `capture`, which takes a verified `ProcessorCharge`.
        """
        import inspect

        from app.payments import routing

        source = inspect.getsource(routing)
        assert "PaymentState.PAID" in source
        # Exactly one assignment of PAID, inside capture().
        assert source.count("payment_state = PaymentState.PAID") == 1
        capture_source = inspect.getsource(routing.PaymentRouter.capture)
        assert "payment_state = PaymentState.PAID" in capture_source
        # And capture's only input is a ProcessorCharge, which the caller must
        # have verified.
        signature = inspect.signature(routing.PaymentRouter.capture)
        assert "charge" in signature.parameters


# --- reconciliation ----------------------------------------------------------


class FakeAdapter:
    def __init__(self, name: str = "paystack") -> None:
        self.name = name
        self.answer: ProcessorCharge | None = None
        self.knows = True
        self.fetched: list[str] = []

    def fetch_charge(self, processor_reference: str) -> ProcessorCharge | None:
        self.fetched.append(processor_reference)
        return self.answer if self.knows else None


class TestReconciliation:
    def test_an_unknown_charge_is_resolved_against_the_same_processor(
        self, session, router
    ):
        order, intent, attempt, _ = _ready(session, router)
        attempt.status = AttemptStatus.UNKNOWN
        session.add(attempt)
        session.commit()

        adapter = FakeAdapter()
        adapter.answer = _charge(attempt)
        router.reconcile(session, attempt, adapter)
        session.commit()

        session.refresh(attempt)
        session.refresh(order)
        assert attempt.status is AttemptStatus.SUCCEEDED
        assert order.payment_state is PaymentState.PAID
        assert adapter.fetched == [attempt.idempotency_key]

    def test_it_never_reconciles_through_a_different_processor(
        self, session, router
    ):
        """Routing a second charge elsewhere because the first went quiet is
        how a customer pays twice."""
        order, intent, attempt, _ = _ready(session, router)
        attempt.status = AttemptStatus.UNKNOWN
        session.add(attempt)
        session.commit()

        other = FakeAdapter("someone-else")
        with pytest.raises(PaymentRoutingError) as excinfo:
            router.reconcile(session, attempt, other)
        assert excinfo.value.code == "wrong_processor"
        assert other.fetched == []

    def test_an_unanswerable_charge_stays_unknown(self, session, router):
        order, intent, attempt, _ = _ready(session, router)
        adapter = FakeAdapter()
        adapter.knows = False
        router.reconcile(session, attempt, adapter)
        session.commit()

        session.refresh(attempt)
        session.refresh(order)
        assert attempt.status is AttemptStatus.UNKNOWN
        assert order.payment_state is PaymentState.UNPAID
