"""US-25 AC-25.3 package chaining (validity_days, superseded status) and
AC-25.4 audit_log table.

Revision ID: 0018_us25_chaining_audit
Revises: 0017_us22_sos_sms_fallback
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_us25_chaining_audit"
down_revision: str | None = "0017_us22_sos_sms_fallback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE package_status ADD VALUE IF NOT EXISTS 'superseded'")
    op.add_column(
        "pricing_tiers",
        sa.Column(
            "validity_days", sa.Integer(), nullable=False, server_default="30"
        ),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reference", sa.String(255), nullable=True),
        sa.Column("outcome", sa.String(64), nullable=False),
        sa.Column("details", sa.String(500), nullable=True),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_event_type", "audit_log", ["event_type"])
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index("ix_audit_log_outcome", "audit_log", ["outcome"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_outcome", table_name="audit_log")
    op.drop_index("ix_audit_log_user_id", table_name="audit_log")
    op.drop_index("ix_audit_log_event_type", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_column("pricing_tiers", "validity_days")

    # PostgreSQL cannot drop one enum value in place. No packages can exist
    # with status='superseded' in a pre-US-25 schema, so this rebuild is
    # always safe -- same pattern as migration 0017's channel enum rollback.
    op.execute("DELETE FROM packages WHERE status = 'superseded'")
    op.execute("ALTER TABLE packages ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE packages ALTER COLUMN status TYPE VARCHAR(20) USING status::text"
    )
    op.execute("DROP TYPE package_status")
    op.execute(
        "CREATE TYPE package_status AS ENUM "
        "('pending', 'active', 'expired', 'cancelled')"
    )
    op.execute(
        "ALTER TABLE packages ALTER COLUMN status TYPE package_status "
        "USING status::package_status"
    )
    op.execute(
        "ALTER TABLE packages ALTER COLUMN status SET DEFAULT 'active'"
    )
