"""Automated data-retention state, summaries, and audit idempotency.

Revision ID: 0023_data_retention
Revises: 0022_pricing_tier_destination
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_data_retention"
down_revision: str | None = "0022_pricing_tier_destination"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE user_status ADD VALUE IF NOT EXISTS 'pending_deletion'")
    op.add_column(
        "users",
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_users_deletion_requested_at", "users", ["deletion_requested_at"]
    )

    for table in ("check_ins", "sos_alerts", "call_logs"):
        op.drop_constraint(f"{table}_user_id_fkey", table, type_="foreignkey")
        op.alter_column(table, "user_id", nullable=True)
        op.create_foreign_key(
            f"{table}_user_id_fkey",
            table,
            "users",
            ["user_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.add_column(
        "check_ins",
        sa.Column(
            "location_retention_due_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.execute(
        "UPDATE check_ins SET location_retention_due_at = "
        "GREATEST(timestamp, COALESCE((SELECT MAX(packages.expires_at) "
        "FROM packages WHERE packages.user_id = check_ins.user_id), timestamp)) "
        "+ INTERVAL '90 days'"
    )
    op.alter_column("check_ins", "location_retention_due_at", nullable=False)
    op.create_index(
        "ix_check_ins_location_retention_due_at",
        "check_ins",
        ["location_retention_due_at"],
    )

    op.create_table(
        "usage_polls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "esim_profile_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("polled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_used_gb", sa.Numeric(6, 2), nullable=False),
        sa.Column("poll_success", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "ix_usage_polls_esim_profile_id", "usage_polls", ["esim_profile_id"]
    )
    op.create_index("ix_usage_polls_polled_at", "usage_polls", ["polled_at"])

    op.create_table(
        "daily_usage_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "esim_profile_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("summary_date", sa.Date(), nullable=False),
        sa.Column("first_polled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_data_used_gb", sa.Numeric(6, 2), nullable=False),
        sa.Column("last_data_used_gb", sa.Numeric(6, 2), nullable=False),
        sa.Column("successful_poll_count", sa.Integer(), nullable=False),
        sa.Column("failed_poll_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "esim_profile_id",
            "summary_date",
            name="uq_daily_usage_summary_profile_date",
        ),
    )
    op.create_index(
        "ix_daily_usage_summaries_esim_profile_id",
        "daily_usage_summaries",
        ["esim_profile_id"],
    )
    op.create_index(
        "ix_daily_usage_summaries_summary_date",
        "daily_usage_summaries",
        ["summary_date"],
    )

    op.add_column(
        "transactions",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.alter_column("transactions", "created_at", server_default=None)
    op.create_index("ix_transactions_created_at", "transactions", ["created_at"])

    op.add_column(
        "audit_log", sa.Column("idempotency_key", sa.String(255), nullable=True)
    )
    op.create_index(
        "ix_audit_log_idempotency_key",
        "audit_log",
        ["idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_idempotency_key", table_name="audit_log")
    op.drop_column("audit_log", "idempotency_key")
    op.drop_index("ix_transactions_created_at", table_name="transactions")
    op.drop_column("transactions", "created_at")
    op.drop_table("daily_usage_summaries")
    op.drop_table("usage_polls")
    op.drop_index("ix_check_ins_location_retention_due_at", table_name="check_ins")
    op.drop_column("check_ins", "location_retention_due_at")

    for table in ("check_ins", "sos_alerts", "call_logs"):
        op.execute(sa.text(f"DELETE FROM {table} WHERE user_id IS NULL"))
        op.drop_constraint(f"{table}_user_id_fkey", table, type_="foreignkey")
        op.alter_column(table, "user_id", nullable=False)
        op.create_foreign_key(
            f"{table}_user_id_fkey",
            table,
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )

    op.drop_index("ix_users_deletion_requested_at", table_name="users")
    op.drop_column("users", "deletion_requested_at")
    op.execute(
        "UPDATE users SET status = 'suspended' WHERE status = 'pending_deletion'"
    )
    op.execute("ALTER TABLE users ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE users ALTER COLUMN status TYPE VARCHAR(20) USING status::text"
    )
    op.execute("DROP TYPE user_status")
    op.execute("CREATE TYPE user_status AS ENUM ('active', 'suspended')")
    op.execute(
        "ALTER TABLE users ALTER COLUMN status TYPE user_status "
        "USING status::user_status"
    )
    op.execute("ALTER TABLE users ALTER COLUMN status SET DEFAULT 'active'")
