"""Bulk jobs, per-recipient items and activation requests — US-40.

Revision ID: 0042_bulk_provisioning
Revises: 0041_organization_people

**Purely additive.** Three new tables, no column added to an existing table, no
row touched and nothing dropped. `orders`, `order_items` and
`ledger_reservations` are referenced by foreign key and otherwise untouched: a
bulk job creates ordinary order items, one per recipient, which is chunk 05's
quantity-one invariant used exactly as intended rather than worked around.

Four constraints carry this chunk's guarantees:

- `uq_bulk_jobs_idempotency` — one submission is one job. A double-clicked "buy
  for these fifty people" is the same job, and without this it is a second fifty
  lines and a second fifty charges.
- `uq_bulk_job_items_person` — one line per person per job. The same colleague
  selected twice is a mistake in the selection, not two lines.
- `ux_bulk_job_items_order_item` — one order item belongs to one bulk item. A
  resumed run that re-entered the ordering path cannot attach a second line to
  the same purchase.
- `ux_activation_requests_live` — one live invitation per line. Re-sending
  updates that row rather than minting a second token, because two live tokens
  for one line is two people who can claim it.

`activation_requests.token_hash` is a hash and the column is unique. The token
itself is returned once, to one recipient, and never stored: a table of live
invitation tokens is a table of credentials, and this one is readable by every
administrator of the tenant.

**Integration numbering.** The submitted migration was `0039`, based on chunk
22's submitted `0038`. The accepted dependency chain already uses 0039–0041,
so this integrated migration follows `0041_organization_people` as `0042`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042_bulk_provisioning"
down_revision: str | None = "0041_organization_people"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_ENUMS = (
    (
        "bulk_job_state",
        (
            "planned",
            "funded",
            "provisioning",
            "completed",
            "partially_completed",
            "cancelled",
        ),
    ),
    (
        "bulk_item_state",
        (
            "pending",
            "invalid",
            "reserved",
            "ordered",
            "provisioned",
            "failed",
            "unknown",
            "cancelled",
        ),
    ),
    (
        "activation_request_state",
        ("pending", "sent", "redeemed", "expired", "revoked"),
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _NEW_ENUMS:
        postgresql.ENUM(*values, name=name, create_type=True).create(
            bind, checkfirst=True
        )

    op.create_table(
        "bulk_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "sales_market_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sales_markets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "state",
            postgresql.ENUM(name="bulk_job_state", create_type=False),
            nullable=False,
            server_default="planned",
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("unit_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("recipient_count", sa.Integer(), nullable=False),
        sa.Column("reserved_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "provisioned_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unknown_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancelled_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_bulk_jobs_idempotency"
        ),
        sa.CheckConstraint(
            "recipient_count >= 0", name="ck_bulk_jobs_recipient_count"
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_bulk_jobs_currency_iso4217"
        ),
    )
    op.create_index(
        "ix_bulk_jobs_org", "bulk_jobs", ["organization_id", "created_at"]
    )

    op.create_table(
        "bulk_job_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bulk_jobs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization_people.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "state",
            postgresql.ENUM(name="bulk_item_state", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "reservation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ledger_reservations.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "order_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("order_items.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provisioned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "person_id", name="uq_bulk_job_items_person"),
        sa.CheckConstraint("attempts >= 0", name="ck_bulk_job_items_attempts"),
        sa.CheckConstraint(
            "(state = 'invalid' AND error_code IS NOT NULL) OR state <> 'invalid'",
            name="ck_bulk_job_items_invalid_reason",
        ),
    )
    op.create_index(
        "ux_bulk_job_items_order_item",
        "bulk_job_items",
        ["order_item_id"],
        unique=True,
        postgresql_where=sa.text("order_item_id IS NOT NULL"),
    )
    op.create_index(
        "ix_bulk_job_items_state", "bulk_job_items", ["job_id", "state"]
    )

    op.create_table(
        "activation_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "bulk_job_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bulk_job_items.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization_people.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "state",
            postgresql.ENUM(name="activation_request_state", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("delivered_to", sa.String(255), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "redeemed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_activation_requests_token"),
        sa.CheckConstraint(
            "(state = 'redeemed' AND redeemed_at IS NOT NULL) "
            "OR (state <> 'redeemed' AND redeemed_at IS NULL)",
            name="ck_activation_requests_redeemed_at",
        ),
    )
    op.create_index(
        "ux_activation_requests_live",
        "activation_requests",
        ["bulk_job_item_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('pending', 'sent')"),
    )
    op.create_index(
        "ix_activation_requests_org",
        "activation_requests",
        ["organization_id", "state"],
    )


def downgrade() -> None:
    """Drops only what `upgrade` created.

    The orders and order items a bulk job produced **stay**. They are ordinary
    order rows: dropping them because the bulk surface was removed is exactly
    what `AGENTS.md` forbids, and a customer's purchase history does not belong
    to the screen that created it.
    """
    op.drop_table("activation_requests")
    op.drop_table("bulk_job_items")
    op.drop_table("bulk_jobs")
    bind = op.get_bind()
    for name, _ in _NEW_ENUMS:
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
