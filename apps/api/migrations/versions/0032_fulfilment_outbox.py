"""Durable outbox, inbox and supplier attempts — US-32, chunk 11.

Revision ID: 0032_fulfilment_outbox
Revises: 0031_ledger_and_reservations

Additive. The legacy `esim_issuance_jobs` path and its Celery scheduling are
untouched; chunk 11 adds the durable mechanism new orders use, and moving the
legacy path onto it is a later chunk's migration, not this one's.

Two constraints carry the chunk's whole purpose:

- `ux_supplier_attempts_live_item` — one *live* attempt per order item, where
  live means in flight, accepted, unknown or held. A second concurrent attempt
  is not a retry; it is a second purchase, and this refuses it in the database
  rather than in a code path somebody can forget to call.
- `uq_supplier_attempts_key` — `(provider, idempotency_key)`. The key names one
  *request*, so a retry reuses it and a fresh decision to buy gets a new one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032_fulfilment_outbox"
down_revision: str | None = "0031_ledger_and_reservations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUMS = (
    ("outbox_status", ("pending", "in_progress", "done", "dead_letter")),
    (
        "attempt_outcome",
        (
            "in_flight",
            "accepted",
            "rejected",
            "outcome_unknown",
            "held_for_review",
        ),
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _ENUMS:
        postgresql.ENUM(*values, name=name, create_type=True).create(
            bind, checkfirst=True
        )

    op.create_table(
        "outbox_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("topic", sa.String(100), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="outbox_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("leased_by", sa.String(100), nullable=True),
        sa.Column("last_error", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("dedupe_key", name="uq_outbox_messages_dedupe"),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_messages_attempts"),
        # A lease without a holder, or a holder without a lease, is a row no
        # recovery logic can reason about.
        sa.CheckConstraint(
            "(status = 'in_progress' AND leased_until IS NOT NULL "
            "AND leased_by IS NOT NULL) "
            "OR (status <> 'in_progress' AND leased_until IS NULL "
            "AND leased_by IS NULL)",
            name="ck_outbox_messages_lease",
        ),
    )
    op.create_index(
        "ix_outbox_messages_claimable",
        "outbox_messages",
        ["status", "available_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_outbox_messages_lease_expiry",
        "outbox_messages",
        ["status", "leased_until"],
    )

    op.create_table(
        "inbox_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disposition", sa.String(200), nullable=True),
        # Providers number their own events, so "evt-1" from two of them is two
        # different events. The pair is the identity.
        sa.UniqueConstraint(
            "source", "external_id", name="uq_inbox_messages_external"
        ),
    )
    op.create_index("ix_inbox_messages_received", "inbox_messages", ["received_at"])

    op.create_table(
        "supplier_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "order_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("order_items.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "outcome",
            postgresql.ENUM(name="attempt_outcome", create_type=False),
            nullable=False,
            server_default="in_flight",
        ),
        sa.Column("provider_reference", sa.String(200), nullable=True),
        sa.Column("review_reason", sa.String(500), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider", "idempotency_key", name="uq_supplier_attempts_key"
        ),
        sa.CheckConstraint("attempt_number >= 1", name="ck_supplier_attempts_number"),
        sa.CheckConstraint(
            "(outcome = 'accepted' AND provider_reference IS NOT NULL) "
            "OR outcome <> 'accepted'",
            name="ck_supplier_attempts_accepted_reference",
        ),
    )
    # One live attempt per order item. This is the double-purchase guard, in
    # the database rather than in a code path.
    op.create_index(
        "ux_supplier_attempts_live_item",
        "supplier_attempts",
        ["order_item_id"],
        unique=True,
        postgresql_where=sa.text(
            "outcome IN ('in_flight', 'accepted', 'outcome_unknown', "
            "'held_for_review')"
        ),
    )
    op.create_index(
        "ix_supplier_attempts_outcome", "supplier_attempts", ["outcome", "created_at"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("supplier_attempts", "inbox_messages", "outbox_messages"):
        op.drop_table(table)
    for name, _ in _ENUMS:
        postgresql.ENUM(name=name, create_type=False).drop(bind, checkfirst=True)
