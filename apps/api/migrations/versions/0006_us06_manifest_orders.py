"""US-06 manifest grouping, pricing, and multi-order purchasing.

Revision ID: 0006_us06_manifest_orders
Revises: 0005_us05_manifests
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_us06_manifest_orders"
down_revision: str | None = "0005_us05_manifests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

manifest_order_status = sa.Enum(
    "awaiting_payment",
    "paid",
    "provisioning",
    "provisioned",
    name="manifest_order_status",
)


def upgrade() -> None:
    op.create_table(
        "pricing_tiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("usd_reference_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("data_gb", sa.Integer(), nullable=False),
        sa.Column("pstn_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "is_group_tier", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("min_group_size", sa.Integer(), nullable=True),
        sa.Column("max_group_size", sa.Integer(), nullable=True),
        sa.Column("wholesale_usd_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint(
            "(is_group_tier AND min_group_size IS NOT NULL "
            "AND max_group_size IS NOT NULL "
            "AND min_group_size >= 2 AND max_group_size >= min_group_size) "
            "OR (NOT is_group_tier AND min_group_size IS NULL "
            "AND max_group_size IS NULL)",
            name="ck_pricing_tiers_group_bounds",
        ),
    )

    op.create_table(
        "daily_price_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "pricing_tier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pricing_tiers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("ngn_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("fx_rate_used", sa.Numeric(10, 4), nullable=False),
        sa.UniqueConstraint(
            "pricing_tier_id", "date", name="uq_daily_price_cache_tier_date"
        ),
    )
    op.create_index(
        "ix_daily_price_cache_pricing_tier_id",
        "daily_price_cache",
        ["pricing_tier_id"],
    )
    op.create_index("ix_daily_price_cache_date", "daily_price_cache", ["date"])

    op.create_table(
        "manifest_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "manifest_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("manifests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "pricing_tier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pricing_tiers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("pilgrim_count", sa.Integer(), nullable=False),
        sa.Column("wholesale_price_ngn", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_ngn", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "status",
            manifest_order_status,
            nullable=False,
            server_default="awaiting_payment",
        ),
        sa.Column("invoice_url", sa.String(500), nullable=True),
        sa.Column("invoice_object_key", sa.String(500), nullable=True),
        sa.Column("invoice_email_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "payment_confirmed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "provisioning_enqueued_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("pilgrim_count > 0", name="ck_manifest_orders_count"),
        sa.CheckConstraint(
            "wholesale_price_ngn > 0 AND total_ngn > 0",
            name="ck_manifest_orders_amounts",
        ),
    )
    op.create_index(
        "ix_manifest_orders_manifest_id", "manifest_orders", ["manifest_id"]
    )
    op.create_index(
        "ix_manifest_orders_pricing_tier_id",
        "manifest_orders",
        ["pricing_tier_id"],
    )

    # US-05 reserved this nullable UUID slot before its target table existed.
    # No pre-US-06 value is valid, so normalize any stray staging values before
    # enforcing referential integrity.
    op.execute(
        "UPDATE manifest_pilgrims SET manifest_order_id = NULL "
        "WHERE manifest_order_id IS NOT NULL"
    )
    op.create_foreign_key(
        "fk_manifest_pilgrims_manifest_order_id",
        "manifest_pilgrims",
        "manifest_orders",
        ["manifest_order_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "manifest_pilgrims",
        sa.Column("activation_link_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("manifest_pilgrims", "activation_link_sent_at")
    op.drop_constraint(
        "fk_manifest_pilgrims_manifest_order_id",
        "manifest_pilgrims",
        type_="foreignkey",
    )
    op.execute(
        "UPDATE manifest_pilgrims SET manifest_order_id = NULL "
        "WHERE manifest_order_id IS NOT NULL"
    )
    op.drop_table("manifest_orders")
    op.drop_table("daily_price_cache")
    op.drop_table("pricing_tiers")
    manifest_order_status.drop(op.get_bind(), checkfirst=True)
