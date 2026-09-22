"""Internal operations on real PostgreSQL — US-41, chunk 25.

The assignment names two scenarios and this file builds both: **a paid order
whose supplier outcome is unknown**, and **a payment discrepancy** — each
resolved without duplicate service and without an unbalanced entry.

Around them sit the guards that make an operations surface safe rather than
convenient:

- reconciliation before resolution, refused rather than warned about;
- an immutable audit trail, enforced by a database trigger that no application
  change can talk its way past;
- a replayed resolution that is the same resolution;
- two operators acting at once converging on one decision.

All of it is database behaviour — an advisory lock, a unique constraint, a check
constraint and a trigger — so none of it would be proved by a SQLite run.
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
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app import model_registry  # noqa: F401
from app.auth.models import AdminRole, AdminUser, Locale, Platform, User
from app.catalog.models import LegalEntity, Product, ProductKind
from app.connectivity.models import (
    ActivationState,
    CarrierLine,
    Entitlement,
    NetworkState,
)
from app.fulfilment.models import AttemptOutcome, SupplierAttempt
from app.ledger.models import AccountKind, Direction, JournalLine, OwnerKind
from app.ledger.service import LedgerService
from app.operations.models import (
    OperatorAction,
    OperatorActionKind,
    OperatorSubjectKind,
)
from app.operations.service import OperationsError, OperationsService, mask
from app.orders.models import Order, OrderItem, PaymentState, ProvisioningState
from app.refunds.models import (
    BankFundingStatus,
    BankTransferReceipt,
    ExceptionItem,
    ExceptionKind,
)

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="immutability, replay and concurrency are database guarantees",
)

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
TABLES = (
    "operator_actions, exception_items, carrier_lines, entitlements, "
    "bank_transfer_receipts, "
    "supplier_attempts, order_items, orders, "
    "products, legal_entities, journal_lines, journal_entries, "
    "ledger_reservations, ledger_accounts, admin_users, users"
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
def ledger(clock):
    return LedgerService(clock=clock)


@pytest.fixture
def operations(ledger, clock):
    return OperationsService(ledger, clock=clock)


def _operator(session: Session, label: str = "ops") -> AdminUser:
    admin = AdminUser(
        email=f"{label}-{uuid4().hex[:8]}@example.test",
        password_hash="x",
        locale=Locale.EN,
        role=AdminRole.ADMIN,
    )
    session.add(admin)
    session.flush()
    return admin


def _paid_order_item(
    session: Session, clock: Clock, *, adopted: bool = False
) -> tuple[OrderItem, SupplierAttempt]:
    """A customer who paid, and a supplier that never told us what happened."""
    entity = LegalEntity(code=f"E{uuid4().hex[:6]}", name="Seller", country="NG")
    product = Product(
        sku=f"sku-{uuid4().hex[:8]}", name="Nigeria 5GB", kind=ProductKind.DATA
    )
    payer = User(
        phone_number=f"+23488{uuid4().int % 10**8:08d}",
        first_name="Payer",
        platform=Platform.ANDROID,
    )
    session.add(entity)
    session.add(product)
    session.add(payer)
    session.flush()
    order = Order(
        reference=f"ORD-{uuid4().hex[:8].upper()}",
        seller_legal_entity_id=entity.id,
        payer_user_id=payer.id,
        currency="NGN",
        total_amount=Decimal("5000.00"),
        payment_state=PaymentState.PAID,
        placed_at=NOW,
    )
    session.add(order)
    session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        recipient_user_id=payer.id,
        quantity=1,
        unit_currency="NGN",
        unit_amount=Decimal("5000.00"),
        provisioning_state=ProvisioningState.OUTCOME_UNKNOWN,
    )
    session.add(item)
    session.flush()
    attempt = SupplierAttempt(
        order_item_id=item.id,
        provider="telnyx",
        idempotency_key=f"item:{item.id}:1",
        attempt_number=1,
        outcome=AttemptOutcome.HELD_FOR_REVIEW,
        requested_at=NOW,
        created_at=NOW,
    )
    session.add(attempt)
    session.flush()
    if adopted:
        entitlement = Entitlement(
            order_item_id=item.id,
            holder_user_id=payer.id,
            product_id=product.id,
            data_bytes_total=5_368_709_120,
            voice_seconds_total=0,
            granted_at=NOW,
        )
        session.add(entitlement)
        session.flush()
        session.add(
            CarrierLine(
                entitlement_id=entitlement.id,
                carrier="telnyx",
                carrier_line_reference="SUP-REF-0001",
                activation_state=ActivationState.ACTIVE,
                network_state=NetworkState.ATTACHED,
                provider_status="active",
            )
        )
        session.flush()
    return item, attempt


def _exception(session: Session, clock: Clock, reference: str) -> ExceptionItem:
    item = ExceptionItem(
        kind=ExceptionKind.SETTLEMENT_MISMATCH,
        subject_reference=reference,
        detail="a payment we cannot account for",
        raised_at=NOW,
    )
    session.add(item)
    session.flush()
    return item


class TestReconcileBeforeResolving:
    def test_a_checkbox_cannot_stand_in_for_reconciler_state(
        self, session, operations, clock
    ):
        operator = _operator(session)
        item, attempt = _paid_order_item(session, clock)
        attempt.outcome = AttemptOutcome.OUTCOME_UNKNOWN
        session.add(attempt)
        session.flush()

        with pytest.raises(OperationsError) as excinfo:
            operations.resolve_supplier_attempt(
                session,
                attempt,
                actor=operator,
                succeeded=True,
                reason="operator ticked reconciled without stored evidence",
                idempotency_key="assertion-is-not-evidence",
                reconciled=True,
                provider_reference="SUP-REF-CLAIMED",
            )

        assert excinfo.value.code == "reconciliation_required"
        assert attempt.outcome is AttemptOutcome.OUTCOME_UNKNOWN
        assert item.provisioning_state is ProvisioningState.OUTCOME_UNKNOWN

    def test_an_unreconciled_attempt_cannot_be_resolved(
        self, session, operations, clock
    ):
        """The single most important guard in the chunk.

        Chunk 11's design rests on a lost response being asked about rather than
        guessed at. An operations screen that let a human skip it would
        reintroduce the duplicate purchase that design exists to prevent.
        """
        operator = _operator(session)
        item, attempt = _paid_order_item(session, clock)
        attempt.outcome = AttemptOutcome.OUTCOME_UNKNOWN
        session.add(attempt)
        session.flush()

        with pytest.raises(OperationsError) as excinfo:
            operations.resolve_supplier_attempt(
                session,
                attempt,
                actor=operator,
                succeeded=True,
                reason="customer says it works",
                idempotency_key="key-1",
                reconciled=False,
            )

        assert excinfo.value.code == "reconciliation_required"
        assert attempt.outcome is AttemptOutcome.OUTCOME_UNKNOWN
        assert item.provisioning_state is ProvisioningState.OUTCOME_UNKNOWN

    def test_a_refused_resolution_records_nothing(self, session, operations, clock):
        """A refusal is not a decision, so there is nothing to audit."""
        operator = _operator(session)
        _item, attempt = _paid_order_item(session, clock)
        attempt.outcome = AttemptOutcome.OUTCOME_UNKNOWN
        session.add(attempt)
        session.flush()

        with pytest.raises(OperationsError):
            operations.resolve_supplier_attempt(
                session,
                attempt,
                actor=operator,
                succeeded=True,
                reason="because",
                idempotency_key="key-1",
                reconciled=False,
            )

        assert session.exec(select(OperatorAction)).all() == []

    def test_an_already_settled_attempt_is_not_an_operators_decision(
        self, session, operations, clock
    ):
        operator = _operator(session)
        _item, attempt = _paid_order_item(session, clock)
        attempt.outcome = AttemptOutcome.ACCEPTED
        attempt.provider_reference = "prov-existing"
        session.add(attempt)
        session.flush()

        with pytest.raises(OperationsError) as excinfo:
            operations.resolve_supplier_attempt(
                session,
                attempt,
                actor=operator,
                succeeded=False,
                reason="changed my mind",
                idempotency_key="key-1",
                reconciled=True,
            )
        assert excinfo.value.code == "attempt_already_settled"


class TestThePaidUnknownSupplierCase:
    """The first scenario the assignment names, end to end."""

    def test_a_reference_alone_cannot_claim_that_service_was_provisioned(
        self, session, operations, clock
    ):
        operator = _operator(session)
        item, attempt = _paid_order_item(session, clock)

        with pytest.raises(OperationsError) as excinfo:
            operations.resolve_supplier_attempt(
                session,
                attempt,
                actor=operator,
                succeeded=True,
                reason="supplier reference copied from an email",
                idempotency_key="reference-without-service",
                reconciled=True,
                provider_reference="SUP-REF-0001",
            )

        assert excinfo.value.code == "supplier_success_not_adopted"
        assert item.provisioning_state is ProvisioningState.OUTCOME_UNKNOWN
        assert attempt.outcome is AttemptOutcome.HELD_FOR_REVIEW

    def test_a_reconciled_success_provisions_without_a_second_purchase(
        self, session, operations, clock
    ):
        operator = _operator(session)
        item, attempt = _paid_order_item(session, clock, adopted=True)
        queue_item = _exception(
            session, clock, f"supplier_attempt:{attempt.id}"
        )

        action = operations.resolve_supplier_attempt(
            session,
            attempt,
            actor=operator,
            succeeded=True,
            reason="supplier confirmed the profile against our idempotency key",
            idempotency_key="resolve-1",
            reconciled=True,
            provider_reference="SUP-REF-0001",
            exception_item=queue_item,
        )

        assert attempt.outcome is AttemptOutcome.ACCEPTED
        assert item.provisioning_state is ProvisioningState.PROVISIONED
        # One attempt row, still. Nothing bought a second time.
        assert len(session.exec(select(SupplierAttempt)).all()) == 1
        # The decision is on the record with its before and after.
        assert action.before_state["attempt_outcome"] == "held_for_review"
        assert action.after_state["attempt_outcome"] == "accepted"
        assert queue_item.resolved_at is not None

    def test_a_reconciled_failure_fails_the_line(self, session, operations, clock):
        operator = _operator(session)
        item, attempt = _paid_order_item(session, clock)

        operations.resolve_supplier_attempt(
            session,
            attempt,
            actor=operator,
            succeeded=False,
            reason="supplier has no record of this key",
            idempotency_key="resolve-2",
            reconciled=True,
        )

        assert attempt.outcome is AttemptOutcome.REJECTED
        assert item.provisioning_state is ProvisioningState.FAILED

    def test_a_failure_cannot_overwrite_an_already_adopted_service(
        self, session, operations, clock
    ):
        operator = _operator(session)
        item, attempt = _paid_order_item(session, clock, adopted=True)

        with pytest.raises(OperationsError) as excinfo:
            operations.resolve_supplier_attempt(
                session,
                attempt,
                actor=operator,
                succeeded=False,
                reason="supplier search did not find it",
                idempotency_key="failure-contradicts-local-line",
                reconciled=True,
            )

        assert excinfo.value.code == "supplier_failure_has_adopted_service"
        assert attempt.outcome is AttemptOutcome.HELD_FOR_REVIEW
        assert item.provisioning_state is ProvisioningState.OUTCOME_UNKNOWN

    def test_replaying_a_resolution_is_the_same_resolution(
        self, session, operations, clock
    ):
        """An operator who lost the response and clicked again."""
        operator = _operator(session)
        _item, attempt = _paid_order_item(session, clock, adopted=True)

        first = operations.resolve_supplier_attempt(
            session,
            attempt,
            actor=operator,
            succeeded=True,
            reason="supplier confirmed",
            idempotency_key="same-key",
            reconciled=True,
            provider_reference="SUP-REF-0001",
        )
        second = operations.resolve_supplier_attempt(
            session,
            attempt,
            actor=operator,
            succeeded=True,
            reason="supplier confirmed",
            idempotency_key="same-key",
            reconciled=True,
            provider_reference="SUP-REF-0001",
        )

        assert first.id == second.id
        assert len(session.exec(select(OperatorAction)).all()) == 1

    def test_a_replay_with_different_evidence_is_a_conflict(
        self, session, operations, clock
    ):
        operator = _operator(session)
        _item, attempt = _paid_order_item(session, clock, adopted=True)
        attempt.outcome = AttemptOutcome.HELD_FOR_REVIEW
        session.add(attempt)
        session.flush()

        operations.resolve_supplier_attempt(
            session,
            attempt,
            actor=operator,
            succeeded=True,
            reason="supplier confirmed",
            idempotency_key="same-key-different-evidence",
            reconciled=True,
            provider_reference="SUP-REF-0001",
        )

        with pytest.raises(OperationsError) as excinfo:
            operations.resolve_supplier_attempt(
                session,
                attempt,
                actor=operator,
                succeeded=True,
                reason="supplier confirmed",
                idempotency_key="same-key-different-evidence",
                reconciled=True,
                provider_reference="SUP-REF-0002",
            )
        assert excinfo.value.code == "idempotency_conflict"

    def test_an_action_cannot_close_an_unrelated_exception(
        self, session, operations, clock
    ):
        operator = _operator(session)
        _item, attempt = _paid_order_item(session, clock)
        attempt.outcome = AttemptOutcome.HELD_FOR_REVIEW
        unrelated = _exception(session, clock, "payment:somebody-else")

        with pytest.raises(OperationsError) as excinfo:
            operations.resolve_supplier_attempt(
                session,
                attempt,
                actor=operator,
                succeeded=False,
                reason="supplier found no record",
                idempotency_key="wrong-exception",
                reconciled=True,
                exception_item=unrelated,
            )
        assert excinfo.value.code == "exception_subject_mismatch"
        assert unrelated.resolved_at is None


class TestThePaymentDiscrepancyCase:
    """The second scenario: money settled without an unbalanced entry."""

    def _customer_account(self, session, ledger, currency="NGN"):
        customer = User(
            phone_number=f"+23489{uuid4().int % 10**8:08d}",
            first_name="Customer",
            platform=Platform.ANDROID,
        )
        session.add(customer)
        session.flush()
        credit = ledger.account(
            session,
            currency,
            AccountKind.SERVICE_CREDIT,
            OwnerKind.USER,
            owner_user_id=customer.id,
        )
        return credit

    def _case(self, session, ledger):
        credit = self._customer_account(session, ledger)
        receipt = BankTransferReceipt(
            bank_account_reference="bank-ngn-1",
            statement_reference=f"stmt-{uuid4().hex}",
            currency="NGN",
            amount=Decimal("2500.00"),
            payer_reference="customer reference",
            value_date=NOW,
            status=BankFundingStatus.UNMATCHED,
            imported_at=NOW,
        )
        session.add(receipt)
        session.flush()
        queue_item = ExceptionItem(
            kind=ExceptionKind.UNMATCHED_BANK_TRANSFER,
            subject_reference=f"bank:{receipt.id}",
            detail="a reconciled bank line with no customer match",
            raised_at=NOW,
        )
        session.add(queue_item)
        session.flush()
        return credit, receipt, queue_item

    def test_a_discrepancy_is_settled_by_a_balanced_entry(
        self, session, operations, ledger, clock
    ):
        operator = _operator(session)
        credit, receipt, queue_item = self._case(session, ledger)

        action = operations.resolve_payment_discrepancy(
            session,
            actor=operator,
            customer_account=credit,
            reason="bank transfer matched to the customer by reference",
            idempotency_key="pay-1",
            exception_item=queue_item,
        )

        assert action.ledger_entry_id is not None
        lines = session.exec(
            select(JournalLine).where(JournalLine.entry_id == action.ledger_entry_id)
        ).all()
        debits = sum(
            line.amount for line in lines if line.direction is Direction.DEBIT
        )
        credits = sum(
            line.amount for line in lines if line.direction is Direction.CREDIT
        )
        assert debits == credits == Decimal("2500.00")
        assert ledger.balance(session, credit) == Decimal("2500.00")
        assert receipt.status is BankFundingStatus.MATCHED
        assert queue_item.resolved_at is not None

    def test_replaying_a_discrepancy_does_not_post_twice(
        self, session, operations, ledger, clock
    ):
        """The failure this guard exists for: money moving twice on one click."""
        operator = _operator(session)
        credit, _receipt, queue_item = self._case(session, ledger)

        first = operations.resolve_payment_discrepancy(
            session,
            actor=operator,
            customer_account=credit,
            reason="matched by reference",
            idempotency_key="pay-same",
            exception_item=queue_item,
        )
        second = operations.resolve_payment_discrepancy(
            session,
            actor=operator,
            customer_account=credit,
            reason="matched by reference",
            idempotency_key="pay-same",
            exception_item=queue_item,
        )

        assert first.id == second.id
        assert ledger.balance(session, credit) == Decimal("2500.00")

    def test_cross_currency_compensation_is_refused(
        self, session, operations, ledger, clock
    ):
        """Inventing an FX rate inside an exception queue makes two problems."""
        operator = _operator(session)
        _credit, _receipt, queue_item = self._case(session, ledger)
        usd_credit = self._customer_account(session, ledger, "USD")

        with pytest.raises(OperationsError) as excinfo:
            operations.resolve_payment_discrepancy(
                session,
                actor=operator,
                customer_account=usd_credit,
                reason="close enough",
                idempotency_key="pay-fx",
                exception_item=queue_item,
            )
        assert excinfo.value.code == "cross_currency_compensation"

    def test_an_operator_cannot_choose_an_arbitrary_account_or_amount(
        self, session, operations, ledger, clock
    ):
        operator = _operator(session)
        _credit, receipt, queue_item = self._case(session, ledger)
        arbitrary = ledger.account(session, "NGN", AccountKind.ADJUSTMENT)

        with pytest.raises(OperationsError) as excinfo:
            operations.resolve_payment_discrepancy(
                session,
                actor=operator,
                customer_account=arbitrary,
                reason="move money between accounts",
                idempotency_key="not-a-balance-editor",
                exception_item=queue_item,
            )

        assert excinfo.value.code == "invalid_customer_account"
        assert receipt.status is BankFundingStatus.UNMATCHED

    def test_there_is_no_way_to_set_a_balance(self, session, operations):
        """Asserted as an absence, because that is the requirement.

        The assignment forbids unrestricted balance editing. The service exposes
        no method that writes a balance — money moves only by posting a balanced
        entry, which the ledger itself refuses to accept unbalanced.
        """
        surface = {name for name in dir(operations) if not name.startswith("_")}
        assert not any(
            candidate in surface
            for candidate in ("set_balance", "adjust_balance", "credit", "debit")
        )


class TestTheAuditTrailIsImmutable:
    def test_an_action_cannot_be_updated(self, session, operations, clock):
        """Enforced by trigger. An editable audit trail records only intentions."""
        operator = _operator(session)
        _item, attempt = _paid_order_item(session, clock, adopted=True)
        action = operations.resolve_supplier_attempt(
            session,
            attempt,
            actor=operator,
            succeeded=True,
            reason="supplier confirmed",
            idempotency_key="immutable-1",
            reconciled=True,
            provider_reference="SUP-REF-0001",
        )
        session.commit()

        with pytest.raises(DatabaseError):
            session.exec(
                text("UPDATE operator_actions SET reason = 'something else' "
                     "WHERE id = :id").bindparams(id=str(action.id))
            )
        session.rollback()

    def test_an_action_cannot_be_deleted(self, session, operations, clock):
        operator = _operator(session)
        _item, attempt = _paid_order_item(session, clock, adopted=True)
        action = operations.resolve_supplier_attempt(
            session,
            attempt,
            actor=operator,
            succeeded=True,
            reason="supplier confirmed",
            idempotency_key="immutable-2",
            reconciled=True,
            provider_reference="SUP-REF-0001",
        )
        session.commit()

        with pytest.raises(DatabaseError):
            session.exec(
                text("DELETE FROM operator_actions WHERE id = :id").bindparams(
                    id=str(action.id)
                )
            )
        session.rollback()

    def test_a_blank_reason_is_refused_by_the_database(self, session, clock):
        """Not only by the service: a form can be changed by the next client."""
        operator = _operator(session)
        session.add(
            OperatorAction(
                kind=OperatorActionKind.DISMISS_EXCEPTION,
                subject_kind=OperatorSubjectKind.EXCEPTION_ITEM,
                subject_reference="exception_item:whatever",
                actor_admin_id=operator.id,
                reason="   ",
                idempotency_key="blank",
                before_state={},
                after_state={},
                created_at=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    def test_the_service_refuses_a_blank_reason_with_a_named_error(
        self, session, operations, clock
    ):
        operator = _operator(session)
        queue_item = _exception(session, clock, "payment:whatever")

        with pytest.raises(OperationsError) as excinfo:
            operations.dismiss_exception(
                session,
                queue_item,
                actor=operator,
                reason="  ",
                idempotency_key="blank-2",
            )
        assert excinfo.value.code == "reason_required"
        session.commit()
        session.refresh(queue_item)
        assert queue_item.resolved_at is None
        assert session.exec(select(OperatorAction)).all() == []


class TestConcurrentOperators:
    def test_different_keys_cannot_record_two_decisions_for_one_attempt(
        self, engine, session, clock
    ):
        _item, attempt = _paid_order_item(session, clock, adopted=True)
        operator = _operator(session)
        session.commit()
        attempt_id, operator_id = attempt.id, operator.id
        barrier = Barrier(2)

        def resolve(key: str):
            with Session(engine) as worker:
                service = OperationsService(LedgerService(clock=clock), clock=clock)
                subject = worker.get(SupplierAttempt, attempt_id)
                actor = worker.get(AdminUser, operator_id)
                barrier.wait(timeout=10)
                try:
                    action = service.resolve_supplier_attempt(
                        worker,
                        subject,
                        actor=actor,
                        succeeded=True,
                        reason="supplier confirmed",
                        idempotency_key=key,
                        reconciled=True,
                        provider_reference="SUP-REF-0001",
                    )
                    worker.commit()
                    return str(action.id)
                except OperationsError as error:
                    worker.rollback()
                    return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = {
                future.result(timeout=30)
                for future in (
                    pool.submit(resolve, "decision-a"),
                    pool.submit(resolve, "decision-b"),
                )
            }

        assert "attempt_already_settled" in outcomes
        with Session(engine) as check:
            assert len(check.exec(select(OperatorAction)).all()) == 1

    def test_two_operators_resolving_at_once_produce_one_decision(
        self, engine, session, operations, clock
    ):
        """A busy morning, not an edge case."""
        _item, attempt = _paid_order_item(session, clock, adopted=True)
        operator = _operator(session)
        session.commit()
        attempt_id, operator_id = attempt.id, operator.id
        barrier = Barrier(2)

        def resolve():
            with Session(engine) as worker:
                service = OperationsService(LedgerService(clock=clock), clock=clock)
                subject = worker.get(SupplierAttempt, attempt_id)
                actor = worker.get(AdminUser, operator_id)
                barrier.wait(timeout=10)
                try:
                    action = service.resolve_supplier_attempt(
                        worker,
                        subject,
                        actor=actor,
                        succeeded=True,
                        reason="supplier confirmed",
                        idempotency_key="race-key",
                        reconciled=True,
                        provider_reference="SUP-REF-0001",
                    )
                    worker.commit()
                    return str(action.id)
                except Exception as error:  # noqa: BLE001 - the outcome is the assertion
                    worker.rollback()
                    return getattr(error, "code", "error")

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = [
                future.result(timeout=30)
                for future in (pool.submit(resolve), pool.submit(resolve))
            ]

        with Session(engine) as check:
            actions = check.exec(select(OperatorAction)).all()
        # One decision on the record, whichever way the two threads resolved.
        assert len(actions) == 1
        assert str(actions[0].id) in outcomes or "attempt_already_settled" in outcomes


class TestTheQueue:
    def test_the_queue_is_searchable_by_the_reference_a_customer_quotes(
        self, session, operations, clock
    ):
        _exception(session, clock, "payment:unmatched-77")
        _exception(session, clock, "call:abcdef")

        found = operations.queue(session, reference="payment:")

        assert len(found) == 1
        assert found[0].subject_reference == "payment:unmatched-77"

    def test_a_resolved_item_leaves_the_queue_but_not_the_record(
        self, session, operations, clock
    ):
        """A dismissal is not a delete: an empty queue is not a quiet week."""
        operator = _operator(session)
        queue_item = _exception(session, clock, "payment:unmatched-78")
        queue_item.kind = ExceptionKind.USAGE_DISCREPANCY
        session.add(queue_item)
        session.flush()

        operations.dismiss_exception(
            session,
            queue_item,
            actor=operator,
            reason="duplicate of an earlier report",
            idempotency_key="dismiss-1",
        )

        assert operations.queue(session) == []
        assert len(operations.queue(session, include_resolved=True)) == 1
        assert session.get(ExceptionItem, queue_item.id) is not None

    def test_the_queue_shows_how_often_something_has_been_acted_on(
        self, session, operations, clock
    ):
        operator = _operator(session)
        queue_item = _exception(session, clock, "payment:unmatched-79")
        operations.record_sensitive_access(
            session,
            actor=operator,
            subject_kind=OperatorSubjectKind.PAYMENT,
            subject_reference="payment:unmatched-79",
            reason="checking the bank reference",
            idempotency_key="view-1",
        )

        entry = operations.queue(session)[0]

        assert entry.exception_id == queue_item.id
        assert entry.action_count == 1


class TestSensitiveData:
    def test_looking_is_recorded(self, session, operations, clock):
        """The question after an incident is always "who saw this"."""
        operator = _operator(session)

        operations.record_sensitive_access(
            session,
            actor=operator,
            subject_kind=OperatorSubjectKind.ORDER_ITEM,
            subject_reference="order_item:abc",
            reason="customer called about their number",
            idempotency_key="view-2",
        )

        actions = session.exec(select(OperatorAction)).all()
        assert len(actions) == 1
        assert actions[0].kind is OperatorActionKind.VIEW_SENSITIVE_RECORD
        assert actions[0].actor_admin_id == operator.id

    def test_masking_shows_enough_to_recognise_and_not_enough_to_use(self):
        assert mask("+2348031234567") == "••••••••••4567"
        assert mask("8931060000000000000") == "•••••••••••••••0000"

    def test_a_short_value_is_entirely_masked(self):
        assert mask("123") == "•••"

    def test_masking_leaves_nothing_of_an_empty_value(self):
        assert mask(None) is None
        assert mask("") == ""
