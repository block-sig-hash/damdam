"""Durable outbox, supplier attempts and worker leases (US-32, chunk 11).

`AGENTS.md` calls the accepted-but-response-lost case "the single most expensive
failure mode in this product", and this module exists for it.

The sequence that costs money is short. We ask a supplier to provision a line.
The request arrives, the supplier accepts it and charges us, and then the
response is lost — a timeout, a dropped connection, a worker killed mid-call.
The order still looks unfulfilled. If anything retries naively, we buy a second
line for a customer who already has one and pay for both.

Four rules follow, and each has a table behind it:

1. **The attempt is recorded before the request is sent.** `SupplierAttempt` is
   written and committed *first*, with the idempotency key we are about to use.
   A crash between commit and call is then indistinguishable from a crash after
   the call — both leave a row saying "we may have asked", which is exactly the
   state that needs reconciling.
2. **`OUTCOME_UNKNOWN` is a real state, not an error.** It is the honest answer
   when we do not know, and it routes to reconciliation rather than to retry.
3. **Reconciliation asks the *same* supplier about the *same* reference.** Never
   a different supplier, never a fresh order. If the supplier cannot answer
   definitively, the attempt is held for a human.
4. **Work is dispatched through an outbox in the same transaction as the state
   change it describes.** A message that exists because a database commit
   succeeded cannot describe a commit that did not.
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DDL,
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    event,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import Table
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now


def _enum(
    enum_type: type[Enum], name: str, default: Enum | None = None
) -> "Column[Any]":
    return Column(
        SAEnum(
            enum_type,
            name=name,
            values_callable=lambda choices: [choice.value for choice in choices],
        ),
        nullable=False,
        server_default=None if default is None else default.value,
    )


def _json() -> "Column[Any]":
    return Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)


class OutboxStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    #: Tried enough times, still failing. Parked for a human rather than
    #: retried forever -- a poison message retried forever is a queue that
    #: never drains and an alert nobody can act on.
    DEAD_LETTER = "dead_letter"


class OutboxMessage(SQLModel, table=True):
    """Work to do, written in the same transaction as the state that caused it.

    This is the transactional outbox pattern, and the reason for it is narrow
    and specific: a worker that is told to do something before the database
    commits may act on a state that then rolls back. Writing the instruction
    *into* the same transaction makes the instruction and the state atomic — the
    message exists if and only if the change did.

    `dedupe_key` is what makes a consumer idempotent from the producer's side:
    the same logical work enqueued twice is one row, not two.
    """

    __tablename__ = "outbox_messages"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_outbox_messages_dedupe"),
        CheckConstraint("attempts >= 0", name="ck_outbox_messages_attempts"),
        CheckConstraint(
            "(status = 'in_progress' AND leased_until IS NOT NULL "
            "AND leased_by IS NOT NULL AND lease_token IS NOT NULL) "
            "OR (status <> 'in_progress' AND leased_until IS NULL "
            "AND leased_by IS NULL AND lease_token IS NULL)",
            name="ck_outbox_messages_lease",
        ),
        Index(
            "ix_outbox_messages_claimable",
            "status",
            "available_at",
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
        Index("ix_outbox_messages_lease_expiry", "status", "leased_until"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    topic: str = Field(sa_column=Column(String(100), nullable=False))
    #: Names the work, not the attempt: `order_item:<id>:provision`. Two
    #: enqueues of the same work collide here rather than producing two jobs.
    dedupe_key: str = Field(sa_column=Column(String(200), nullable=False))
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=_json())
    status: OutboxStatus = Field(
        default=OutboxStatus.PENDING,
        sa_column=_enum(OutboxStatus, "outbox_status", OutboxStatus.PENDING),
    )
    attempts: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    #: When this becomes claimable. Backoff moves it forward rather than
    #: sleeping a worker, so a delayed job costs no worker time.
    available_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    #: A lease, not a lock. A worker that dies holding one loses it when the
    #: lease expires, and the work becomes claimable again -- without which a
    #: crashed worker strands its message forever.
    leased_until: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    leased_by: str | None = Field(
        default=None, sa_column=Column(String(100), nullable=True)
    )
    # Distinguishes successive leases held by the same named worker. The name
    # alone cannot stop a timed-out handler from completing a later lease.
    lease_token: UUID | None = Field(
        default=None, sa_column=Column(Uuid(), nullable=True)
    )
    last_error: str | None = Field(
        default=None, sa_column=Column(String(1000), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class InboxMessage(SQLModel, table=True):
    """Every externally delivered message we have already handled.

    The consumer side of the same idea. A supplier or processor that delivers
    the same webhook twice — which they all do — is handled once, because the
    second delivery collides on `external_id` before any handler runs.
    """

    __tablename__ = "inbox_messages"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_inbox_messages_external"),
        Index("ix_inbox_messages_received", "received_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source: str = Field(sa_column=Column(String(50), nullable=False))
    external_id: str = Field(sa_column=Column(String(200), nullable=False))
    received_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    #: What we did about it, for the operator who asks why nothing happened.
    disposition: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )


class AttemptOutcome(str, Enum):
    """What we know about a supplier request. Three answers, not two.

    `OUTCOME_UNKNOWN` is the entire point. Collapsing it into `FAILED` is what
    makes a system buy twice: a lost response looks like a failure, the failure
    looks retryable, and the retry buys a second line the supplier already sold
    us.
    """

    IN_FLIGHT = "in_flight"
    ACCEPTED = "accepted"
    #: The supplier said no, definitively. Safe to treat as final.
    REJECTED = "rejected"
    #: We do not know. Reconcile against the same reference; never retry blind.
    OUTCOME_UNKNOWN = "outcome_unknown"
    #: Reconciliation could not establish the truth either. A human decides.
    HELD_FOR_REVIEW = "held_for_review"


class SupplierAttempt(SQLModel, table=True):
    """One request to one supplier, recorded before it is sent.

    `idempotency_key` is ours and names one *request* — order item plus attempt
    number — so a reconciliation can ask the supplier about exactly this attempt
    rather than guessing which of several it means, and a legitimate second
    purchase after a definite rejection is not de-duplicated against the first.

    The partial unique index is what stops a double purchase at the database
    level rather than in a code path: one *live* attempt per order item, where
    live means anything that might still be out there.
    """

    __tablename__ = "supplier_attempts"
    __table_args__ = (
        UniqueConstraint(
            "provider", "idempotency_key", name="uq_supplier_attempts_key"
        ),
        CheckConstraint("attempt_number >= 1", name="ck_supplier_attempts_number"),
        CheckConstraint(
            "(outcome = 'accepted' AND provider_reference IS NOT NULL) "
            "OR outcome <> 'accepted'",
            name="ck_supplier_attempts_accepted_reference",
        ),
        # One live attempt per order item. A second concurrent attempt is not a
        # retry, it is a second purchase.
        Index(
            "ux_supplier_attempts_live_item",
            "order_item_id",
            unique=True,
            postgresql_where=text(
                "outcome IN ('in_flight', 'accepted', 'outcome_unknown', "
                "'held_for_review')"
            ),
            sqlite_where=text(
                "outcome IN ('in_flight', 'accepted', 'outcome_unknown', "
                "'held_for_review')"
            ),
        ),
        Index("ix_supplier_attempts_outcome", "outcome", "created_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    order_item_id: UUID = Field(
        sa_column=Column(
            ForeignKey("order_items.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
    )
    provider: str = Field(sa_column=Column(String(32), nullable=False))
    #: Ours, sent to the supplier and reused verbatim on any reconciliation.
    idempotency_key: str = Field(sa_column=Column(String(200), nullable=False))
    attempt_number: int = Field(
        default=1, sa_column=Column(Integer, nullable=False, server_default="1")
    )
    outcome: AttemptOutcome = Field(
        default=AttemptOutcome.IN_FLIGHT,
        sa_column=_enum(AttemptOutcome, "attempt_outcome", AttemptOutcome.IN_FLIGHT),
    )
    #: The supplier's own identifier, once they give us one. Null while in
    #: flight, and null forever if the response was lost -- which is precisely
    #: why reconciliation keys on *our* idempotency key instead.
    provider_reference: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    #: Why a human is looking at it, when one is.
    review_reason: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    requested_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    resolved_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


_ATTEMPT_HISTORY_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE OR REPLACE FUNCTION damdam_supplier_attempt_history() RETURNS trigger AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'supplier attempt history is immutable';
        END IF;
        IF OLD.outcome IN ('accepted', 'rejected') AND NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'terminal supplier attempt is immutable';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_supplier_attempt_history
        BEFORE UPDATE OR DELETE ON supplier_attempts
        FOR EACH ROW EXECUTE FUNCTION damdam_supplier_attempt_history();
    """
)

_ATTEMPT_TABLE: Table = SupplierAttempt.__table__  # type: ignore[attr-defined]
event.listen(
    _ATTEMPT_TABLE,
    "after_create",
    _ATTEMPT_HISTORY_TRIGGER.execute_if(dialect="postgresql"),
)
