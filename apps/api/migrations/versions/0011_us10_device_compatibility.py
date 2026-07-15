"""US-10 device eSIM compatibility log.

Revision ID: 0011_us10_device_compatibility
Revises: 0010_us09_retail_payments
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_us10_device_compatibility"
down_revision: str | None = "0010_us09_retail_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The "platform" enum already exists (created in 0001_us01_auth for
# users.platform) — referenced here with create_type=False, not
# recreated.
platform = postgresql.ENUM("ios", "android", name="platform", create_type=False)


def upgrade() -> None:
    op.create_table(
        "device_compatibility_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("platform", platform, nullable=False),
        sa.Column("device_model", sa.String(100), nullable=False),
        sa.Column("os_version", sa.String(20), nullable=True),
        sa.Column("esim_supported", sa.Boolean(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_device_compatibility_log_user_id",
        "device_compatibility_log",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_device_compatibility_log_user_id", table_name="device_compatibility_log"
    )
    op.drop_table("device_compatibility_log")
