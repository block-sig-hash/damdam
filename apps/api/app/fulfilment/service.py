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
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, text, update
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

    @staticmethod
    def _lock_key(session: Session, key: str) -> None:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
                .bindparams(key=key)
            )

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
        self._lock_key(session, f"outbox:{dedupe_key}")
        existing = session.exec(
            select(OutboxMessage).where(OutboxMessage.dedupe_key == dedupe_key)
        ).first()
        if existing is not None:
            if existing.topic != topic or existing.payload != payload:
                raise FulfilmentError(
                    "idempotency_conflict",
                    f"outbox key {dedupe_key} already names different work",
                )
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
        if not worker.strip():
            raise FulfilmentError("invalid_worker")
        statement = (
            select(OutboxMessage)
            .where(
                or_(
                    col(OutboxMessage.status) == OutboxStatus.PENDING,
                    and_(
                        col(OutboxMessage.status) == OutboxStatus.IN_PROGRESS,
                        col(OutboxMessage.leased_until) <= now,
                    ),
                ),
                col(OutboxMessage.available_at) <= now,
            )
            .order_by(col(OutboxMessage.available_at))
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if topic is not None:
            statement = statement.where(OutboxMessage.topic == topic)

        candidate = session.exec(statement).first()
        if candidate is None:
            return None
        candidate.status = OutboxStatus.IN_PROGRESS
        candidate.leased_until = now + self.lease
        candidate.leased_by = worker
        candidate.lease_token = uuid4()
        # Preserve the claim identity across Session commit expiration. A
        # mapped attribute may reload the *next* worker's token, which would
        # let a stale handler accidentally authenticate as the new lease.
        candidate.__dict__["_claimed_message_id"] = candidate.id
        candidate.__dict__["_claimed_lease_token"] = candidate.lease_token
        candidate.attempts += 1
        session.add(candidate)
        session.flush()
        return candidate

    def _active_lease(
        self, session: Session, message: OutboxMessage
    ) -> OutboxMessage:
        expected_token = message.__dict__.get("_claimed_lease_token")
        message_id = message.__dict__.get("_claimed_message_id")
        if expected_token is None or message_id is None:
            raise FulfilmentError("stale_lease")
        current = session.exec(
            select(OutboxMessage)
            .where(OutboxMessage.id == message_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        now = self.clock()
        if (
            current is None
            or current.status is not OutboxStatus.IN_PROGRESS
            or current.lease_token != expected_token
            or current.leased_until is None
            or _aware(current.leased_until) <= now
        ):
            raise FulfilmentError("stale_lease")
        return current

    def complete(self, session: Session, message: OutboxMessage) -> OutboxMessage:
        current = self._active_lease(session, message)
        current.status = OutboxStatus.DONE
        current.leased_until = None
        current.leased_by = None
        current.lease_token = None
        current.completed_at = self.clock()
        message.__dict__.pop("_claimed_message_id", None)
        message.__dict__.pop("_claimed_lease_token", None)
        session.add(current)
        session.flush()
        return current

    def fail(
        self, session: Session, message: OutboxMessage, error: str
    ) -> OutboxMessage:
        """Back off, or park it for a human once it has had enough tries.

        A poison message retried forever is a queue that never drains and an
        alert nobody can act on. Dead-lettering is the honest end state: the
        work did not happen, and somebody has to look.
        """
        current = self._active_lease(session, message)
        now = self.clock()
        current.last_error = error[:1000]
        current.leased_until = None
        current.leased_by = None
        current.lease_token = None
        message.__dict__.pop("_claimed_message_id", None)
        message.__dict__.pop("_claimed_lease_token", None)
        if current.attempts >= self.max_attempts:
            current.status = OutboxStatus.DEAD_LETTER
            current.completed_at = now
        else:
            current.status = OutboxStatus.PENDING
            # Exponential backoff, moving the row forward rather than sleeping
            # a worker: a delayed job should cost no worker time.
            current.available_at = now + timedelta(
                seconds=min(300, 2**current.attempts)
            )
        session.add(current)
        session.flush()
        return current

    # --- inbox ------------------------------------------------------------

    def accept_once(
        self, session: Session, source: str, external_id: str, disposition: str
    ) -> bool:
        """Record an inbound delivery, returning False if it is a duplicate.

        Suppliers and processors all redeliver. The constraint decides, not a
        prior read: two concurrent deliveries of the same webhook both see "not
        handled", and exactly one of them wins the insert.
        """
        try:
            with session.begin_nested():
                session.add(
                    InboxMessage(
                        source=source,
                        external_id=external_id,
                        received_at=self.clock(),
                        disposition=disposition,
                    )
                )
                session.flush()
        except IntegrityError:
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
        current_item = session.exec(
            select(OrderItem)
            .where(OrderItem.id == item.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if current_item is None:
            raise FulfilmentError("order_item_not_found")

        live = session.exec(
            select(SupplierAttempt).where(
                SupplierAttempt.order_item_id == current_item.id,
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
            if live.provider != provider:
                raise FulfilmentError("attempt_provider_conflict")
            return live

        if current_item.provisioning_state is ProvisioningState.CANCELLED:
            raise FulfilmentError("item_cancelled")
        if current_item.provisioning_state is ProvisioningState.PROVISIONED:
            raise FulfilmentError("already_provisioned")

        previous = session.exec(
            select(SupplierAttempt).where(
                SupplierAttempt.order_item_id == current_item.id
            )
        ).all()
        attempt_number = len(previous) + 1
        now = self.clock()
        attempt = SupplierAttempt(
            order_item_id=current_item.id,
            provider=provider,
            idempotency_key=self.idempotency_key(current_item.id, attempt_number),
            attempt_number=attempt_number,
            outcome=AttemptOutcome.IN_FLIGHT,
            requested_at=now,
            created_at=now,
        )
        session.add(attempt)
        current_item.provisioning_state = ProvisioningState.REQUESTED
        current_item.operation_reference = attempt.idempotency_key
        session.add(current_item)
        session.flush()
        return attempt

    def _locked_attempt(
        self, session: Session, attempt: SupplierAttempt
    ) -> tuple[OrderItem, SupplierAttempt]:
        # Every state transition takes the order item first. The consistent
        # order serializes begin/result/unknown/cancel without deadlocks.
        item = session.exec(
            select(OrderItem)
            .where(OrderItem.id == attempt.order_item_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if item is None:  # pragma: no cover - FK guarantees this
            raise FulfilmentError("order_item_not_found")
        current = session.exec(
            select(SupplierAttempt)
            .where(SupplierAttempt.id == attempt.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if current is None:
            raise FulfilmentError("attempt_not_found")
        return item, current

    def record_result(
        self,
        session: Session,
        attempt: SupplierAttempt,
        result: SupplierResult,
    ) -> SupplierAttempt:
        if result.accepted and not (result.provider_reference or "").strip():
            raise FulfilmentError("accepted_result_missing_reference")
        now = self.clock()
        item, current = self._locked_attempt(session, attempt)

        if current.outcome is AttemptOutcome.ACCEPTED:
            if (
                result.accepted
                and current.provider_reference == result.provider_reference
            ):
                return current
            raise FulfilmentError("attempt_already_resolved")
        if current.outcome is AttemptOutcome.REJECTED:
            if (
                not result.accepted
                and current.review_reason == result.rejection_reason
            ):
                return current
            raise FulfilmentError("attempt_already_resolved")
        if item.provisioning_state is ProvisioningState.CANCELLED:
            raise FulfilmentError("item_cancelled")

        if result.accepted:
            current.outcome = AttemptOutcome.ACCEPTED
            current.provider_reference = result.provider_reference
            item.provisioning_state = ProvisioningState.PROVISIONED
        else:
            current.outcome = AttemptOutcome.REJECTED
            current.review_reason = result.rejection_reason
            item.provisioning_state = ProvisioningState.FAILED
        current.resolved_at = now
        session.add(current)
        session.add(item)
        session.flush()
        return current

    def record_unknown(
        self, session: Session, attempt: SupplierAttempt, reason: str
    ) -> SupplierAttempt:
        """The lost response. Not a failure — an unknown.

        The distinction is the expensive one. Marking this `FAILED` makes it
        look retryable, and the retry buys a second line the supplier has
        already sold us.
        """
        item, current = self._locked_attempt(session, attempt)
        if current.outcome not in (
            AttemptOutcome.IN_FLIGHT,
            AttemptOutcome.OUTCOME_UNKNOWN,
        ):
            raise FulfilmentError("attempt_not_markable_unknown")
        current.outcome = AttemptOutcome.OUTCOME_UNKNOWN
        current.review_reason = reason[:500]
        item.provisioning_state = ProvisioningState.OUTCOME_UNKNOWN
        session.add(item)
        session.add(current)
        session.flush()
        return current

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
            _item, current = self._locked_attempt(session, attempt)
            if current.outcome not in (
                AttemptOutcome.OUTCOME_UNKNOWN,
                AttemptOutcome.IN_FLIGHT,
            ):
                raise FulfilmentError("attempt_not_reconcilable")
            current.outcome = AttemptOutcome.HELD_FOR_REVIEW
            current.review_reason = (
                "supplier could not confirm the outcome of "
                f"{current.idempotency_key}; held for operations review"
            )
            current.resolved_at = None
            session.add(current)
            session.flush()
            return current
        return self.record_result(session, attempt, answer)

    # --- cancellation -----------------------------------------------------

    def cancel(self, session: Session, item: OrderItem) -> OrderItem:
        """Cancel an item, unless something is already in flight for it.

        The cancel-versus-fulfil race: a cancellation arriving while a supplier
        request is outstanding must not mark the item cancelled, because the
        supplier may be about to accept. It is refused, and the reconciliation
        resolves the truth first.
        """
        current_item = session.exec(
            select(OrderItem)
            .where(OrderItem.id == item.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if current_item is None:
            raise FulfilmentError("order_item_not_found")
        live = session.exec(
            select(SupplierAttempt).where(
                SupplierAttempt.order_item_id == current_item.id,
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
        if current_item.provisioning_state is ProvisioningState.PROVISIONED:
            raise FulfilmentError("already_provisioned")

        current_item.provisioning_state = ProvisioningState.CANCELLED
        session.add(current_item)
        # Any queued provisioning work for this item is dropped, so a worker
        # that claims it later does not provision something already cancelled.
        session.execute(
            update(OutboxMessage)
            .where(
                col(OutboxMessage.dedupe_key)
                == f"order_item:{current_item.id}:provision",
                col(OutboxMessage.status) == OutboxStatus.PENDING,
            )
            .values(
                status=OutboxStatus.DONE,
                completed_at=self.clock(),
                last_error="cancelled before dispatch",
            )
        )
        session.flush()
        return current_item


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
