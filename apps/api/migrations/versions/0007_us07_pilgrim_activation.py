"""US-07 pilgrim activation: materialize packages on redemption.

Revision ID: 0007_us07_pilgrim_activation
Revises: 0006_us06_manifest_orders
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_us07_pilgrim_activation"
down_revision: str | None = "0006_us06_manifest_orders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

package_source = sa.Enum("retail", "hto_manifest", name="package_source")
package_status = sa.Enum("active", "expired", "cancelled", name="package_status")


def upgrade() -> None:
    op.create_table(
        "packages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "pricing_tier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pricing_tiers.id"),
            nullable=False,
        ),
        sa.Column("source", package_source, nullable=False),
        sa.Column(
            "status", package_status, nullable=False, server_default="active"
        ),
        sa.Column("group_size", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("data_gb_total", sa.Integer(), nullable=False),
        sa.Column("data_gb_remaining", sa.Numeric(6, 2), nullable=False),
        sa.Column("pstn_minutes_total", sa.Integer(), nullable=False),
        sa.Column("pstn_minutes_remaining", sa.Numeric(6, 2), nullable=False),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_packages_user_id", "packages", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_packages_user_id", table_name="packages")
    op.drop_table("packages")
    package_status.drop(op.get_bind(), checkfirst=True)
    package_source.drop(op.get_bind(), checkfirst=True)
