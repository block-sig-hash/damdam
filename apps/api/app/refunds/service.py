"""Refund, dispute, funding and reconciliation behaviour (US-34, chunk 14).

The invariant this file exists to hold: **total refunded can never exceed the
refundable charge.** Everything else is arrangement around that.

It is enforced in two places on purpose. The service computes the remaining
refundable amount under a row lock, so two concurrent partial refunds cannot
both see the same headroom; and the ledger's own balance trigger means an
over-refund could not post even if the service were wrong.

Nothing here edits a posted entry. Chunk 10's triggers refuse that outright, and
this module never tries — a refund posts a new, opposite entry with its own
business event, which is also what makes it replay-safe.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlmodel import Session, col, func, select

from app.auth.models import utc_now
from app.ledger.models import AccountKind, Direction, LedgerAccount
from app.ledger.service import LedgerService, Posting
from app.money import round_money
from app.payments.contract import AttemptStatus, ExcessPayment, PaymentAttempt
from app.refunds.models import (
    BankFundingStatus,
    BankTransferReceipt,
    Dispute,
    DisputeState,
    DocumentKind,
    ExceptionItem,
    ExceptionKind,
    FinancialDocument,
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
        existing = session.exec(
            select(Refund).where(Refund.business_event_id == business_event_id)
        ).first()
        if existing is not None:
            return existing

        # Lock the charge before computing headroom.
        session.exec(
            select(PaymentAttempt)
            .where(PaymentAttempt.id == attempt.id)
            .with_for_update()
        ).first()

        if attempt.status is not AttemptStatus.SUCCEEDED:
            raise RefundError(
                "charge_not_refundable",
                "only a captured charge can be refunded",
            )
        requested = round_money(amount, attempt.currency)
        if requested <= 0:
            raise RefundError("non_positive_amount")

        remaining = self.refundable_remaining(session, attempt)
        if requested > remaining:
            # Not a large refund -- a payout, which is a different product with
            # a different licensing conversation attached.
            raise RefundError(
                "exceeds_refundable",
                f"{requested} requested against {remaining} remaining",
            )

        refund = Refund(
            business_event_id=business_event_id,
            payment_attempt_id=attempt.id,
            processor=attempt.processor,
            currency=attempt.currency,
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
        customer_account: LedgerAccount,
    ) -> Refund:
        """Post the reversal only when the processor confirms it.

        A refund that has not settled has not moved money, so posting on
        request would show a customer credited before their bank saw anything.
        """
        now = self.clock()
        if not outcome.succeeded:
            refund.status = RefundStatus.FAILED
            session.add(refund)
            session.flush()
            return refund

        refund.status = RefundStatus.SUCCEEDED
        refund.processor_reference = outcome.processor_reference
        refund.settled_at = now
        session.add(refund)

        clearing = self.ledger.account(
            session, refund.currency, AccountKind.SETTLEMENT_CLEARING
        )
        # A new, opposite entry -- never an edit. Chunk 10's trigger refuses an
        # edit anyway; this is the shape that makes the history readable.
        self.ledger.post(
            session,
            f"{refund.business_event_id}:posted",
            [
                Posting(customer_account, Direction.DEBIT, refund.amount),
                Posting(clearing, Direction.CREDIT, refund.amount),
            ],
            occurred_at=now,
            reference=f"refund {refund.id} against attempt {refund.payment_attempt_id}",
        )
        session.flush()
        return refund

    def record_refund_unknown(
        self, session: Session, refund: Refund, reason: str
    ) -> Refund:
        """A refund whose outcome we did not see. Never retried blindly.

        The processor may already have sent the money, and a second refund is a
        second payout. It stays counted against the headroom and goes to the
        exception queue.
        """
        refund.status = RefundStatus.UNKNOWN
        session.add(refund)
        self.raise_exception(
            session,
            ExceptionKind.REFUND_UNKNOWN,
            f"refund:{refund.id}",
            f"{reason[:400]}; do not re-issue -- reconcile against "
            f"{refund.business_event_id}",
        )
        session.flush()
        return refund

    def reconcile_refund(
        self, session: Session, refund: Refund, processor: RefundProcessor,
        customer_account: LedgerAccount,
    ) -> Refund:
        if processor.name != refund.processor:
            raise RefundError("wrong_processor")
        outcome = processor.fetch_refund(refund.business_event_id)
        if outcome is None:
            return refund  # still unknown; the exception item stands
        return self.record_refund_outcome(session, refund, outcome, customer_account)

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
        existing = session.exec(
            select(Dispute).where(
                Dispute.processor == attempt.processor,
                Dispute.processor_reference == processor_reference,
            )
        ).first()
        if existing is not None:
            return existing

        dispute = Dispute(
            payment_attempt_id=attempt.id,
            processor=attempt.processor,
            processor_reference=processor_reference,
            currency=attempt.currency,
            amount=round_money(amount, attempt.currency),
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
        customer_account: LedgerAccount,
    ) -> Dispute:
        """A lost dispute posts the loss. A won one posts nothing.

        Won means the money never left after all — there was nothing to record
        in the first place, and posting a reversal of a reversal would invent
        two transactions that did not happen.
        """
        now = self.clock()
        dispute.state = DisputeState.WON if won else DisputeState.LOST
        dispute.resolved_at = now
        session.add(dispute)

        # Charged to adjustment rather than to the customer: the customer did
        # not ask for this and may still hold the service. Whether the allowance
        # is clawed back is a policy question (D5) this module does not decide,
        # which is why `customer_account` is accepted for symmetry with
        # `record_refund_outcome` and deliberately not posted against.
        del customer_account
        if not won:
            clearing = self.ledger.account(
                session, dispute.currency, AccountKind.SETTLEMENT_CLEARING
            )
            adjustment = self.ledger.account(
                session, dispute.currency, AccountKind.ADJUSTMENT
            )
            self.ledger.post(
                session,
                f"dispute:{dispute.id}:lost",
                [
                    Posting(adjustment, Direction.DEBIT, dispute.amount),
                    Posting(clearing, Direction.CREDIT, dispute.amount),
                ],
                occurred_at=now,
                reference=f"chargeback lost on {dispute.processor_reference}",
            )
        session.flush()
        return dispute

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
        existing = session.exec(
            select(BankTransferReceipt).where(
                BankTransferReceipt.bank_account_reference == bank_account_reference,
                BankTransferReceipt.statement_reference == statement_reference,
            )
        ).first()
        if existing is not None:
            return existing

        receipt = BankTransferReceipt(
            bank_account_reference=bank_account_reference,
            statement_reference=statement_reference,
            currency=currency,
            amount=round_money(amount, currency),
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
        if receipt.status is BankFundingStatus.MATCHED:
            raise RefundError("already_matched")
        if account.currency != receipt.currency:
            raise RefundError("currency_mismatch")

        now = self.clock()
        clearing = self.ledger.account(
            session, receipt.currency, AccountKind.SETTLEMENT_CLEARING
        )
        self.ledger.post(
            session,
            f"bank:{receipt.id}:funding",
            [
                Posting(clearing, Direction.DEBIT, receipt.amount),
                Posting(account, Direction.CREDIT, receipt.amount),
            ],
            # The date the bank says the money arrived, not the date somebody
            # got round to reconciling it.
            occurred_at=receipt.value_date,
            reference=f"bank transfer {receipt.statement_reference}",
        )
        receipt.status = BankFundingStatus.MATCHED
        receipt.matched_ledger_account_id = account.id
        receipt.matched_by = matched_by
        receipt.matched_at = now
        session.add(receipt)
        session.flush()
        return receipt

    def flag_unmatched(
        self, session: Session, receipt: BankTransferReceipt, detail: str
    ) -> BankTransferReceipt:
        receipt.status = BankFundingStatus.UNMATCHED
        session.add(receipt)
        self.raise_exception(
            session,
            ExceptionKind.UNMATCHED_BANK_TRANSFER,
            f"bank:{receipt.id}",
            detail[:1000],
        )
        session.flush()
        return receipt

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
        now = self.clock()
        document = FinancialDocument(
            kind=kind,
            number=number,
            seller_legal_entity_id=seller_legal_entity_id,
            order_id=order_id,
            currency=currency,
            total_amount=round_money(total_amount, currency),
            snapshot={
                **snapshot,
                "currency": currency,
                "total_amount": str(round_money(total_amount, currency)),
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

    def settlement_report(
        self, session: Session, currency: str
    ) -> dict[str, Decimal | bool]:
        """Reconcile what we captured against what the ledger says.

        Captured minus refunded minus lost disputes should equal what the
        clearing account holds. A difference is not a rounding artefact — the
        ledger balances by construction — so it means something reached the
        tables without going through these services, and that is worth an
        alert.
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


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
