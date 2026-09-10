"""Order fulfilment, durable retries and reconciliation (US-32, chunk 11).

The order of operations is the whole design, so it is worth stating plainly:

1. Record the attempt, **commit**, then call the supplier.
2. If the call returns cleanly, record what it said.
3. If it times out, crashes or the process dies — do **not** retry the purchase.
   Mark it `OUTCOME_UNKNOWN` and reconcile against the same supplier using the
   same idempotency key.
4. If reconciliation cannot establish the truth, hold it for a human.

Step 1's ordering is what makes step 3 possible. A crash between committing the
attempt and making the call is indistinguishable from a crash after the call —
and that is fine, because both are reconciled the same way. The alternative,
calling first and recording afterwards, produces a purchase nobody has any
record of.

Never in this file: a second supplier, a fresh order, or a retry of a request
whose outcome is unknown.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.auth.models import utc_now
from app.fulfilment.models import (
    AttemptOutcome,
    InboxMessage,
    OutboxMessage,
    OutboxStatus,
    SupplierAttempt,
)
from app.orders.models import OrderItem, ProvisioningState


class FulfilmentError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


class SupplierTimeout(Exception):
    """The request may or may not have been accepted. That is the point."""


@dataclass(frozen=True)
class SupplierResult:
    accepted: bool
    provider_reference: str | None = None
    #: Set when the supplier definitively refused. A refusal is safe to treat
    #: as final; an absence of response never is.
    rejection_reason: str | None = None


class SupplierClient(Protocol):
    """The narrow surface fulfilment needs from any provisioning supplier.

    `reconcile` is the half that matters. A supplier without it cannot be used
    for anything we pay for, because there would be no way to answer "did that
    request land" other than guessing.
    """

    name: str

    def provision(
        self, idempotency_key: str, payload: dict[str, Any]
    ) -> SupplierResult: ...

    def reconcile(self, idempotency_key: str) -> SupplierResult | None:
        """What happened to this exact request, or `None` if unknowable."""
        ...


class FulfilmentService:
    #: How long a worker may hold a message before it is considered dead. Long
    #: enough for a slow supplier call, short enough that a killed worker's
    #: work is picked up in the same shift.
    LEASE = timedelta(minutes=5)
    MAX_ATTEMPTS = 5

    def __init__(
        self,
        clock: Callable[[], datetime] = utc_now,
        lease: timedelta | None = None,
        max_attempts: int | None = None,
    ) -> None:
        self.clock = clock
        self.lease = lease or self.LEASE
        self.max_attempts = max_attempts or self.MAX_ATTEMPTS

    # --- outbox -----------------------------------------------------------

    def enqueue(
        self,
        session: Session,
        topic: str,
        dedupe_key: str,
        payload: dict[str, Any],
        available_at: datetime | None = None,
    ) -> OutboxMessage:
        """Enqueue in the caller's transaction. Deliberately does not commit.

        The point of an outbox is that the message and the state change it
        describes commit together. A helper that committed here would break the
        one property the pattern exists for.
        """
        existing = session.exec(
            select(OutboxMessage).where(OutboxMessage.dedupe_key == dedupe_key)
        ).first()
        if existing is not None:
            return existing
        message = OutboxMessage(
            topic=topic,
            dedupe_key=dedupe_key,
            payload=payload,
            status=OutboxStatus.PENDING,
            available_at=available_at or self.clock(),
            created_at=self.clock(),
        )
        session.add(message)
        session.flush()
        return message

    def claim(
        self, session: Session, worker: str, topic: str | None = None
    ) -> OutboxMessage | None:
        """Take one claimable message under a lease.

        `SKIP LOCKED` is what lets several workers drain the same queue without
        queueing behind each other: a row another worker is already claiming is
        skipped rather than waited on.

        A message whose lease has expired is claimable again. That is how a
        killed worker's work is recovered — without it, a crash strands the
        message forever and the order silently never completes.
        """
        now = self.clock()
        statement = (
            select(OutboxMessage)
            .where(
                col(OutboxMessage.status).in_(
                    [OutboxStatus.PENDING, OutboxStatus.IN_PROGRESS]
                ),
                col(OutboxMessage.available_at) <= now,
            )
            .order_by(col(OutboxMessage.available_at))
            .with_for_update(skip_locked=True)
        )
        if topic is not None:
            statement = statement.where(OutboxMessage.topic == topic)

        for candidate in session.exec(statement).all():
            if candidate.status is OutboxStatus.IN_PROGRESS:
                leased_until = candidate.leased_until
                if leased_until is not None and _aware(leased_until) > now:
                    continue  # somebody else still holds a live lease
            candidate.status = OutboxStatus.IN_PROGRESS
            candidate.leased_until = now + self.lease
            candidate.leased_by = worker
            candidate.attempts += 1
            session.add(candidate)
            session.flush()
            return candidate
        return None

    def complete(self, session: Session, message: OutboxMessage) -> OutboxMessage:
        message.status = OutboxStatus.DONE
        message.leased_until = None
        message.leased_by = None
        message.completed_at = self.clock()
        session.add(message)
        session.flush()
        return message

    def fail(
        self, session: Session, message: OutboxMessage, error: str
    ) -> OutboxMessage:
        """Back off, or park it for a human once it has had enough tries.

        A poison message retried forever is a queue that never drains and an
        alert nobody can act on. Dead-lettering is the honest end state: the
        work did not happen, and somebody has to look.
        """
        now = self.clock()
        message.last_error = error[:1000]
        message.leased_until = None
        message.leased_by = None
        if message.attempts >= self.max_attempts:
            message.status = OutboxStatus.DEAD_LETTER
            message.completed_at = now
        else:
            message.status = OutboxStatus.PENDING
            # Exponential backoff, moving the row forward rather than sleeping
            # a worker: a delayed job should cost no worker time.
            message.available_at = now + timedelta(
                seconds=min(300, 2**message.attempts)
            )
        session.add(message)
        session.flush()
        return message

    # --- inbox ------------------------------------------------------------

    def accept_once(
        self, session: Session, source: str, external_id: str, disposition: str
    ) -> bool:
        """Record an inbound delivery, returning False if it is a duplicate.

        Suppliers and processors all redeliver. The constraint decides, not a
        prior read: two concurrent deliveries of the same webhook both see "not
        handled", and exactly one of them wins the insert.
        """
        session.add(
            InboxMessage(
                source=source,
                external_id=external_id,
                received_at=self.clock(),
                disposition=disposition,
            )
        )
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            return False
        return True

    # --- supplier attempts ------------------------------------------------

    @staticmethod
    def idempotency_key(order_item_id: UUID, attempt_number: int) -> str:
        """Identifies one *request*, not one order item.

        The first version of this keyed on the order item alone, on the theory
        that the key should be reconstructible without stored state. Two things
        were wrong with that. The row is always available — it is committed
        before the call, which is the whole point — so nothing needed
        reconstructing. And more importantly, a *legitimate* second attempt
        after a definitive rejection would reuse the key, and the supplier would
        de-duplicate the new purchase against the old refusal. The order would
        never be fulfilled and nothing would say why.

        An idempotency key names a request. A retry of the same request reuses
        it; a new decision to buy gets a new one.
        """
        return f"order-item:{order_item_id}:attempt:{attempt_number}"

    def begin_attempt(
        self, session: Session, item: OrderItem, provider: str
    ) -> SupplierAttempt:
        """Record the attempt. The caller commits *before* calling the supplier.

        Returning an existing live attempt rather than creating a second one is
        the double-purchase guard in service form; the partial unique index is
        the same guard in the database.
        """
        live = session.exec(
            select(SupplierAttempt).where(
                SupplierAttempt.order_item_id == item.id,
                col(SupplierAttempt.outcome).in_(
                    [
                        AttemptOutcome.IN_FLIGHT,
                        AttemptOutcome.ACCEPTED,
                        AttemptOutcome.OUTCOME_UNKNOWN,
                        AttemptOutcome.HELD_FOR_REVIEW,
                    ]
                ),
            )
        ).first()
        if live is not None:
            return live

        previous = session.exec(
            select(SupplierAttempt).where(SupplierAttempt.order_item_id == item.id)
        ).all()
        attempt_number = len(previous) + 1
        now = self.clock()
        attempt = SupplierAttempt(
            order_item_id=item.id,
            provider=provider,
            idempotency_key=self.idempotency_key(item.id, attempt_number),
            attempt_number=attempt_number,
            outcome=AttemptOutcome.IN_FLIGHT,
            requested_at=now,
            created_at=now,
        )
        session.add(attempt)
        item.provisioning_state = ProvisioningState.REQUESTED
        item.operation_reference = attempt.idempotency_key
        session.add(item)
        session.flush()
        return attempt

    def record_result(
        self,
        session: Session,
        attempt: SupplierAttempt,
        result: SupplierResult,
    ) -> SupplierAttempt:
        now = self.clock()
        item = session.get(OrderItem, attempt.order_item_id)
        if item is None:  # pragma: no cover - FK guarantees this
            raise FulfilmentError("order_item_not_found")

        if result.accepted:
            attempt.outcome = AttemptOutcome.ACCEPTED
            attempt.provider_reference = result.provider_reference
            item.provisioning_state = ProvisioningState.PROVISIONED
        else:
            attempt.outcome = AttemptOutcome.REJECTED
            attempt.review_reason = result.rejection_reason
            item.provisioning_state = ProvisioningState.FAILED
        attempt.resolved_at = now
        session.add(attempt)
        session.add(item)
        session.flush()
        return attempt

    def record_unknown(
        self, session: Session, attempt: SupplierAttempt, reason: str
    ) -> SupplierAttempt:
        """The lost response. Not a failure — an unknown.

        The distinction is the expensive one. Marking this `FAILED` makes it
        look retryable, and the retry buys a second line the supplier has
        already sold us.
        """
        attempt.outcome = AttemptOutcome.OUTCOME_UNKNOWN
        attempt.review_reason = reason[:500]
        item = session.get(OrderItem, attempt.order_item_id)
        if item is not None:
            item.provisioning_state = ProvisioningState.OUTCOME_UNKNOWN
            session.add(item)
        session.add(attempt)
        session.flush()
        return attempt

    def reconcile(
        self, session: Session, attempt: SupplierAttempt, client: SupplierClient
    ) -> SupplierAttempt:
        """Ask the same supplier about the same reference.

        Three outcomes, and the third is not a failure of this function:

        - the supplier confirms it accepted → the order is fulfilled, nothing
          is bought;
        - the supplier confirms it never landed → the item is failed and may be
          ordered again *as a new attempt*;
        - the supplier cannot say → **held for review**. A human decides,
          because guessing either way costs money in one direction or leaves a
          customer without service in the other.
        """
        if attempt.outcome not in (
            AttemptOutcome.OUTCOME_UNKNOWN,
            AttemptOutcome.IN_FLIGHT,
        ):
            raise FulfilmentError("attempt_not_reconcilable")
        if client.name != attempt.provider:
            # The rule AGENTS.md states outright: an unknown outcome reconciles
            # against the *original* operation, never another vendor.
            raise FulfilmentError(
                "wrong_supplier",
                f"attempt was sent to {attempt.provider}, not {client.name}",
            )

        answer = client.reconcile(attempt.idempotency_key)
        if answer is None:
            attempt.outcome = AttemptOutcome.HELD_FOR_REVIEW
            attempt.review_reason = (
                "supplier could not confirm the outcome of "
                f"{attempt.idempotency_key}; held for operations review"
            )
            attempt.resolved_at = None
            session.add(attempt)
            session.flush()
            return attempt
        return self.record_result(session, attempt, answer)

    # --- cancellation -----------------------------------------------------

    def cancel(self, session: Session, item: OrderItem) -> OrderItem:
        """Cancel an item, unless something is already in flight for it.

        The cancel-versus-fulfil race: a cancellation arriving while a supplier
        request is outstanding must not mark the item cancelled, because the
        supplier may be about to accept. It is refused, and the reconciliation
        resolves the truth first.
        """
        live = session.exec(
            select(SupplierAttempt).where(
                SupplierAttempt.order_item_id == item.id,
                col(SupplierAttempt.outcome).in_(
                    [
                        AttemptOutcome.IN_FLIGHT,
                        AttemptOutcome.OUTCOME_UNKNOWN,
                        AttemptOutcome.HELD_FOR_REVIEW,
                    ]
                ),
            )
        ).first()
        if live is not None:
            raise FulfilmentError(
                "cancel_conflicts_with_attempt",
                "a supplier request is outstanding; reconcile it first",
            )
        if item.provisioning_state is ProvisioningState.PROVISIONED:
            raise FulfilmentError("already_provisioned")

        item.provisioning_state = ProvisioningState.CANCELLED
        session.add(item)
        # Any queued provisioning work for this item is dropped, so a worker
        # that claims it later does not provision something already cancelled.
        session.execute(
            update(OutboxMessage)
            .where(
                col(OutboxMessage.dedupe_key)
                == f"order_item:{item.id}:provision",
                col(OutboxMessage.status) == OutboxStatus.PENDING,
            )
            .values(
                status=OutboxStatus.DONE,
                completed_at=self.clock(),
                last_error="cancelled before dispatch",
            )
        )
        session.flush()
        return item


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
