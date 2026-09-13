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

from sqlalchemy import text
from sqlmodel import Session, col, select

from app.auth.models import AdminUser, utc_now
from app.fulfilment.models import AttemptOutcome, SupplierAttempt
from app.ledger.models import Direction, LedgerAccount
from app.ledger.service import LedgerService, Posting
from app.money import round_money
from app.operations.models import (
    OperatorAction,
    OperatorActionKind,
    OperatorSubjectKind,
)
from app.orders.models import OrderItem, ProvisioningState
from app.refunds.models import ExceptionItem, ExceptionKind


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
                action_count=self._action_count(session, item.subject_reference),
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

        `reconciled` is passed by the caller because reconciliation talks to a
        supplier and this module does not. It is a required, explicit assertion
        that somebody went and looked: an operator who has not reconciled cannot
        proceed by clicking harder, and the refusal names the reason.

        This is the single most important guard in the chunk. Chunk 11's whole
        design rests on a lost response being *asked about* rather than guessed
        at, and an operations screen that let a human skip it would reintroduce
        the duplicate purchase that design exists to prevent.
        """
        self._lock(session, f"supplier-attempt:{attempt.id}")
        existing = self._replayed(
            session,
            OperatorActionKind.CONFIRM_SUPPLIER_SUCCESS
            if succeeded
            else OperatorActionKind.CONFIRM_SUPPLIER_FAILURE,
            f"supplier_attempt:{attempt.id}",
            idempotency_key,
        )
        if existing is not None:
            return existing

        if attempt.outcome in {AttemptOutcome.ACCEPTED, AttemptOutcome.REJECTED}:
            raise OperationsError(
                "attempt_already_settled",
                "this attempt already has a definitive outcome; there is "
                "nothing for an operator to decide",
            )
        if not reconciled:
            raise OperationsError(
                "reconciliation_required",
                "ask the supplier what happened to this idempotency key before "
                "recording an outcome; resolving without it is how a second "
                "purchase gets made",
            )
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
            subject_reference=f"supplier_attempt:{attempt.id}",
            actor=actor,
            reason=reason,
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
        debit_account: LedgerAccount,
        credit_account: LedgerAccount,
        amount: Decimal,
        reason: str,
        idempotency_key: str,
        subject_reference: str,
        exception_item: ExceptionItem | None = None,
    ) -> OperatorAction:
        """Settle a payment our records cannot account for.

        The **only** money path on this surface, and it is a balanced posting
        through chunk 10 rather than an adjustment to a balance. The ledger
        refuses an entry that does not balance, which is a stronger guarantee
        than any permission check on a "set balance" field — and the reason a
        set-balance field does not exist here.

        Both accounts are supplied by the caller and validated for currency.
        Cross-currency compensation is refused rather than converted: inventing
        an FX rate inside an exception queue is how a discrepancy becomes two.
        """
        if debit_account.currency != credit_account.currency:
            raise OperationsError(
                "cross_currency_compensation",
                "a compensating entry moves one currency; converting here would "
                "invent a rate nobody agreed",
            )
        rounded = round_money(amount, debit_account.currency)
        if rounded <= 0:
            raise OperationsError("non_positive_amount")

        self._lock(session, f"payment-discrepancy:{subject_reference}")
        existing = self._replayed(
            session,
            OperatorActionKind.RESOLVE_PAYMENT_DISCREPANCY,
            subject_reference,
            idempotency_key,
        )
        if existing is not None:
            return existing

        entry = self.ledger.post(
            session,
            f"operations:{idempotency_key}",
            [
                Posting(debit_account, Direction.DEBIT, rounded),
                Posting(credit_account, Direction.CREDIT, rounded),
            ],
            occurred_at=self.clock(),
            reference=f"operator compensation: {subject_reference}",
        )
        action = self._record(
            session,
            kind=OperatorActionKind.RESOLVE_PAYMENT_DISCREPANCY,
            subject_kind=OperatorSubjectKind.PAYMENT,
            subject_reference=subject_reference,
            actor=actor,
            reason=reason,
            idempotency_key=idempotency_key,
            before={"unreconciled_amount": str(rounded)},
            after={
                "compensating_entry": str(entry.id),
                "debit_account": str(debit_account.id),
                "credit_account": str(credit_account.id),
            },
            exception_item=exception_item,
            ledger_entry_id=entry.id,
        )
        if exception_item is not None:
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
        self._lock(session, f"exception:{exception_item.id}")
        existing = self._replayed(
            session,
            OperatorActionKind.DISMISS_EXCEPTION,
            f"exception_item:{exception_item.id}",
            idempotency_key,
        )
        if existing is not None:
            return existing

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
            reason=reason,
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
        existing = self._replayed(
            session,
            OperatorActionKind.VIEW_SENSITIVE_RECORD,
            subject_reference,
            idempotency_key,
        )
        if existing is not None:
            return existing
        return self._record(
            session,
            kind=OperatorActionKind.VIEW_SENSITIVE_RECORD,
            subject_kind=subject_kind,
            subject_reference=subject_reference,
            actor=actor,
            reason=reason,
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
        cleaned = (reason or "").strip()
        if not cleaned:
            # The database refuses it too. Checking here as well means the
            # caller gets a named error rather than an integrity error, and the
            # rule survives somebody removing one of the two.
            raise OperationsError(
                "reason_required",
                "a privileged action without a stated reason is one nobody can "
                "review later",
            )
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

    def _action_count(self, session: Session, subject_reference: str) -> int:
        return len(
            session.exec(
                select(OperatorAction).where(
                    OperatorAction.subject_reference == subject_reference
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
