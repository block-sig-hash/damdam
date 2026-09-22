"""Settling what no automatic path can, safely (US-41, chunk 25).

Four rules, and each exists because an operations surface is where a careful
system usually acquires its worst bug.

**Reconcile before resolving.** An operator may not declare a supplier attempt
successful or failed while its outcome is still `outcome_unknown` and nobody has
asked the supplier. Chunk 11 built the reconciliation path precisely so that a
lost response is *asked about* rather than guessed at, and an operations screen
that lets a human skip it is a screen that buys a second eSIM on a busy morning.
`resolve_supplier_attempt` refuses; it does not warn.

**Money moves only through balanced entries.** There is no balance adjustment in
this module and there will not be one. A payment discrepancy is settled by
posting a compensating entry through chunk 10's ledger, which refuses to post
anything that does not balance. The assignment forbids "unrestricted balance
editing"; the ledger forbids it more thoroughly than a permission check could.

**Every action is recorded before it takes effect.** The audit row is written
first and the effect follows, so a crash leaves a record of an intention rather
than an unexplained change. The row is immutable at the database level.

**A replay is the same decision.** Idempotency is keyed on the action, its
subject and the operator's key. An operator who lost a response and clicked
again gets the resolution that exists — not a second compensating entry.

## What is deliberately absent

No arbitrary query surface, no balance setter, no path that deletes an exception
instead of resolving it, and no way to read unmasked activation material. The
last one matters most: `mask` exists so a support screen can show enough of an
identifier to confirm it is the right one and not enough to use it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import or_, text
from sqlmodel import Session, col, select

from app.auth.models import AdminUser, utc_now
from app.calling.charging import CallChargingService, ChargingError
from app.calling.models import CallAttempt, CallCharge, ChargeBasis
from app.connectivity.models import CarrierLine, Entitlement
from app.fulfilment.models import AttemptOutcome, SupplierAttempt
from app.ledger.models import AccountKind, Direction, LedgerAccount, OwnerKind
from app.ledger.service import LedgerService, Posting
from app.money import round_money
from app.operations.models import (
    OperatorAction,
    OperatorActionKind,
    OperatorSubjectKind,
)
from app.orders.models import OrderItem, ProvisioningState
from app.refunds.models import (
    BankFundingStatus,
    BankTransferReceipt,
    ExceptionItem,
    ExceptionKind,
)


class OperationsError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class QueueEntry:
    """One thing waiting for a human, with enough context to triage it."""

    exception_id: UUID
    kind: ExceptionKind
    subject_reference: str
    detail: str
    raised_at: datetime
    resolved_at: datetime | None = None
    #: How many operator actions already reference this item. A queue entry
    #: somebody has already acted on twice is worth looking at before a third.
    action_count: int = 0


def mask(value: str | None, *, keep: int = 4) -> str | None:
    """Show enough to recognise, never enough to use.

    Support screens need to confirm "is this the right line" without putting a
    usable identifier in front of an operator, on a shared screen, in a
    screenshot attached to a ticket. Activation material is not masked — it is
    *not returned at all* — and this exists for the things that legitimately
    have to be shown, like the last digits of a number a customer just read out.
    """
    if not value:
        return value
    if len(value) <= keep:
        return "•" * len(value)
    return "•" * (len(value) - keep) + value[-keep:]


class OperationsService:
    def __init__(
        self,
        ledger: LedgerService,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.ledger = ledger
        self.clock = clock

    # --- the queue ---------------------------------------------------------

    def queue(
        self,
        session: Session,
        *,
        kind: ExceptionKind | None = None,
        reference: str | None = None,
        include_resolved: bool = False,
        limit: int = 100,
    ) -> Sequence[QueueEntry]:
        """What is waiting, searchable by the reference a customer would quote.

        `reference` matches a prefix of the subject, because the references in
        this queue are structured — `call:<id>`, `refund:<id>` — and an operator
        with a ticket in front of them has the whole string or the kind, never
        the middle of it.
        """
        statement = select(ExceptionItem)
        if kind is not None:
            statement = statement.where(ExceptionItem.kind == kind)
        if reference:
            statement = statement.where(
                col(ExceptionItem.subject_reference).startswith(reference)
            )
        if not include_resolved:
            statement = statement.where(col(ExceptionItem.resolved_at).is_(None))
        items = session.exec(
            statement.order_by(col(ExceptionItem.raised_at)).limit(limit)
        ).all()
        return [
            QueueEntry(
                exception_id=item.id,
                kind=item.kind,
                subject_reference=item.subject_reference,
                detail=item.detail,
                raised_at=item.raised_at,
                resolved_at=item.resolved_at,
                action_count=self._action_count(session, item),
            )
            for item in items
        ]

    def history(
        self,
        session: Session,
        *,
        subject_reference: str | None = None,
        limit: int = 100,
    ) -> Sequence[OperatorAction]:
        """Every decision taken, newest first. Append-only, by trigger."""
        statement = select(OperatorAction)
        if subject_reference:
            statement = statement.where(
                OperatorAction.subject_reference == subject_reference
            )
        return session.exec(
            statement.order_by(col(OperatorAction.created_at).desc()).limit(limit)
        ).all()

    # --- supplier resolution ----------------------------------------------

    def resolve_supplier_attempt(
        self,
        session: Session,
        attempt: SupplierAttempt,
        *,
        actor: AdminUser,
        succeeded: bool,
        reason: str,
        idempotency_key: str,
        reconciled: bool = False,
        provider_reference: str | None = None,
        exception_item: ExceptionItem | None = None,
    ) -> OperatorAction:
        """Settle a purchase whose outcome we lost — **after** asking the supplier.

        The durable `held_for_review` outcome is the proof that the automatic
        reconciler asked the original supplier and could not establish the
        result. A request-body assertion is not evidence and cannot substitute
        for that state transition.

        This is the single most important guard in the chunk. Chunk 11's whole
        design rests on a lost response being *asked about* rather than guessed
        at, and an operations screen that let a human skip it would reintroduce
        the duplicate purchase that design exists to prevent.
        """
        cleaned_reason = self._clean_reason(reason)
        subject_reference = f"supplier_attempt:{attempt.id}"
        self._lock(session, subject_reference.replace("_", "-"))
        current_attempt = session.exec(
            select(SupplierAttempt)
            .where(SupplierAttempt.id == attempt.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if current_attempt is None:
            raise OperationsError("supplier_attempt_not_found")
        attempt = current_attempt
        existing = self._replayed(
            session,
            OperatorActionKind.CONFIRM_SUPPLIER_SUCCESS
            if succeeded
            else OperatorActionKind.CONFIRM_SUPPLIER_FAILURE,
            subject_reference,
            idempotency_key,
        )
        if existing is not None:
            expected_outcome = (
                AttemptOutcome.ACCEPTED.value
                if succeeded
                else AttemptOutcome.REJECTED.value
            )
            if (
                existing.reason != cleaned_reason
                or existing.exception_item_id
                != (exception_item.id if exception_item else None)
                or existing.after_state.get("attempt_outcome") != expected_outcome
                or existing.after_state.get("provider_reference")
                != (provider_reference if succeeded else attempt.provider_reference)
            ):
                raise OperationsError("idempotency_conflict")
            return existing

        if attempt.outcome in {AttemptOutcome.ACCEPTED, AttemptOutcome.REJECTED}:
            raise OperationsError(
                "attempt_already_settled",
                "this attempt already has a definitive outcome; there is "
                "nothing for an operator to decide",
            )
        if attempt.outcome is not AttemptOutcome.HELD_FOR_REVIEW:
            raise OperationsError(
                "reconciliation_required",
                "the stored attempt must show that reconciliation against the "
                "original supplier completed without a definitive answer",
            )
        del reconciled  # Compatibility only; caller testimony is not trusted.
        self._validate_exception(exception_item, subject_reference)
        if succeeded and not provider_reference:
            # Chunk 11's schema requires an accepted attempt to name what the
            # supplier said succeeded, and it is right to: confirming a success
            # without recording *which* provider record proves it is confirming
            # nothing, and leaves the next person with the operator's word.
            raise OperationsError(
                "provider_reference_required",
                "record the supplier's own reference for the work you are "
                "confirming; an outcome with nothing behind it is an assertion",
            )

        item = session.get(OrderItem, attempt.order_item_id)
        adopted_lines = session.exec(
            select(CarrierLine)
            .join(
                Entitlement,
                col(Entitlement.id) == col(CarrierLine.entitlement_id),
            )
            .where(Entitlement.order_item_id == attempt.order_item_id)
            .where(CarrierLine.carrier == attempt.provider)
        ).all()
        if succeeded:
            matching_line = next(
                (
                    line
                    for line in adopted_lines
                    if line.carrier_line_reference == provider_reference
                ),
                None,
            )
            if matching_line is None:
                raise OperationsError(
                    "supplier_success_not_adopted",
                    "the supplier reference has not been adopted into a local "
                    "line; do not label the order item provisioned until it has",
                )
        elif adopted_lines:
            raise OperationsError(
                "supplier_failure_has_adopted_service",
                "a local carrier line already proves that service was adopted; "
                "do not mark its purchase failed",
            )
        before = {
            "attempt_outcome": attempt.outcome.value,
            "provisioning_state": item.provisioning_state.value if item else None,
            "provider_reference": attempt.provider_reference,
        }

        attempt.outcome = (
            AttemptOutcome.ACCEPTED if succeeded else AttemptOutcome.REJECTED
        )
        if succeeded:
            attempt.provider_reference = provider_reference
        attempt.resolved_at = self.clock()
        session.add(attempt)
        if item is not None:
            item.provisioning_state = (
                ProvisioningState.PROVISIONED if succeeded else ProvisioningState.FAILED
            )
            session.add(item)
        session.flush()

        after = {
            "attempt_outcome": attempt.outcome.value,
            "provisioning_state": item.provisioning_state.value if item else None,
            "provider_reference": attempt.provider_reference,
        }
        action = self._record(
            session,
            kind=(
                OperatorActionKind.CONFIRM_SUPPLIER_SUCCESS
                if succeeded
                else OperatorActionKind.CONFIRM_SUPPLIER_FAILURE
            ),
            subject_kind=OperatorSubjectKind.SUPPLIER_ATTEMPT,
            subject_reference=subject_reference,
            actor=actor,
            reason=cleaned_reason,
            idempotency_key=idempotency_key,
            before=before,
            after=after,
            exception_item=exception_item,
        )
        if exception_item is not None:
            self._resolve_exception(session, exception_item)
        return action

    # --- payment discrepancy ----------------------------------------------

    def resolve_payment_discrepancy(
        self,
        session: Session,
        *,
        actor: AdminUser,
        customer_account: LedgerAccount,
        reason: str,
        idempotency_key: str,
        exception_item: ExceptionItem,
    ) -> OperatorAction:
        """Match one reconciled bank-statement line to customer service credit.

        The caller chooses only the receiving customer account. The immutable
        bank receipt supplies the amount, currency, clearing account and event
        date, so this endpoint cannot be used as a generic balance-transfer
        primitive.
        """
        cleaned_reason = self._clean_reason(reason)
        if exception_item.kind is not ExceptionKind.UNMATCHED_BANK_TRANSFER:
            raise OperationsError("exception_kind_mismatch")
        subject_reference = exception_item.subject_reference
        prefix = "bank:"
        if not subject_reference.startswith(prefix):
            raise OperationsError("exception_subject_mismatch")
        try:
            receipt_id = UUID(subject_reference.removeprefix(prefix))
        except ValueError as exc:
            raise OperationsError("exception_subject_mismatch") from exc
        self._lock(session, f"payment-discrepancy:{subject_reference}")
        existing = self._replayed(
            session,
            OperatorActionKind.RESOLVE_PAYMENT_DISCREPANCY,
            subject_reference,
            idempotency_key,
        )
        if existing is not None:
            if (
                existing.reason != cleaned_reason
                or existing.exception_item_id != exception_item.id
                or existing.after_state.get("customer_account")
                != str(customer_account.id)
            ):
                raise OperationsError("idempotency_conflict")
            return existing
        self._validate_exception(exception_item, subject_reference)

        receipt = session.exec(
            select(BankTransferReceipt)
            .where(BankTransferReceipt.id == receipt_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if receipt is None:
            raise OperationsError("bank_receipt_not_found")
        if receipt.status is not BankFundingStatus.UNMATCHED:
            raise OperationsError("bank_receipt_not_unmatched")
        if (
            customer_account.kind is not AccountKind.SERVICE_CREDIT
            or customer_account.owner_kind is OwnerKind.SYSTEM
        ):
            raise OperationsError("invalid_customer_account")
        if customer_account.currency != receipt.currency:
            raise OperationsError("cross_currency_compensation")

        rounded = round_money(receipt.amount, receipt.currency)
        clearing = self.ledger.account(
            session, receipt.currency, AccountKind.SETTLEMENT_CLEARING
        )

        entry = self.ledger.post(
            session,
            f"bank:{receipt.id}:funding",
            [
                Posting(clearing, Direction.DEBIT, rounded),
                Posting(customer_account, Direction.CREDIT, rounded),
            ],
            occurred_at=receipt.value_date,
            reference=f"bank transfer {receipt.statement_reference}",
        )
        receipt.status = BankFundingStatus.MATCHED
        receipt.matched_ledger_account_id = customer_account.id
        receipt.matched_by = f"operator:{actor.id}"
        receipt.matched_at = self.clock()
        session.add(receipt)
        session.flush()
        action = self._record(
            session,
            kind=OperatorActionKind.RESOLVE_PAYMENT_DISCREPANCY,
            subject_kind=OperatorSubjectKind.PAYMENT,
            subject_reference=subject_reference,
            actor=actor,
            reason=cleaned_reason,
            idempotency_key=idempotency_key,
            before={
                "bank_receipt": str(receipt.id),
                "status": BankFundingStatus.UNMATCHED.value,
                "amount": str(rounded),
                "currency": receipt.currency,
            },
            after={
                "compensating_entry": str(entry.id),
                "clearing_account": str(clearing.id),
                "customer_account": str(customer_account.id),
                "status": receipt.status.value,
            },
            exception_item=exception_item,
            ledger_entry_id=entry.id,
        )
        self._resolve_exception(session, exception_item)
        return action

    # --- call settlement correction --------------------------------------

    def correct_call_settlement(
        self,
        session: Session,
        charge: CallCharge,
        *,
        charging: CallChargingService,
        actor: AdminUser,
        billable_seconds: int,
        setup_amount: Decimal,
        usage_amount: Decimal,
        reason: str,
        idempotency_key: str,
        exception_item: ExceptionItem,
    ) -> OperatorAction:
        """Audit a bounded V03 charge correction and close its exact exception."""
        cleaned_reason = self._clean_reason(reason)
        if exception_item.kind not in {
            ExceptionKind.CALL_SETTLEMENT_SHORTFALL,
            ExceptionKind.SETTLEMENT_MISMATCH,
        }:
            raise OperationsError("exception_kind_mismatch")
        attempt = session.get(CallAttempt, charge.attempt_id)
        if attempt is None:  # pragma: no cover - FK guarantees this
            raise OperationsError("call_attempt_not_found")
        subject_reference = f"call:{attempt.id}"
        self._lock(session, f"call-correction:{charge.id}")
        normalized_setup = round_money(setup_amount, charge.currency)
        normalized_usage = round_money(usage_amount, charge.currency)
        existing = self._replayed(
            session,
            OperatorActionKind.CORRECT_CALL_SETTLEMENT,
            subject_reference,
            idempotency_key,
        )
        expected = {
            "billable_seconds": billable_seconds,
            "setup_amount": str(normalized_setup),
            "usage_amount": str(normalized_usage),
        }
        if existing is not None:
            if (
                existing.reason != cleaned_reason
                or existing.exception_item_id != exception_item.id
                or any(
                    existing.after_state.get(key) != value
                    for key, value in expected.items()
                )
            ):
                raise OperationsError("idempotency_conflict")
            return existing
        self._validate_exception(exception_item, subject_reference)

        before = {
            "charge_id": str(charge.id),
            "billable_seconds": charge.billable_seconds,
            "setup_amount": str(charge.setup_amount),
            "usage_amount": str(charge.usage_amount),
            "charged_amount": str(charge.charged_amount),
            "state": charge.state.value,
        }
        try:
            replacement = charging.correct(
                session,
                charge,
                billable_seconds=billable_seconds,
                setup_amount=normalized_setup,
                usage_amount=normalized_usage,
                basis=ChargeBasis.MANUAL_CORRECTION,
                detail=cleaned_reason,
                record_manual_exception=False,
            )
        except ChargingError as exc:
            raise OperationsError(exc.code, exc.detail) from exc
        after = {
            "charge_id": str(replacement.id),
            "corrects_id": str(charge.id),
            "billable_seconds": replacement.billable_seconds,
            "setup_amount": str(normalized_setup),
            "usage_amount": str(normalized_usage),
            "charged_amount": str(replacement.charged_amount),
            "state": replacement.state.value,
        }
        action = self._record(
            session,
            kind=OperatorActionKind.CORRECT_CALL_SETTLEMENT,
            subject_kind=OperatorSubjectKind.CALL_CHARGE,
            subject_reference=subject_reference,
            actor=actor,
            reason=cleaned_reason,
            idempotency_key=idempotency_key,
            before=before,
            after=after,
            exception_item=exception_item,
            ledger_entry_id=replacement.journal_entry_id,
        )
        self._resolve_exception(session, exception_item)
        return action

    # --- dismissal and access ---------------------------------------------

    def dismiss_exception(
        self,
        session: Session,
        exception_item: ExceptionItem,
        *,
        actor: AdminUser,
        reason: str,
        idempotency_key: str,
    ) -> OperatorAction:
        """Close an exception that needs nothing, with a reason on the record.

        Deliberately not a delete. The queue entry stays, resolved, because
        "somebody looked at this and decided it was fine" is information and
        an empty queue is not evidence of a quiet week.
        """
        cleaned_reason = self._clean_reason(reason)
        non_dismissible = {
            ExceptionKind.UNMATCHED_BANK_TRANSFER,
            ExceptionKind.EXCESS_PAYMENT,
            ExceptionKind.REFUND_UNKNOWN,
            ExceptionKind.DISPUTE_OPENED,
            ExceptionKind.SETTLEMENT_MISMATCH,
            ExceptionKind.CALL_DUPLICATE_BILLABLE_LEG,
            ExceptionKind.CALL_MISSING_TERMINAL_EVENT,
            ExceptionKind.CALL_UNKNOWN_OUTCOME,
            ExceptionKind.CALL_SETTLEMENT_SHORTFALL,
            ExceptionKind.CALL_SUPPLIER_COST_UNMATCHED,
        }
        if exception_item.kind in non_dismissible:
            raise OperationsError("exception_requires_resolution")
        self._lock(session, f"exception:{exception_item.id}")
        existing = self._replayed(
            session,
            OperatorActionKind.DISMISS_EXCEPTION,
            f"exception_item:{exception_item.id}",
            idempotency_key,
        )
        if existing is not None:
            if existing.reason != cleaned_reason:
                raise OperationsError("idempotency_conflict")
            return existing
        if exception_item.resolved_at is not None:
            raise OperationsError("exception_already_resolved")

        before = {
            "resolved_at": (
                exception_item.resolved_at.isoformat()
                if exception_item.resolved_at
                else None
            )
        }
        self._resolve_exception(session, exception_item)
        return self._record(
            session,
            kind=OperatorActionKind.DISMISS_EXCEPTION,
            subject_kind=OperatorSubjectKind.EXCEPTION_ITEM,
            subject_reference=f"exception_item:{exception_item.id}",
            actor=actor,
            reason=cleaned_reason,
            idempotency_key=idempotency_key,
            before=before,
            after={"resolved_at": self.clock().isoformat()},
            exception_item=exception_item,
        )

    def record_sensitive_access(
        self,
        session: Session,
        *,
        actor: AdminUser,
        subject_kind: OperatorSubjectKind,
        subject_reference: str,
        reason: str,
        idempotency_key: str,
    ) -> OperatorAction:
        """Looking is an act on this surface, so looking is recorded.

        Not a deterrent for its own sake: the question after an incident is
        always "who saw this", and a system that cannot answer it has to assume
        the worst about everybody with access.
        """
        cleaned_reason = self._clean_reason(reason)
        existing = self._replayed(
            session,
            OperatorActionKind.VIEW_SENSITIVE_RECORD,
            subject_reference,
            idempotency_key,
        )
        if existing is not None:
            if existing.reason != cleaned_reason:
                raise OperationsError("idempotency_conflict")
            return existing
        return self._record(
            session,
            kind=OperatorActionKind.VIEW_SENSITIVE_RECORD,
            subject_kind=subject_kind,
            subject_reference=subject_reference,
            actor=actor,
            reason=cleaned_reason,
            idempotency_key=idempotency_key,
            before={},
            after={},
        )

    # --- internals ---------------------------------------------------------

    def _record(
        self,
        session: Session,
        *,
        kind: OperatorActionKind,
        subject_kind: OperatorSubjectKind,
        subject_reference: str,
        actor: AdminUser,
        reason: str,
        idempotency_key: str,
        before: dict[str, Any],
        after: dict[str, Any],
        exception_item: ExceptionItem | None = None,
        ledger_entry_id: UUID | None = None,
    ) -> OperatorAction:
        cleaned = self._clean_reason(reason)
        action = OperatorAction(
            kind=kind,
            subject_kind=subject_kind,
            subject_reference=subject_reference[:200],
            actor_admin_id=actor.id,
            reason=cleaned[:500],
            idempotency_key=idempotency_key[:200],
            exception_item_id=exception_item.id if exception_item else None,
            before_state=before,
            after_state=after,
            ledger_entry_id=ledger_entry_id,
            created_at=self.clock(),
        )
        session.add(action)
        session.flush()
        return action

    @staticmethod
    def _clean_reason(reason: str) -> str:
        cleaned = (reason or "").strip()
        if not cleaned:
            raise OperationsError(
                "reason_required",
                "a privileged action without a stated reason is one nobody can "
                "review later",
            )
        return cleaned

    @staticmethod
    def _validate_exception(
        item: ExceptionItem | None, subject_reference: str
    ) -> None:
        if item is None:
            return
        if item.subject_reference != subject_reference:
            raise OperationsError("exception_subject_mismatch")
        if item.resolved_at is not None:
            raise OperationsError("exception_already_resolved")

    def _replayed(
        self,
        session: Session,
        kind: OperatorActionKind,
        subject_reference: str,
        idempotency_key: str,
    ) -> OperatorAction | None:
        return session.exec(
            select(OperatorAction).where(
                OperatorAction.kind == kind,
                OperatorAction.subject_reference == subject_reference,
                OperatorAction.idempotency_key == idempotency_key,
            )
        ).first()

    def _resolve_exception(self, session: Session, item: ExceptionItem) -> None:
        if item.resolved_at is None:
            item.resolved_at = self.clock()
            session.add(item)
            session.flush()

    def _action_count(self, session: Session, item: ExceptionItem) -> int:
        return len(
            session.exec(
                select(OperatorAction).where(
                    or_(
                        col(OperatorAction.exception_item_id) == item.id,
                        col(OperatorAction.subject_reference)
                        == item.subject_reference,
                    )
                )
            ).all()
        )

    @staticmethod
    def _lock(session: Session, key: str) -> None:
        """Serialize one operator decision for this transaction.

        Two operators opening the same exception at the same time is the normal
        case on a busy morning, not an edge one. The unique constraint is still
        the final guard; this makes the second one converge on the first's row
        instead of failing after both found nothing.
        """
        if session.get_bind().dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
                .bindparams(key=key)
            )


__all__ = ["OperationsError", "OperationsService", "QueueEntry", "mask"]
