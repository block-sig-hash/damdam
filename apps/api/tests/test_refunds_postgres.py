"""US-34 chunk 14 — refunds, disputes, bank funding and receipts, on PostgreSQL.

The invariant the whole chunk turns on: **total refunded can never exceed the
refundable charge.** Exceeding it is not a large refund, it is a payout, and a
payout is a different product with a different licensing conversation attached.

The other tests are the ways money goes out wrongly: a refund racing another
refund, a chargeback after the service was consumed, the same bank statement
imported twice, a receipt regenerated from live data.
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

from app import model_registry  # noqa: F401  -- completes SQLModel.metadata
from app.auth.models import Platform, User
from app.catalog.models import LegalEntity
from app.ledger.models import AccountKind, JournalEntry, OwnerKind
from app.ledger.service import LedgerService
from app.orders.models import Order
from app.payments.contract import (
    AttemptStatus,
    ExcessPayment,
    MerchantAccount,
    PaymentAttempt,
    PaymentIntent,
    PaymentMethodKind,
)
from app.refunds.models import (
    BankFundingStatus,
    DisputeState,
    DocumentKind,
    ExceptionItem,
    ExceptionKind,
    FinancialDocument,
    Refund,
    RefundStatus,
)
from app.refunds.service import RefundError, RefundOutcome, RefundService

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="refund headroom races require PostgreSQL",
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
TABLES = (
    "exception_items, financial_documents, bank_transfer_receipts, disputes, "
    "refunds, excess_payments, payment_attempts, payment_intents, "
    "merchant_accounts, journal_lines, journal_entries, ledger_accounts, "
    "orders, legal_entities, users"
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
def ledger():
    return LedgerService(clock=Clock())


@pytest.fixture
def service(ledger):
    return RefundService(ledger, clock=Clock())


def _captured(session: Session, ledger: LedgerService, amount: str = "5000.00"):
    """A customer, a captured charge, and the credit account behind it."""
    entity = LegalEntity(code=f"E{uuid4().hex[:6]}", name="Seller", country="NG")
    session.add(entity)
    session.flush()
    merchant = MerchantAccount(
        processor="paystack",
        legal_entity_id=entity.id,
        currency="NGN",
        live_enabled=True,
        approval_reference="fixture",
        created_at=NOW,
    )
    payer = User(
        phone_number=f"+23488{uuid4().int % 10**8:08d}",
        first_name="payer",
        platform=Platform.ANDROID,
    )
    session.add(merchant)
    session.add(payer)
    session.flush()
    order = Order(
        reference=f"ord-{uuid4().hex[:12]}",
        seller_legal_entity_id=entity.id,
        payer_user_id=payer.id,
        currency="NGN",
        total_amount=Decimal(amount),
    )
    session.add(order)
    session.flush()
    intent = PaymentIntent(
        order_id=order.id,
        seller_legal_entity_id=entity.id,
        merchant_account_id=merchant.id,
        currency="NGN",
        amount=Decimal(amount),
        created_at=NOW,
    )
    session.add(intent)
    session.flush()
    attempt = PaymentAttempt(
        intent_id=intent.id,
        processor="paystack",
        method=PaymentMethodKind.CARD,
        idempotency_key=f"intent:{intent.id}:attempt:1",
        processor_reference=f"chg-{uuid4().hex[:10]}",
        currency="NGN",
        amount=Decimal(amount),
        status=AttemptStatus.SUCCEEDED,
        captured_at=NOW,
        created_at=NOW,
    )
    session.add(attempt)
    credit = ledger.account(
        session, "NGN", AccountKind.SERVICE_CREDIT, OwnerKind.USER, payer.id
    )
    session.commit()
    return attempt, credit, entity


def _success(reference: str | None = None) -> RefundOutcome:
    """A distinct processor reference per refund, as a real processor returns.

    Sharing one across two refunds is refused by
    `ux_refunds_processor_reference`, which is the index doing its job: the same
    payout cannot be recorded twice. The first version of this fixture reused
    one reference and was rightly rejected.
    """
    return RefundOutcome(
        succeeded=True, processor_reference=reference or f"rfnd-{uuid4().hex[:10]}"
    )


# --- the invariant -----------------------------------------------------------


class TestRefundCeiling:
    def test_a_full_refund_is_allowed_once(self, session, service, ledger):
        attempt, credit, _ = _captured(session, ledger)
        refund = service.request_refund(
            session, attempt, Decimal("5000.00"), "customer asked", "refund:1"
        )
        service.record_refund_outcome(session, refund, _success(), credit)
        session.commit()

        session.refresh(refund)
        assert refund.status is RefundStatus.SUCCEEDED
        assert service.refundable_remaining(session, attempt) == Decimal("0.00")

    def test_refunding_more_than_the_charge_is_refused(self, session, service, ledger):
        """Not a large refund -- a payout."""
        attempt, _, _ = _captured(session, ledger)
        with pytest.raises(RefundError) as excinfo:
            service.request_refund(
                session, attempt, Decimal("5000.01"), "oops", "refund:1"
            )
        assert excinfo.value.code == "exceeds_refundable"

    def test_partial_refunds_cannot_exceed_the_charge_in_aggregate(
        self, session, service, ledger
    ):
        attempt, credit, _ = _captured(session, ledger)
        for index, amount in enumerate(["2000.00", "2000.00"]):
            refund = service.request_refund(
                session, attempt, Decimal(amount), "partial", f"refund:{index}"
            )
            service.record_refund_outcome(session, refund, _success(), credit)
            session.commit()

        assert service.refundable_remaining(session, attempt) == Decimal("1000.00")
        with pytest.raises(RefundError) as excinfo:
            service.request_refund(
                session, attempt, Decimal("1000.01"), "too much", "refund:3"
            )
        assert excinfo.value.code == "exceeds_refundable"

    def test_an_in_flight_refund_counts_against_the_headroom(
        self, session, service, ledger
    ):
        """A refund whose outcome we have not seen may already have paid out.

        Excluding it is how a second refund is authorized on top of a first.
        """
        attempt, _, _ = _captured(session, ledger)
        service.request_refund(
            session, attempt, Decimal("5000.00"), "in flight", "refund:1"
        )
        session.commit()
        assert service.refundable_remaining(session, attempt) == Decimal("0.00")
        with pytest.raises(RefundError):
            service.request_refund(
                session, attempt, Decimal("0.01"), "second", "refund:2"
            )

    def test_an_unknown_refund_still_counts(self, session, service, ledger):
        attempt, _, _ = _captured(session, ledger)
        refund = service.request_refund(
            session, attempt, Decimal("5000.00"), "x", "refund:1"
        )
        service.record_refund_unknown(session, refund, "processor timed out")
        session.commit()

        assert service.refundable_remaining(session, attempt) == Decimal("0.00")
        # And it is surfaced rather than silently retried.
        item = session.exec(
            select(ExceptionItem).where(
                ExceptionItem.kind == ExceptionKind.REFUND_UNKNOWN
            )
        ).one()
        assert "do not re-issue" in item.detail

    def test_a_failed_refund_frees_the_headroom_again(self, session, service, ledger):
        attempt, credit, _ = _captured(session, ledger)
        refund = service.request_refund(
            session, attempt, Decimal("5000.00"), "x", "refund:1"
        )
        service.record_refund_outcome(
            session, refund, RefundOutcome(succeeded=False), credit
        )
        session.commit()
        assert service.refundable_remaining(session, attempt) == Decimal("5000.00")

    def test_an_uncaptured_charge_cannot_be_refunded(self, session, service, ledger):
        attempt, _, _ = _captured(session, ledger)
        attempt.status = AttemptStatus.FAILED
        session.add(attempt)
        session.commit()
        with pytest.raises(RefundError) as excinfo:
            service.request_refund(session, attempt, Decimal("1.00"), "x", "refund:1")
        assert excinfo.value.code == "charge_not_refundable"

    def test_concurrent_partial_refunds_cannot_exceed_the_charge(self, engine):
        """Two operators refunding at once, each within the limit alone."""
        ledger = LedgerService(clock=Clock())
        service = RefundService(ledger, clock=Clock())
        with Session(engine) as setup:
            setup.exec(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
            setup.commit()
            attempt, _, _ = _captured(setup, ledger)
            attempt_id = attempt.id

        barrier = Barrier(2)

        def refund(index: int) -> str:
            with Session(engine) as scoped:
                scoped_attempt = scoped.get(PaymentAttempt, attempt_id)
                barrier.wait(timeout=10)
                try:
                    service.request_refund(
                        scoped,
                        scoped_attempt,
                        Decimal("3000.00"),
                        "partial",
                        f"refund:{index}",
                    )
                    scoped.commit()
                    return "ok"
                except RefundError as exc:
                    scoped.rollback()
                    return exc.code
                except Exception:
                    scoped.rollback()
                    return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(refund, range(2)))

        assert outcomes.count("ok") == 1, outcomes
        with Session(engine) as check:
            total = sum(
                refund.amount
                for refund in check.exec(
                    select(Refund).where(Refund.payment_attempt_id == attempt_id)
                ).all()
            )
            assert total <= Decimal("5000.00")

    def test_requesting_the_same_refund_twice_is_one_refund(
        self, session, service, ledger
    ):
        attempt, _, _ = _captured(session, ledger)
        first = service.request_refund(
            session, attempt, Decimal("100.00"), "x", "refund:same"
        )
        session.commit()
        second = service.request_refund(
            session, attempt, Decimal("100.00"), "x", "refund:same"
        )
        session.commit()
        assert first.id == second.id


# --- history is never rewritten ----------------------------------------------


class TestLedgerHistory:
    def test_a_refund_posts_a_new_opposite_entry(self, session, service, ledger):
        attempt, credit, _ = _captured(session, ledger)
        before = len(session.exec(select(JournalEntry)).all())
        refund = service.request_refund(
            session, attempt, Decimal("1000.00"), "x", "refund:1"
        )
        service.record_refund_outcome(session, refund, _success(), credit)
        session.commit()

        entries = session.exec(select(JournalEntry)).all()
        assert len(entries) == before + 1
        assert ledger.trial_balance(session, "NGN")["difference"] == Decimal("0.00")

    def test_an_unsettled_refund_posts_nothing(self, session, service, ledger):
        # A refund that has not settled has not moved money, so posting on
        # request would show a customer credited before their bank saw it.
        attempt, _, _ = _captured(session, ledger)
        before = len(session.exec(select(JournalEntry)).all())
        service.request_refund(session, attempt, Decimal("1000.00"), "x", "refund:1")
        session.commit()
        assert len(session.exec(select(JournalEntry)).all()) == before

    def test_replaying_a_settled_refund_posts_once(self, session, service, ledger):
        attempt, credit, _ = _captured(session, ledger)
        refund = service.request_refund(
            session, attempt, Decimal("1000.00"), "x", "refund:1"
        )
        settled = _success()
        service.record_refund_outcome(session, refund, settled, credit)
        session.commit()
        count = len(session.exec(select(JournalEntry)).all())

        # The same outcome delivered twice: same reference, same event.
        service.record_refund_outcome(session, refund, settled, credit)
        session.commit()
        assert len(session.exec(select(JournalEntry)).all()) == count


# --- disputes ----------------------------------------------------------------


class TestDisputes:
    def test_a_chargeback_is_not_recorded_as_a_refund(self, session, service, ledger):
        """The bank took the money; we are being told, not asked.

        Calling it a refund would make the books say we chose to give it back.
        """
        attempt, _, _ = _captured(session, ledger)
        dispute = service.open_dispute(
            session, attempt, "dsp-1", Decimal("5000.00"), "fraud"
        )
        session.commit()

        assert dispute.state is DisputeState.OPENED
        assert session.exec(select(Refund)).all() == []

    def test_a_dispute_raises_an_exception_item(self, session, service, ledger):
        attempt, _, _ = _captured(session, ledger)
        service.open_dispute(session, attempt, "dsp-1", Decimal("5000.00"))
        session.commit()
        item = session.exec(
            select(ExceptionItem).where(
                ExceptionItem.kind == ExceptionKind.DISPUTE_OPENED
            )
        ).one()
        assert "chargeback" in item.detail

    def test_a_duplicate_dispute_notification_is_one_dispute(
        self, session, service, ledger
    ):
        attempt, _, _ = _captured(session, ledger)
        first = service.open_dispute(session, attempt, "dsp-1", Decimal("100.00"))
        session.commit()
        second = service.open_dispute(session, attempt, "dsp-1", Decimal("100.00"))
        session.commit()
        assert first.id == second.id

    def test_a_lost_dispute_posts_the_loss_without_rewriting_history(
        self, session, service, ledger
    ):
        """A chargeback after the service was consumed is a real loss."""
        attempt, credit, _ = _captured(session, ledger)
        before = len(session.exec(select(JournalEntry)).all())
        dispute = service.open_dispute(session, attempt, "dsp-1", Decimal("5000.00"))
        service.resolve_dispute(session, dispute, won=False, customer_account=credit)
        session.commit()

        session.refresh(dispute)
        assert dispute.state is DisputeState.LOST
        assert len(session.exec(select(JournalEntry)).all()) == before + 1
        assert ledger.trial_balance(session, "NGN")["difference"] == Decimal("0.00")

    def test_a_won_dispute_posts_nothing(self, session, service, ledger):
        # The money never left. Posting a reversal of a reversal would invent
        # two transactions that did not happen.
        attempt, credit, _ = _captured(session, ledger)
        before = len(session.exec(select(JournalEntry)).all())
        dispute = service.open_dispute(session, attempt, "dsp-1", Decimal("5000.00"))
        service.resolve_dispute(session, dispute, won=True, customer_account=credit)
        session.commit()
        assert len(session.exec(select(JournalEntry)).all()) == before

    def test_the_database_refuses_a_resolved_state_without_a_timestamp(
        self, session, service, ledger
    ):
        attempt, _, _ = _captured(session, ledger)
        dispute = service.open_dispute(session, attempt, "dsp-1", Decimal("100.00"))
        session.commit()
        dispute.state = DisputeState.LOST
        session.add(dispute)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


# --- bank funding ------------------------------------------------------------


class TestBankFunding:
    def test_importing_a_statement_twice_credits_nobody_twice(
        self, session, service, ledger
    ):
        """The specific failure a manual funding process produces every time."""
        first = service.import_bank_line(
            session, "acct-1", "stmt-line-9", "NGN", Decimal("2000.00"), NOW
        )
        session.commit()
        second = service.import_bank_line(
            session, "acct-1", "stmt-line-9", "NGN", Decimal("2000.00"), NOW
        )
        session.commit()
        assert first.id == second.id

    def test_the_database_refuses_a_duplicate_statement_line(
        self, session, service, ledger
    ):
        from app.refunds.models import BankTransferReceipt

        service.import_bank_line(
            session, "acct-1", "stmt-line-9", "NGN", Decimal("2000.00"), NOW
        )
        session.commit()
        session.add(
            BankTransferReceipt(
                bank_account_reference="acct-1",
                statement_reference="stmt-line-9",
                currency="NGN",
                amount=Decimal("2000.00"),
                value_date=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_an_import_credits_nothing_by_itself(self, session, service, ledger):
        # Importing evidence and deciding whose money it is are separate acts.
        before = len(session.exec(select(JournalEntry)).all())
        receipt = service.import_bank_line(
            session, "acct-1", "stmt-1", "NGN", Decimal("2000.00"), NOW
        )
        session.commit()
        assert receipt.status is BankFundingStatus.IMPORTED
        assert len(session.exec(select(JournalEntry)).all()) == before

    def test_matching_credits_the_named_account_and_records_who_decided(
        self, session, service, ledger
    ):
        _, credit, _ = _captured(session, ledger)
        receipt = service.import_bank_line(
            session, "acct-1", "stmt-1", "NGN", Decimal("2000.00"), NOW
        )
        service.match_bank_line(session, receipt, credit, "ops:alex")
        session.commit()

        session.refresh(receipt)
        assert receipt.status is BankFundingStatus.MATCHED
        assert receipt.matched_by == "ops:alex"
        assert ledger.balance(session, credit) == Decimal("2000.00")

    def test_the_same_line_cannot_fund_two_accounts(self, session, service, ledger):
        """The assignment names this one outright."""
        _, first, _ = _captured(session, ledger)
        _, second, _ = _captured(session, ledger)
        receipt = service.import_bank_line(
            session, "acct-1", "stmt-1", "NGN", Decimal("2000.00"), NOW
        )
        service.match_bank_line(session, receipt, first, "ops:alex")
        session.commit()

        with pytest.raises(RefundError) as excinfo:
            service.match_bank_line(session, receipt, second, "ops:sam")
        assert excinfo.value.code == "already_matched"
        assert ledger.balance(session, second) == Decimal("0.00")

    def test_it_posts_at_the_value_date_not_the_reconciliation_date(
        self, session, service, ledger
    ):
        _, credit, _ = _captured(session, ledger)
        value_date = NOW - timedelta(days=5)
        receipt = service.import_bank_line(
            session, "acct-1", "stmt-1", "NGN", Decimal("2000.00"), value_date
        )
        service.match_bank_line(session, receipt, credit, "ops:alex")
        session.commit()

        entry = session.exec(
            select(JournalEntry).where(
                JournalEntry.business_event_id == f"bank:{receipt.id}:funding"
            )
        ).one()
        assert entry.occurred_at.replace(tzinfo=timezone.utc) == value_date

    def test_an_unmatched_line_goes_to_the_exception_queue_uncredited(
        self, session, service, ledger
    ):
        # Guessing whose payment it is credits one customer with another's
        # money.
        receipt = service.import_bank_line(
            session, "acct-1", "stmt-1", "NGN", Decimal("2000.00"), NOW
        )
        service.flag_unmatched(session, receipt, "reference 'JOHN' matches nobody")
        session.commit()

        session.refresh(receipt)
        assert receipt.status is BankFundingStatus.UNMATCHED
        assert receipt.matched_ledger_account_id is None
        item = session.exec(
            select(ExceptionItem).where(
                ExceptionItem.kind == ExceptionKind.UNMATCHED_BANK_TRANSFER
            )
        ).one()
        assert "matches nobody" in item.detail

    def test_a_currency_mismatch_is_refused(self, session, service, ledger):
        _, credit, _ = _captured(session, ledger)
        receipt = service.import_bank_line(
            session, "acct-1", "stmt-1", "USD", Decimal("20.00"), NOW
        )
        with pytest.raises(RefundError) as excinfo:
            service.match_bank_line(session, receipt, credit, "ops:alex")
        assert excinfo.value.code == "currency_mismatch"


# --- documents ---------------------------------------------------------------


class TestDocuments:
    def test_a_receipt_freezes_its_facts(self, session, service, ledger):
        """Reprinting last year's receipt must produce last year's numbers."""
        _, _, entity = _captured(session, ledger)
        document = service.issue_document(
            session,
            DocumentKind.RECEIPT,
            "R-0001",
            entity.id,
            "NGN",
            Decimal("5000.00"),
            {"lines": [{"description": "10 GB plan", "amount": "5000.00"}]},
        )
        session.commit()

        session.refresh(document)
        assert document.snapshot["total_amount"] == "5000.00"
        assert document.snapshot["currency"] == "NGN"
        assert document.snapshot["seller_legal_entity_id"] == str(entity.id)
        assert document.snapshot["lines"][0]["amount"] == "5000.00"

    def test_a_document_number_is_unique_per_seller_and_kind(
        self, session, service, ledger
    ):
        # A tax authority asking for invoice 47 must get exactly one document.
        _, _, entity = _captured(session, ledger)
        service.issue_document(
            session,
            DocumentKind.INVOICE,
            "INV-1",
            entity.id,
            "NGN",
            Decimal("1.00"),
            {},
        )
        session.commit()
        session.add(
            FinancialDocument(
                kind=DocumentKind.INVOICE,
                number="INV-1",
                seller_legal_entity_id=entity.id,
                currency="NGN",
                total_amount=Decimal("1.00"),
                snapshot={},
                issued_at=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_the_snapshot_keeps_the_seller_even_if_the_entity_changes_later(
        self, session, service, ledger
    ):
        _, _, entity = _captured(session, ledger)
        document = service.issue_document(
            session,
            DocumentKind.RECEIPT,
            "R-1",
            entity.id,
            "NGN",
            Decimal("100.00"),
            {"seller_name": entity.name},
        )
        session.commit()

        entity.name = "Renamed Entity Ltd"
        session.add(entity)
        session.commit()
        session.refresh(document)
        # The document still names who actually sold it.
        assert document.snapshot["seller_name"] == "Seller"


# --- reconciliation and the exception queue ----------------------------------


class TestReconciliation:
    def test_excess_payments_are_surfaced_for_a_human(self, session, service, ledger):
        """Chunk 12 records them so the money is not lost.

        This is what makes somebody look: an excess payment nobody sees is a
        customer charged twice and never refunded.
        """
        attempt, _, _ = _captured(session, ledger)
        intent = session.get(PaymentIntent, attempt.intent_id)
        session.add(
            ExcessPayment(
                intent_id=intent.id,
                processor="paystack",
                processor_reference="chg-extra",
                currency="NGN",
                amount=Decimal("5000.00"),
                reason="order already paid by another attempt",
                created_at=NOW,
            )
        )
        session.commit()

        raised = service.sweep_excess_payments(session)
        session.commit()
        assert len(raised) == 1
        assert "5000.00" in raised[0].detail

    def test_the_sweep_is_idempotent(self, session, service, ledger):
        attempt, _, _ = _captured(session, ledger)
        intent = session.get(PaymentIntent, attempt.intent_id)
        session.add(
            ExcessPayment(
                intent_id=intent.id,
                processor="paystack",
                processor_reference="chg-extra",
                currency="NGN",
                amount=Decimal("100.00"),
                reason="x",
                created_at=NOW,
            )
        )
        session.commit()
        service.sweep_excess_payments(session)
        session.commit()
        service.sweep_excess_payments(session)
        session.commit()
        assert len(session.exec(select(ExceptionItem)).all()) == 1

    def test_the_settlement_report_reconciles_captures_refunds_and_losses(
        self, session, service, ledger
    ):
        attempt, credit, _ = _captured(session, ledger)
        refund = service.request_refund(
            session, attempt, Decimal("1000.00"), "partial", "refund:1"
        )
        service.record_refund_outcome(session, refund, _success(), credit)
        session.commit()

        report = service.settlement_report(session, "NGN")
        assert report["captured"] == Decimal("5000.00")
        assert report["refunded"] == Decimal("1000.00")
        assert report["disputed_lost"] == Decimal("0.00")
        assert report["net_expected"] == Decimal("4000.00")

    def test_a_lost_dispute_reduces_the_net_expected(self, session, service, ledger):
        attempt, credit, _ = _captured(session, ledger)
        dispute = service.open_dispute(session, attempt, "dsp-1", Decimal("2000.00"))
        service.resolve_dispute(session, dispute, won=False, customer_account=credit)
        session.commit()

        report = service.settlement_report(session, "NGN")
        assert report["disputed_lost"] == Decimal("2000.00")
        assert report["net_expected"] == Decimal("3000.00")

    def test_chargeback_after_the_allowance_was_spent_is_still_recorded(
        self, session, service, ledger
    ):
        """The service is gone and the money went back. Both facts survive."""
        attempt, credit, _ = _captured(session, ledger)
        dispute = service.open_dispute(session, attempt, "dsp-1", Decimal("5000.00"))
        service.resolve_dispute(session, dispute, won=False, customer_account=credit)
        session.commit()

        assert ledger.trial_balance(session, "NGN")["difference"] == Decimal("0.00")
        report = service.settlement_report(session, "NGN")
        assert report["net_expected"] == Decimal("0.00")
