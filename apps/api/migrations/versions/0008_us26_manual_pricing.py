"""US-26 manual admin-triggered Naira pricing, replacing daily_price_cache.

Revision ID: 0008_us26_manual_pricing
Revises: 0007_us07_pilgrim_activation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_us26_manual_pricing"
down_revision: str | None = "0007_us07_pilgrim_activation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pricing_tiers",
        sa.Column("ngn_price", sa.Numeric(12, 2), nullable=True),
    )
    # Backfill from each tier's most recent daily_price_cache row before that
    # table is dropped below, so existing tiers keep their last-known price
    # instead of the column going NOT NULL against unset data.
    op.execute(
        """
        UPDATE pricing_tiers AS pt
        SET ngn_price = latest.ngn_price
        FROM (
            SELECT DISTINCT ON (pricing_tier_id) pricing_tier_id, ngn_price
            FROM daily_price_cache
            ORDER BY pricing_tier_id, date DESC
        ) AS latest
        WHERE pt.id = latest.pricing_tier_id
        """
    )
    op.alter_column("pricing_tiers", "ngn_price", nullable=False)

    op.create_table(
        "pricing_tier_price_changes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "pricing_tier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pricing_tiers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "admin_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id"),
            nullable=False,
        ),
        sa.Column("old_ngn_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("new_ngn_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_pricing_tier_price_changes_pricing_tier_id",
        "pricing_tier_price_changes",
        ["pricing_tier_id"],
    )

    op.drop_index(
        "ix_daily_price_cache_pricing_tier_id", table_name="daily_price_cache"
    )
    op.drop_index("ix_daily_price_cache_date", table_name="daily_price_cache")
    op.drop_table("daily_price_cache")


def downgrade() -> None:
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

    op.drop_index(
        "ix_pricing_tier_price_changes_pricing_tier_id",
        table_name="pricing_tier_price_changes",
    )
    op.drop_table("pricing_tier_price_changes")
    op.drop_column("pricing_tiers", "ngn_price")
