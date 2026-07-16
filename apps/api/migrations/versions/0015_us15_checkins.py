"""US-15 check-ins and WhatsApp-to-SMS notification tracking.

Revision ID: 0015_us15_checkins
Revises: 0014_us14_voice_calling
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_us15_checkins"
down_revision: str | None = "0014_us14_voice_calling"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

whatsapp_status = postgresql.ENUM(
    "pending",
    "accepted",
    "delivered",
    "failed",
    name="checkin_whatsapp_status",
    create_type=False,
)
sms_status = postgresql.ENUM(
    "sent", "failed", name="checkin_sms_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    whatsapp_status.create(bind, checkfirst=True)
    sms_status.create(bind, checkfirst=True)
    op.create_table(
        "check_ins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "client_generated_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
        ),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_check_ins_user_id", "check_ins", ["user_id"])
    op.create_index(
        "ix_check_ins_client_generated_id",
        "check_ins",
        ["client_generated_id"],
        unique=True,
    )
    op.create_index("ix_check_ins_timestamp", "check_ins", ["timestamp"])
    op.create_table(
        "check_in_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "check_in_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("check_ins.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "whatsapp_status",
            whatsapp_status,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("whatsapp_message_id", sa.String(255), nullable=True, unique=True),
        sa.Column("whatsapp_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("whatsapp_delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("whatsapp_failure_reason", sa.String(255), nullable=True),
        sa.Column("fallback_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sms_status", sms_status, nullable=True),
        sa.Column("sms_message_id", sa.String(255), nullable=True),
        sa.Column("sms_fallback_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sms_failure_reason", sa.String(255), nullable=True),
        sa.Column(
            "sms_attempt_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("admin_queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_check_in_notifications_check_in_id",
        "check_in_notifications",
        ["check_in_id"],
        unique=True,
    )
    op.create_index(
        "ix_check_in_notifications_whatsapp_message_id",
        "check_in_notifications",
        ["whatsapp_message_id"],
        unique=True,
    )
    op.create_index(
        "ix_check_in_notifications_fallback_due_at",
        "check_in_notifications",
        ["fallback_due_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_check_in_notifications_fallback_due_at",
        table_name="check_in_notifications",
    )
    op.drop_index(
        "ix_check_in_notifications_whatsapp_message_id",
        table_name="check_in_notifications",
    )
    op.drop_index(
        "ix_check_in_notifications_check_in_id",
        table_name="check_in_notifications",
    )
    op.drop_table("check_in_notifications")
    op.drop_index("ix_check_ins_timestamp", table_name="check_ins")
    op.drop_index("ix_check_ins_client_generated_id", table_name="check_ins")
    op.drop_index("ix_check_ins_user_id", table_name="check_ins")
    op.drop_table("check_ins")
    sms_status.drop(op.get_bind(), checkfirst=True)
    whatsapp_status.drop(op.get_bind(), checkfirst=True)
