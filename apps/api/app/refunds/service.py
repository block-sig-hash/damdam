"""Refund, dispute, funding and reconciliation behaviour (US-34, chunk 14).

The invariant this file exists to hold: **total refunded can never exceed the
refundable charge.** Everything else is arrangement around that.

The service computes the remaining refundable amount under a row lock, so two
concurrent partial refunds cannot both see the same headroom. The ledger then
guarantees that every settled refund posting balances; balance alone cannot
enforce a ceiling spanning several refund rows.

Nothing here edits a posted entry. Chunk 10's triggers refuse that outright, and
this module never tries — a refund posts a new, opposite entry with its own
business event, which is also what makes it replay-safe.
"""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlmodel import Session, col, func, select

from app.auth.models import utc_now
from app.ledger.models import (
    AccountKind,
    Direction,
    JournalEntry,
    JournalLine,
    LedgerAccount,
    OwnerKind,
)
from app.ledger.service import LedgerService, Posting
from app.money import round_money
from app.payments.contract import (
    AttemptStatus,
    ExcessPayment,
    PaymentAttempt,
)
from app.refunds.models import (
    BankFundingStatus,
    BankTransferReceipt,
    Dispute,
    DisputeState,
    DocumentKind,
    ExceptionItem,
    ExceptionKind,
    FinancialDocument,
    ProcessorSettlementReport,
    Refund,
    RefundStatus,
)


class RefundError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


@dataclass(frozen=True)
class RefundOutcome:
    succeeded: bool
    processor_reference: str | None = None
    failure_reason: str | None = None


class RefundProcessor(Protocol):
    """What a processor must offer for a refund to be issuable through it."""

    name: str

    def refund(
        self, idempotency_key: str, charge_reference: str, amount: Decimal
    ) -> RefundOutcome: ...

    def fetch_refund(self, idempotency_key: str) -> RefundOutcome | None:
        """What happened to this refund, or `None` if the processor cannot say."""
        ...


class RefundService:
    def __init__(
        self,
        ledger: LedgerService,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.ledger = ledger
        self.clock = clock

    @staticmethod
    def _lock_key(session: Session, key: str) -> None:
        """Serialize a logical idempotency key before its row exists."""
        if session.get_bind().dialect.name == "postgresql":
            session.execute(
                text(
                    "SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"
                ).bindparams(key=key)
            )

    @staticmethod
    def _lock_attempt(session: Session, attempt_id: UUID) -> PaymentAttempt:
        attempt = session.exec(
            select(PaymentAttempt)
            .where(PaymentAttempt.id == attempt_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if attempt is None:
            raise RefundError("payment_attempt_not_found")
        return attempt

    @staticmethod
    def _lock_refund(session: Session, refund_id: UUID) -> Refund:
        refund = session.exec(
            select(Refund)
            .where(Refund.id == refund_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if refund is None:
            raise RefundError("refund_not_found")
        return refund

    @staticmethod
    def _lock_dispute(session: Session, dispute_id: UUID) -> Dispute:
        dispute = session.exec(
            select(Dispute)
            .where(Dispute.id == dispute_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if dispute is None:
            raise RefundError("dispute_not_found")
        return dispute

    @staticmethod
    def _lock_receipt(session: Session, receipt_id: UUID) -> BankTransferReceipt:
        receipt = session.exec(
            select(BankTransferReceipt)
            .where(BankTransferReceipt.id == receipt_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if receipt is None:
            raise RefundError("bank_line_not_found")
        return receipt

    # --- refunds ----------------------------------------------------------

    def refunded_total(self, session: Session, attempt: PaymentAttempt) -> Decimal:
        """Everything already refunded or in flight against this charge.

        In-flight counts. A refund whose outcome we have not seen may already
        have paid out, and excluding it from the headroom is how a second
        refund is authorized on top of a first.
        """
        total = session.exec(
            select(func.sum(Refund.amount)).where(
                Refund.payment_attempt_id == attempt.id,
                col(Refund.status).in_(
                    [
                        RefundStatus.REQUESTED,
                        RefundStatus.PENDING,
                        RefundStatus.SUCCEEDED,
                        RefundStatus.UNKNOWN,
                    ]
                ),
            )
        ).first()
        return round_money(Decimal(total or 0), attempt.currency)

    def refundable_remaining(
        self, session: Session, attempt: PaymentAttempt
    ) -> Decimal:
        if attempt.status is not AttemptStatus.SUCCEEDED:
            return round_money(Decimal(0), attempt.currency)
        return round_money(
            attempt.amount - self.refunded_total(session, attempt), attempt.currency
        )

    def request_refund(
        self,
        session: Session,
        attempt: PaymentAttempt,
        amount: Decimal,
        reason: str,
        business_event_id: str,
        policy_reference: str | None = None,
    ) -> Refund:
        """Reserve headroom and record the intention, under a lock.

        The lock is on the payment attempt, and every path that changes the
        refunded total goes through it — so two concurrent partial refunds
        cannot both read the same remaining amount and both be allowed.
        """
        if not business_event_id.strip():
            raise RefundError("invalid_business_event")
        if not reason.strip():
            raise RefundError("invalid_reason")
        self._lock_key(session, f"refund-event:{business_event_id}")
        locked_attempt = self._lock_attempt(session, attempt.id)
        requested = round_money(amount, locked_attempt.currency)
        existing = session.exec(
            select(Refund).where(Refund.business_event_id == business_event_id)
        ).first()
        if existing is not None:
            if (
                existing.payment_attempt_id != locked_attempt.id
                or existing.amount != requested
                or existing.reason != reason[:500]
                or existing.policy_reference != policy_reference
            ):
                raise RefundError("idempotency_conflict")
            return existing

        if locked_attempt.status is not AttemptStatus.SUCCEEDED:
            raise RefundError(
                "charge_not_refundable",
                "only a captured charge can be refunded",
            )
        if requested <= 0:
            raise RefundError("non_positive_amount")

        remaining = self.refundable_remaining(session, locked_attempt)
        if requested > remaining:
            # Not a large refund -- a payout, which is a different product with
            # a different licensing conversation attached.
            raise RefundError(
                "exceeds_refundable",
                f"{requested} requested against {remaining} remaining",
            )

        refund = Refund(
            business_event_id=business_event_id,
            payment_attempt_id=locked_attempt.id,
            processor=locked_attempt.processor,
            currency=locked_attempt.currency,
            amount=requested,
            status=RefundStatus.REQUESTED,
            reason=reason[:500],
            policy_reference=policy_reference,
            requested_at=self.clock(),
            created_at=self.clock(),
        )
        session.add(refund)
        session.flush()
        return refund

    def record_refund_outcome(
        self,
        session: Session,
        refund: Refund,
        outcome: RefundOutcome,
    ) -> Refund:
        """Post the reversal only when the processor confirms it.

        A refund that has not settled has not moved money, so posting on
        request would show a customer credited before their bank saw anything.
        """
        current = self._lock_refund(session, refund.id)
        # Refund status changes alter headroom, so they serialize with new
        # refund requests on the same captured attempt.
        self._lock_attempt(session, current.payment_attempt_id)
        now = self.clock()
        processor_reference = (
            outcome.processor_reference.strip()
            if outcome.processor_reference is not None
            else None
        )
        if current.status is RefundStatus.SUCCEEDED:
            if outcome.succeeded and current.processor_reference == processor_reference:
                return current
            raise RefundError("refund_already_resolved")
        if current.status is RefundStatus.FAILED:
            if not outcome.succeeded:
                return current
            raise RefundError("refund_already_resolved")
        if not outcome.succeeded:
            current.status = RefundStatus.FAILED
            session.add(current)
            self._resolve_exception(
                session,
                ExceptionKind.REFUND_UNKNOWN,
                f"refund:{current.id}",
                outcome.failure_reason or "processor confirmed refund failure",
            )
            session.flush()
            return current

        if not processor_reference:
            raise RefundError("missing_processor_reference")
        current.status = RefundStatus.SUCCEEDED
        current.processor_reference = processor_reference
        current.settled_at = now
        session.add(current)

        clearing = self.ledger.account(
            session, current.currency, AccountKind.SETTLEMENT_CLEARING
        )
        revenue = self.ledger.account(session, current.currency, AccountKind.REVENUE)
        # A new, opposite entry -- never an edit. Chunk 10's trigger refuses an
        # edit anyway; this is the shape that makes the history readable.
        self.ledger.post(
            session,
            f"{current.business_event_id}:posted",
            [
                Posting(revenue, Direction.DEBIT, current.amount),
                Posting(clearing, Direction.CREDIT, current.amount),
            ],
            occurred_at=now,
            reference=(
                f"refund {current.id} against attempt {current.payment_attempt_id}"
            ),
        )
        self._resolve_exception(
            session,
            ExceptionKind.REFUND_UNKNOWN,
            f"refund:{current.id}",
            "processor confirmed refund success",
        )
        session.flush()
        return current

    def record_refund_unknown(
        self, session: Session, refund: Refund, reason: str
    ) -> Refund:
        """A refund whose outcome we did not see. Never retried blindly.

        The processor may already have sent the money, and a second refund is a
        second payout. It stays counted against the headroom and goes to the
        exception queue.
        """
        current = self._lock_refund(session, refund.id)
        if current.status in (RefundStatus.SUCCEEDED, RefundStatus.FAILED):
            raise RefundError("refund_already_resolved")
        current.status = RefundStatus.UNKNOWN
        session.add(current)
        self.raise_exception(
            session,
            ExceptionKind.REFUND_UNKNOWN,
            f"refund:{current.id}",
            f"{reason[:400]}; do not re-issue -- reconcile against "
            f"{current.business_event_id}",
        )
        session.flush()
        return current

    def reconcile_refund(
        self,
        session: Session,
        refund: Refund,
        processor: RefundProcessor,
    ) -> Refund:
        current = self._lock_refund(session, refund.id)
        if processor.name != current.processor:
            raise RefundError("wrong_processor")
        if current.status in (RefundStatus.SUCCEEDED, RefundStatus.FAILED):
            return current
        outcome = processor.fetch_refund(current.business_event_id)
        if outcome is None:
            return current  # still unknown; the exception item stands
        return self.record_refund_outcome(session, current, outcome)

    # --- disputes ---------------------------------------------------------

    def open_dispute(
        self,
        session: Session,
        attempt: PaymentAttempt,
        processor_reference: str,
        amount: Decimal,
        reason_code: str | None = None,
    ) -> Dispute:
        """Record a chargeback. Never as a refund.

        The bank has already taken the money; we are being told, not asked. A
        dispute lost after the service was consumed is a real loss, and calling
        it a refund would make the books say we chose to give the money back.
        """
        if not processor_reference.strip():
            raise RefundError("invalid_processor_reference")
        self._lock_key(session, f"dispute:{attempt.processor}:{processor_reference}")
        locked_attempt = self._lock_attempt(session, attempt.id)
        disputed = round_money(amount, locked_attempt.currency)
        if locked_attempt.status is not AttemptStatus.SUCCEEDED:
            raise RefundError("charge_not_disputable")
        if disputed <= 0:
            raise RefundError("non_positive_amount")
        existing = session.exec(
            select(Dispute).where(
                Dispute.processor == locked_attempt.processor,
                Dispute.processor_reference == processor_reference,
            )
        ).first()
        if existing is not None:
            if (
                existing.payment_attempt_id != locked_attempt.id
                or existing.amount != disputed
                or existing.reason_code != reason_code
            ):
                raise RefundError("idempotency_conflict")
            return existing

        already_disputed = Decimal(
            session.exec(
                select(func.sum(Dispute.amount)).where(
                    Dispute.payment_attempt_id == locked_attempt.id,
                    Dispute.state != DisputeState.WON,
                )
            ).first()
            or 0
        )
        if disputed + already_disputed > locked_attempt.amount:
            raise RefundError("exceeds_disputable")

        dispute = Dispute(
            payment_attempt_id=locked_attempt.id,
            processor=locked_attempt.processor,
            processor_reference=processor_reference,
            currency=locked_attempt.currency,
            amount=disputed,
            state=DisputeState.OPENED,
            reason_code=reason_code,
            opened_at=self.clock(),
        )
        session.add(dispute)
        self.raise_exception(
            session,
            ExceptionKind.DISPUTE_OPENED,
            f"dispute:{dispute.id}",
            f"chargeback of {dispute.amount} {dispute.currency} on "
            f"{processor_reference}",
        )
        session.flush()
        return dispute

    def resolve_dispute(
        self,
        session: Session,
        dispute: Dispute,
        won: bool,
    ) -> Dispute:
        """A lost dispute posts the loss. A won one posts nothing.

        Won means the money never left after all — there was nothing to record
        in the first place, and posting a reversal of a reversal would invent
        two transactions that did not happen.
        """
        current = self._lock_dispute(session, dispute.id)
        desired = DisputeState.WON if won else DisputeState.LOST
        if current.state in (DisputeState.WON, DisputeState.LOST):
            if current.state is desired:
                return current
            raise RefundError("dispute_already_resolved")
        now = self.clock()
        current.state = desired
        current.resolved_at = now
        session.add(current)

        # Charged to adjustment rather than to the customer: the customer did
        # not ask for this and may still hold the service. Whether the allowance
        # is clawed back is a policy question (D5) this module does not decide.
        if not won:
            clearing = self.ledger.account(
                session, current.currency, AccountKind.SETTLEMENT_CLEARING
            )
            adjustment = self.ledger.account(
                session, current.currency, AccountKind.ADJUSTMENT
            )
            self.ledger.post(
                session,
                f"dispute:{current.id}:lost",
                [
                    Posting(adjustment, Direction.DEBIT, current.amount),
                    Posting(clearing, Direction.CREDIT, current.amount),
                ],
                occurred_at=now,
                reference=f"chargeback lost on {current.processor_reference}",
            )
        self._resolve_exception(
            session,
            ExceptionKind.DISPUTE_OPENED,
            f"dispute:{current.id}",
            "dispute won" if won else "dispute lost",
        )
        session.flush()
        return current

    # --- bank funding -----------------------------------------------------

    def import_bank_line(
        self,
        session: Session,
        bank_account_reference: str,
        statement_reference: str,
        currency: str,
        amount: Decimal,
        value_date: datetime,
        payer_reference: str | None = None,
    ) -> BankTransferReceipt:
        """Import one statement line. Re-importing a statement is harmless.

        Nothing is credited here. Importing evidence and deciding whose money it
        is are separate acts, and collapsing them is how a fuzzy reference match
        funds the wrong account.
        """
        bank_account_reference = bank_account_reference.strip()
        statement_reference = statement_reference.strip()
        if not bank_account_reference or not statement_reference:
            raise RefundError("invalid_statement_identity")
        imported_amount = round_money(amount, currency)
        if imported_amount <= 0:
            raise RefundError("non_positive_amount")
        self._lock_key(
            session, f"bank-line:{bank_account_reference}:{statement_reference}"
        )
        existing = session.exec(
            select(BankTransferReceipt).where(
                BankTransferReceipt.bank_account_reference == bank_account_reference,
                BankTransferReceipt.statement_reference == statement_reference,
            )
        ).first()
        if existing is not None:
            if (
                existing.currency != currency
                or existing.amount != imported_amount
                or existing.value_date != value_date
                or existing.payer_reference != payer_reference
            ):
                raise RefundError("idempotency_conflict")
            return existing

        receipt = BankTransferReceipt(
            bank_account_reference=bank_account_reference,
            statement_reference=statement_reference,
            currency=currency,
            amount=imported_amount,
            payer_reference=payer_reference,
            value_date=value_date,
            status=BankFundingStatus.IMPORTED,
            imported_at=self.clock(),
        )
        session.add(receipt)
        session.flush()
        return receipt

    def match_bank_line(
        self,
        session: Session,
        receipt: BankTransferReceipt,
        account: LedgerAccount,
        matched_by: str,
    ) -> BankTransferReceipt:
        """Credit a customer from a reconciled line, once.

        `matched_by` names who decided. A funding credit with no attributable
        decision is indistinguishable from an unaudited balance edit, which is
        exactly what the assignment forbids.
        """
        current = self._lock_receipt(session, receipt.id)
        actor = matched_by.strip()
        if not actor:
            raise RefundError("missing_matched_by")
        if current.status is BankFundingStatus.MATCHED:
            if (
                current.matched_ledger_account_id == account.id
                and current.matched_by == actor
            ):
                return current
            raise RefundError("already_matched")
        if (
            account.kind is not AccountKind.SERVICE_CREDIT
            or account.owner_kind is OwnerKind.SYSTEM
        ):
            raise RefundError("invalid_customer_account")
        if account.currency != current.currency:
            raise RefundError("currency_mismatch")

        now = self.clock()
        clearing = self.ledger.account(
            session, current.currency, AccountKind.SETTLEMENT_CLEARING
        )
        self.ledger.post(
            session,
            f"bank:{current.id}:funding",
            [
                Posting(clearing, Direction.DEBIT, current.amount),
                Posting(account, Direction.CREDIT, current.amount),
            ],
            # The date the bank says the money arrived, not the date somebody
            # got round to reconciling it.
            occurred_at=current.value_date,
            reference=f"bank transfer {current.statement_reference}",
        )
        current.status = BankFundingStatus.MATCHED
        current.matched_ledger_account_id = account.id
        current.matched_by = actor
        current.matched_at = now
        session.add(current)
        session.flush()
        return current

    def flag_unmatched(
        self, session: Session, receipt: BankTransferReceipt, detail: str
    ) -> BankTransferReceipt:
        current = self._lock_receipt(session, receipt.id)
        if current.status is BankFundingStatus.MATCHED:
            raise RefundError("already_matched")
        current.status = BankFundingStatus.UNMATCHED
        session.add(current)
        self.raise_exception(
            session,
            ExceptionKind.UNMATCHED_BANK_TRANSFER,
            f"bank:{current.id}",
            detail[:1000],
        )
        session.flush()
        return current

    # --- documents --------------------------------------------------------

    def issue_document(
        self,
        session: Session,
        kind: DocumentKind,
        number: str,
        seller_legal_entity_id: UUID,
        currency: str,
        total_amount: Decimal,
        snapshot: dict[str, Any],
        order_id: UUID | None = None,
    ) -> FinancialDocument:
        """Freeze the facts. A document is generated once and never recomputed.

        Regenerating from live data next year would show next year's prices with
        this year's date, and a customer comparing it against their bank
        statement would be right to complain.
        """
        number = number.strip()
        if not number:
            raise RefundError("invalid_document_number")
        rounded_total = round_money(total_amount, currency)
        if rounded_total < 0:
            raise RefundError("negative_document_total")
        now = self.clock()
        frozen_snapshot = deepcopy(snapshot)
        document = FinancialDocument(
            kind=kind,
            number=number,
            seller_legal_entity_id=seller_legal_entity_id,
            order_id=order_id,
            currency=currency,
            total_amount=rounded_total,
            snapshot={
                **frozen_snapshot,
                "currency": currency,
                "total_amount": str(rounded_total),
                "seller_legal_entity_id": str(seller_legal_entity_id),
                "issued_at": now.isoformat(),
            },
            issued_at=now,
            created_at=now,
        )
        session.add(document)
        session.flush()
        return document

    # --- exceptions and reconciliation ------------------------------------

    def raise_exception(
        self,
        session: Session,
        kind: ExceptionKind,
        subject_reference: str,
        detail: str,
    ) -> ExceptionItem:
        self._lock_key(session, f"exception:{kind.value}:{subject_reference}")
        existing = session.exec(
            select(ExceptionItem).where(
                ExceptionItem.kind == kind,
                ExceptionItem.subject_reference == subject_reference,
            )
        ).first()
        if existing is not None:
            normalized_detail = detail[:1000]
            if existing.resolved_at is not None:
                existing.resolved_at = None
                existing.resolution = None
                existing.raised_at = self.clock()
            existing.detail = normalized_detail
            session.add(existing)
            session.flush()
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

    def import_settlement_report(
        self,
        session: Session,
        *,
        processor: str,
        report_reference: str,
        period_start: datetime,
        period_end: datetime,
        charge_currency: str,
        settlement_currency: str,
        gross_amount: Decimal,
        refund_amount: Decimal,
        dispute_amount: Decimal,
        fee_amount: Decimal,
        tax_amount: Decimal,
        fx_rate: Decimal,
        net_amount: Decimal,
        tax_policy_reference: str | None = None,
        snapshot: dict[str, Any] | None = None,
    ) -> ProcessorSettlementReport:
        """Persist one processor report exactly once, without inventing rates."""
        processor = processor.strip()
        report_reference = report_reference.strip()
        if not processor or not report_reference:
            raise RefundError("invalid_settlement_identity")
        if period_end <= period_start:
            raise RefundError("invalid_settlement_period")
        amounts = {
            "gross_amount": round_money(gross_amount, charge_currency),
            "refund_amount": round_money(refund_amount, charge_currency),
            "dispute_amount": round_money(dispute_amount, charge_currency),
            "fee_amount": round_money(fee_amount, charge_currency),
            "tax_amount": round_money(tax_amount, charge_currency),
            "net_amount": round_money(net_amount, settlement_currency),
        }
        normalized_fx = fx_rate.quantize(Decimal("0.0000000001"))
        if any(amount < 0 for amount in amounts.values()) or normalized_fx <= 0:
            raise RefundError("invalid_settlement_amount")
        if charge_currency == settlement_currency and normalized_fx != Decimal(1):
            raise RefundError("invalid_same_currency_fx")

        self._lock_key(session, f"settlement:{processor}:{report_reference}")
        existing = session.exec(
            select(ProcessorSettlementReport).where(
                ProcessorSettlementReport.processor == processor,
                ProcessorSettlementReport.report_reference == report_reference,
            )
        ).first()
        frozen_snapshot = deepcopy(snapshot or {})
        if existing is not None:
            same_facts = (
                existing.period_start == period_start
                and existing.period_end == period_end
                and existing.charge_currency == charge_currency
                and existing.settlement_currency == settlement_currency
                and existing.gross_amount == amounts["gross_amount"]
                and existing.refund_amount == amounts["refund_amount"]
                and existing.dispute_amount == amounts["dispute_amount"]
                and existing.fee_amount == amounts["fee_amount"]
                and existing.tax_amount == amounts["tax_amount"]
                and existing.fx_rate == normalized_fx
                and existing.net_amount == amounts["net_amount"]
                and existing.tax_policy_reference == tax_policy_reference
                and existing.snapshot == frozen_snapshot
            )
            if not same_facts:
                raise RefundError("idempotency_conflict")
            return existing

        report = ProcessorSettlementReport(
            processor=processor,
            report_reference=report_reference,
            period_start=period_start,
            period_end=period_end,
            charge_currency=charge_currency,
            settlement_currency=settlement_currency,
            gross_amount=amounts["gross_amount"],
            refund_amount=amounts["refund_amount"],
            dispute_amount=amounts["dispute_amount"],
            fee_amount=amounts["fee_amount"],
            tax_amount=amounts["tax_amount"],
            fx_rate=normalized_fx,
            net_amount=amounts["net_amount"],
            tax_policy_reference=tax_policy_reference,
            snapshot=frozen_snapshot,
            imported_at=self.clock(),
        )
        session.add(report)
        session.flush()
        return report

    def reconcile_settlement_report(
        self, session: Session, report: ProcessorSettlementReport
    ) -> dict[str, Decimal | bool]:
        """Compare immutable processor facts with local records and postings."""
        attempts = session.exec(
            select(PaymentAttempt).where(
                PaymentAttempt.processor == report.processor,
                PaymentAttempt.currency == report.charge_currency,
                PaymentAttempt.status == AttemptStatus.SUCCEEDED,
                col(PaymentAttempt.captured_at) >= report.period_start,
                col(PaymentAttempt.captured_at) < report.period_end,
            )
        ).all()
        refunds = session.exec(
            select(Refund).where(
                Refund.processor == report.processor,
                Refund.currency == report.charge_currency,
                Refund.status == RefundStatus.SUCCEEDED,
                col(Refund.settled_at) >= report.period_start,
                col(Refund.settled_at) < report.period_end,
            )
        ).all()
        disputes = session.exec(
            select(Dispute).where(
                Dispute.processor == report.processor,
                Dispute.currency == report.charge_currency,
                Dispute.state == DisputeState.LOST,
                col(Dispute.resolved_at) >= report.period_start,
                col(Dispute.resolved_at) < report.period_end,
            )
        ).all()
        captured = round_money(
            sum((attempt.amount for attempt in attempts), Decimal(0)),
            report.charge_currency,
        )
        refunded = round_money(
            sum((refund.amount for refund in refunds), Decimal(0)),
            report.charge_currency,
        )
        disputed = round_money(
            sum((dispute.amount for dispute in disputes), Decimal(0)),
            report.charge_currency,
        )
        capture_events = [f"payment:{attempt.id}:captured" for attempt in attempts]
        refund_events = [f"{refund.business_event_id}:posted" for refund in refunds]
        dispute_events = [f"dispute:{dispute.id}:lost" for dispute in disputes]
        ledger_captured = self._ledger_total(
            session,
            capture_events,
            report.charge_currency,
            AccountKind.SETTLEMENT_CLEARING,
            Direction.DEBIT,
        )
        ledger_capture_revenue = self._ledger_total(
            session,
            capture_events,
            report.charge_currency,
            AccountKind.REVENUE,
            Direction.CREDIT,
        )
        ledger_refunded = self._ledger_total(
            session,
            refund_events,
            report.charge_currency,
            AccountKind.SETTLEMENT_CLEARING,
            Direction.CREDIT,
        )
        ledger_refund_revenue = self._ledger_total(
            session,
            refund_events,
            report.charge_currency,
            AccountKind.REVENUE,
            Direction.DEBIT,
        )
        ledger_disputed = self._ledger_total(
            session,
            dispute_events,
            report.charge_currency,
            AccountKind.SETTLEMENT_CLEARING,
            Direction.CREDIT,
        )
        ledger_dispute_adjustment = self._ledger_total(
            session,
            dispute_events,
            report.charge_currency,
            AccountKind.ADJUSTMENT,
            Direction.DEBIT,
        )
        pre_fx_net = (
            report.gross_amount
            - report.refund_amount
            - report.dispute_amount
            - report.fee_amount
            - report.tax_amount
        )
        formula_net = round_money(
            pre_fx_net * report.fx_rate, report.settlement_currency
        )
        result: dict[str, Decimal | bool] = {
            "local_captured": captured,
            "local_refunded": refunded,
            "local_disputed_lost": disputed,
            "gross_difference": report.gross_amount - captured,
            "refund_difference": report.refund_amount - refunded,
            "dispute_difference": report.dispute_amount - disputed,
            "ledger_capture_difference": ledger_captured - captured,
            "ledger_capture_revenue_difference": ledger_capture_revenue - captured,
            "ledger_refund_difference": ledger_refunded - refunded,
            "ledger_refund_revenue_difference": ledger_refund_revenue - refunded,
            "ledger_dispute_difference": ledger_disputed - disputed,
            "ledger_dispute_adjustment_difference": (
                ledger_dispute_adjustment - disputed
            ),
            "formula_net": formula_net,
            "net_difference": report.net_amount - formula_net,
        }
        matches = (
            result["gross_difference"] == 0
            and result["refund_difference"] == 0
            and result["dispute_difference"] == 0
            and result["ledger_capture_difference"] == 0
            and result["ledger_capture_revenue_difference"] == 0
            and result["ledger_refund_difference"] == 0
            and result["ledger_refund_revenue_difference"] == 0
            and result["ledger_dispute_difference"] == 0
            and result["ledger_dispute_adjustment_difference"] == 0
            and result["net_difference"] == 0
        )
        result["matches"] = matches
        subject = f"settlement:{report.id}"
        if matches:
            self._resolve_exception(
                session,
                ExceptionKind.SETTLEMENT_MISMATCH,
                subject,
                "processor settlement matches local records",
            )
        else:
            self.raise_exception(
                session,
                ExceptionKind.SETTLEMENT_MISMATCH,
                subject,
                "processor settlement differs from local records: "
                f"gross={result['gross_difference']}, "
                f"refund={result['refund_difference']}, "
                f"dispute={result['dispute_difference']}, "
                f"ledger_capture={result['ledger_capture_difference']}, "
                f"ledger_refund={result['ledger_refund_difference']}, "
                f"ledger_dispute={result['ledger_dispute_difference']}, "
                f"net={result['net_difference']}",
            )
        return result

    @staticmethod
    def _ledger_total(
        session: Session,
        event_ids: list[str],
        currency: str,
        account_kind: AccountKind,
        direction: Direction,
    ) -> Decimal:
        if not event_ids:
            return round_money(Decimal(0), currency)
        account = session.exec(
            select(LedgerAccount).where(
                LedgerAccount.kind == account_kind,
                LedgerAccount.owner_kind == OwnerKind.SYSTEM,
                LedgerAccount.currency == currency,
            )
        ).first()
        if account is None:
            return round_money(Decimal(0), currency)
        total = session.exec(
            select(func.sum(JournalLine.amount))
            .join(JournalEntry, col(JournalEntry.id) == JournalLine.entry_id)
            .where(
                col(JournalEntry.business_event_id).in_(event_ids),
                JournalLine.account_id == account.id,
                JournalLine.direction == direction,
            )
        ).first()
        return round_money(Decimal(total or 0), currency)

    def reconcile_settlement_reports(
        self, session: Session
    ) -> list[dict[str, Decimal | bool]]:
        """Scheduled-job seam: reconcile every imported immutable report."""
        return [
            self.reconcile_settlement_report(session, report)
            for report in session.exec(select(ProcessorSettlementReport)).all()
        ]

    def _resolve_exception(
        self,
        session: Session,
        kind: ExceptionKind,
        subject_reference: str,
        resolution: str,
    ) -> None:
        item = session.exec(
            select(ExceptionItem)
            .where(
                ExceptionItem.kind == kind,
                ExceptionItem.subject_reference == subject_reference,
            )
            .with_for_update()
        ).first()
        if item is not None and item.resolved_at is None:
            item.resolved_at = self.clock()
            item.resolution = resolution[:1000]
            session.add(item)

    def sweep_excess_payments(self, session: Session) -> list[ExceptionItem]:
        """Surface unresolved excess payments from chunk 12 for a human.

        Chunk 12 records them so the money is not lost. This is what makes
        somebody look: an excess payment nobody sees is a customer who was
        charged twice and never refunded.
        """
        raised = []
        for excess in session.exec(
            select(ExcessPayment).where(col(ExcessPayment.resolved_at).is_(None))
        ).all():
            raised.append(
                self.raise_exception(
                    session,
                    ExceptionKind.EXCESS_PAYMENT,
                    f"excess:{excess.id}",
                    f"{excess.amount} {excess.currency} received via "
                    f"{excess.processor} ({excess.reason})",
                )
            )
        return raised

    def settlement_report(self, session: Session, currency: str) -> dict[str, Decimal]:
        """Summarize recorded capture, refund and dispute economics.

        This is an expected-net report, not processor settlement reconciliation.
        Processor settlement files, fees, tax and FX remain gated by D3/D4/D5.
        """
        captured = Decimal(
            session.exec(
                select(func.sum(PaymentAttempt.amount)).where(
                    PaymentAttempt.currency == currency,
                    PaymentAttempt.status == AttemptStatus.SUCCEEDED,
                )
            ).first()
            or 0
        )
        refunded = Decimal(
            session.exec(
                select(func.sum(Refund.amount)).where(
                    Refund.currency == currency,
                    Refund.status == RefundStatus.SUCCEEDED,
                )
            ).first()
            or 0
        )
        disputed = Decimal(
            session.exec(
                select(func.sum(Dispute.amount)).where(
                    Dispute.currency == currency,
                    Dispute.state == DisputeState.LOST,
                )
            ).first()
            or 0
        )
        expected = round_money(captured - refunded - disputed, currency)
        return {
            "captured": round_money(captured, currency),
            "refunded": round_money(refunded, currency),
            "disputed_lost": round_money(disputed, currency),
            "net_expected": expected,
        }
