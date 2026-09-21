"""Bulk orders, per-recipient assignment and activation requests (US-40, chunk 23).

Three tables, and the shape of all three follows from one fact: **a bulk order
is fifty independent purchases that happen to share a button.**

An organization buying service for fifty staff is not buying one thing. Each
recipient gets their own funded line, their own supplier attempt and their own
outcome, and the interesting state of the job is almost never "done" or "failed"
— it is "forty-seven provisioned, two waiting on a supplier we lost contact
with, one recipient whose email was mistyped". A job modelled as a single
transaction has to lie about that, and the lie shows up as a customer charged
for fifty lines who received forty-seven.

So `bulk_job_items` carries the state, and `bulk_jobs` carries only the counts
and the paperwork. Resuming a job means resuming *items*, chosen by what each
one actually is: a failed item may be retried, an item whose supplier outcome is
**unknown** must be reconciled first, and a provisioned item is never touched
again.

**`activation_requests`** is the recipient-bound half. An organization can buy a
line for somebody who has no account with us at all — chunk 22's people are
recipients, not users — so the grant exists before anybody has claimed it, and
the request is what lets exactly one person claim exactly one line.

The distinction the assignment insists on lives here too: a *request* is not an
installation and an installation is not network attachment. This table records
only the request and its redemption; whether a profile reached a handset is
`esim_installations` (chunk 15) and whether the network saw it is
`carrier_lines`. A dashboard that collapsed them would tell an administrator
their staff are connected when nothing has happened but an email.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now
from app.money import currency_check, currency_column, money_column


def _enum(
    enum_type: type[Enum], name: str, default: Enum | None = None
) -> Column[Any]:
    return Column(
        SAEnum(
            enum_type,
            name=name,
            values_callable=lambda choices: [choice.value for choice in choices],
        ),
        nullable=False,
        server_default=None if default is None else default.value,
    )


class BulkJobState(str, Enum):
    """Where a job is. Each value is somewhere fifty purchases can actually be."""

    #: Recipients chosen and validated; no money held, nothing ordered.
    PLANNED = "planned"
    #: Per-line reservations taken. The organization's funds are committed.
    FUNDED = "funded"
    #: Supplier work is in flight. Items are moving independently.
    PROVISIONING = "provisioning"
    #: Every item reached a terminal state and all of them succeeded.
    COMPLETED = "completed"
    #: Every item reached a terminal state and some did not succeed. **Not** a
    #: failure of the job: forty-seven people have working lines.
    PARTIALLY_COMPLETED = "partially_completed"
    #: Stopped before provisioning, with reservations released.
    CANCELLED = "cancelled"


class BulkItemState(str, Enum):
    """One recipient's line, from chosen to connected or explained."""

    PENDING = "pending"
    #: The recipient cannot be served as given — archived, or nothing to send a
    #: request to. Never charged, and visible so somebody can fix the row.
    INVALID = "invalid"
    #: Funds held for this line specifically.
    RESERVED = "reserved"
    #: An order item exists and the supplier has been asked.
    ORDERED = "ordered"
    PROVISIONED = "provisioned"
    #: The supplier refused, definitively. Safe to retry.
    FAILED = "failed"
    #: We lost the answer. **Not** safe to retry — reconcile first. This is the
    #: state that makes a bulk job dangerous, and the one the resume path is
    #: built around.
    UNKNOWN = "unknown"
    #: Withdrawn before the service was consumed.
    CANCELLED = "cancelled"


#: An item in one of these has finished moving on its own.
TERMINAL_ITEM_STATES = frozenset(
    {
        BulkItemState.PROVISIONED,
        BulkItemState.FAILED,
        BulkItemState.INVALID,
        BulkItemState.CANCELLED,
    }
)

#: Money is committed for an item in one of these.
FUNDED_ITEM_STATES = frozenset(
    {
        BulkItemState.RESERVED,
        BulkItemState.ORDERED,
        BulkItemState.UNKNOWN,
    }
)


class ActivationRequestState(str, Enum):
    """The life of an invitation to claim one line."""

    PENDING = "pending"
    #: Delivered to the recipient. Delivery is not acceptance.
    SENT = "sent"
    #: Claimed by exactly one account, once.
    REDEEMED = "redeemed"
    EXPIRED = "expired"
    #: Withdrawn by the organization — somebody left before they claimed it.
    REVOKED = "revoked"


class BulkJob(SQLModel, table=True):
    """One organization's bulk purchase, as paperwork and counts.

    The counts are denormalized on purpose. A dashboard showing fifty jobs
    cannot aggregate fifty item tables on every render, and the numbers are
    written in the same transaction as the item they describe — so they are a
    cache that cannot drift rather than a summary somebody recomputes.
    """

    __tablename__ = "bulk_jobs"
    __table_args__ = (
        # A double-submitted "buy for these fifty people" is the same job.
        # Without this, the second click is a second fifty lines and a second
        # fifty charges.
        UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_bulk_jobs_idempotency"
        ),
        Index("ix_bulk_jobs_org", "organization_id", "created_at"),
        CheckConstraint("recipient_count >= 0", name="ck_bulk_jobs_recipient_count"),
        currency_check("bulk_jobs"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(
        sa_column=Column(
            ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
    )
    #: `SET NULL`: the purchase outlives the administrator who made it.
    created_by_user_id: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    idempotency_key: str = Field(sa_column=Column(String(200), nullable=False))
    product_id: UUID = Field(
        sa_column=Column(
            ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
        )
    )
    #: The published market this was bought in, which names both the seller and
    #: the currency — the same thing `quotes.sales_market_id` records, for the
    #: same reason. Frozen at planning: an order's seller must not change after
    #: the fact, and re-deriving it later would let a market republished under a
    #: different entity rewrite who sold last quarter's lines.
    sales_market_id: UUID = Field(
        sa_column=Column(
            ForeignKey("sales_markets.id", ondelete="RESTRICT"), nullable=False
        )
    )
    state: BulkJobState = Field(
        default=BulkJobState.PLANNED,
        sa_column=_enum(BulkJobState, "bulk_job_state", BulkJobState.PLANNED),
    )
    currency: str = Field(sa_column=currency_column())
    #: The per-line price, frozen when the job was planned. A bulk job priced
    #: from the catalog at provisioning time would charge fifty people at
    #: whatever the price became while the worker was running.
    unit_amount: Decimal = Field(sa_column=money_column())
    recipient_count: int = Field(sa_column=Column(Integer, nullable=False))
    reserved_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    provisioned_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    failed_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    unknown_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    invalid_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    cancelled_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    #: The order every item's line hangs from. Null until funding succeeds for
    #: at least one line — a job that could fund nobody never becomes an order.
    order_id: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("orders.id", ondelete="RESTRICT"), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class BulkJobItem(SQLModel, table=True):
    """One recipient's line: funded, ordered and provisioned on its own."""

    __tablename__ = "bulk_job_items"
    __table_args__ = (
        # One line per person per job. The same person appearing twice in one
        # submission is a mistake in the selection, not two lines.
        UniqueConstraint("job_id", "person_id", name="uq_bulk_job_items_person"),
        # One order item is one line. Belt and braces against a resumed apply
        # attaching a second item to the same purchase.
        Index(
            "ux_bulk_job_items_order_item",
            "order_item_id",
            unique=True,
            postgresql_where=text("order_item_id IS NOT NULL"),
            sqlite_where=text("order_item_id IS NOT NULL"),
        ),
        Index("ix_bulk_job_items_state", "job_id", "state"),
        CheckConstraint("attempts >= 0", name="ck_bulk_job_items_attempts"),
        CheckConstraint(
            "(state = 'invalid' AND error_code IS NOT NULL) OR state <> 'invalid'",
            name="ck_bulk_job_items_invalid_reason",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    job_id: UUID = Field(
        sa_column=Column(
            ForeignKey("bulk_jobs.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    #: `RESTRICT`: a person who has been sold a line is not deletable, and
    #: chunk 22 archives rather than deletes for the same reason.
    person_id: UUID = Field(
        sa_column=Column(
            ForeignKey("organization_people.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
    )
    state: BulkItemState = Field(
        default=BulkItemState.PENDING,
        sa_column=_enum(BulkItemState, "bulk_item_state", BulkItemState.PENDING),
    )
    #: The hold for this line alone. One reservation per recipient is what makes
    #: a partial cancellation releasable without touching anybody else's line.
    reservation_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("ledger_reservations.id", ondelete="RESTRICT"), nullable=True
        ),
    )
    order_item_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=True
        ),
    )
    #: A stable code the dashboard localizes — why this one recipient did not
    #: get a line, in a form somebody can act on.
    error_code: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    attempts: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    provisioned_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ActivationRequest(SQLModel, table=True):
    """An invitation for one recipient to claim one line.

    **Not an installation, and not an attachment.** This row says a request was
    made and, perhaps, claimed. Whether a profile reached a handset is chunk
    15's `esim_installations`; whether a network ever saw it is `carrier_lines`.
    The three disagree in the field constantly — a claimed request with no
    installation is the ordinary state of somebody who has not opened the app
    yet — and a dashboard that merged them would report staff as connected on
    the strength of an email.
    """

    __tablename__ = "activation_requests"
    __table_args__ = (
        # One live request per line. Re-sending is an update to this row, not a
        # second token that would let two people claim the same line.
        Index(
            "ux_activation_requests_live",
            "bulk_job_item_id",
            unique=True,
            postgresql_where=text("state IN ('pending', 'sent')"),
            sqlite_where=text("state IN ('pending', 'sent')"),
        ),
        UniqueConstraint("token_hash", name="uq_activation_requests_token"),
        Index("ix_activation_requests_org", "organization_id", "state"),
        CheckConstraint(
            "(state = 'redeemed' AND redeemed_at IS NOT NULL) "
            "OR (state <> 'redeemed' AND redeemed_at IS NULL)",
            name="ck_activation_requests_redeemed_at",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(
        sa_column=Column(
            ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
    )
    bulk_job_item_id: UUID = Field(
        sa_column=Column(
            ForeignKey("bulk_job_items.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    person_id: UUID = Field(
        sa_column=Column(
            ForeignKey("organization_people.id", ondelete="RESTRICT"), nullable=False
        )
    )
    #: SHA-256 of the token. The token itself is shown once, to one recipient,
    #: and never stored — a table of live invitation tokens is a table of
    #: credentials, and this one is read by every administrator of the tenant.
    token_hash: str = Field(sa_column=Column(String(64), nullable=False))
    state: ActivationRequestState = Field(
        default=ActivationRequestState.PENDING,
        sa_column=_enum(
            ActivationRequestState,
            "activation_request_state",
            ActivationRequestState.PENDING,
        ),
    )
    #: Where it was sent. Frozen at issue, because a person's email changing
    #: later does not change who was invited.
    delivered_to: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    sent_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    #: Who claimed it. This is the moment a recipient becomes a user of ours.
    redeemed_by_user_id: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    redeemed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    revoked_reason: str | None = Field(
        default=None, sa_column=Column(String(120), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
