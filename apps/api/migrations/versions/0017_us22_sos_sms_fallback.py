"""US-22 SMS fallback for the SOS family WhatsApp channel.

Revision ID: 0017_us22_sos_sms_fallback
Revises: 0016_us16_sos
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_us22_sos_sms_fallback"
down_revision: str | None = "0016_us16_sos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE sos_notification_channel ADD VALUE IF NOT EXISTS 'sms_family'"
    )
    op.add_column(
        "sos_notifications",
        sa.Column("whatsapp_message_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "sos_notifications",
        sa.Column("whatsapp_delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sos_notifications",
        sa.Column("fallback_due_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_sos_notifications_whatsapp_message_id",
        "sos_notifications",
        ["whatsapp_message_id"],
    )
    op.create_index(
        "ix_sos_notifications_whatsapp_message_id",
        "sos_notifications",
        ["whatsapp_message_id"],
    )
    op.create_index(
        "ix_sos_notifications_fallback_due_at", "sos_notifications", ["fallback_due_at"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sos_notifications_fallback_due_at", table_name="sos_notifications"
    )
    op.drop_index(
        "ix_sos_notifications_whatsapp_message_id", table_name="sos_notifications"
    )
    op.drop_constraint(
        "uq_sos_notifications_whatsapp_message_id",
        "sos_notifications",
        type_="unique",
    )
    op.drop_column("sos_notifications", "fallback_due_at")
    op.drop_column("sos_notifications", "whatsapp_delivered_at")
    op.drop_column("sos_notifications", "whatsapp_message_id")

    # PostgreSQL cannot drop one enum value in place. No sms_family rows can
    # exist in a pre-US-22 schema, so this rebuild is always safe.
    op.execute(
        "DELETE FROM sos_notifications WHERE channel = 'sms_family'"
    )
    op.execute(
        "ALTER TABLE sos_notifications ALTER COLUMN channel TYPE VARCHAR(30) "
        "USING channel::text"
    )
    op.execute("DROP TYPE sos_notification_channel")
    op.execute(
        "CREATE TYPE sos_notification_channel AS ENUM "
        "('push', 'email', 'whatsapp_operator', 'whatsapp_family')"
    )
    op.execute(
        "ALTER TABLE sos_notifications ALTER COLUMN channel TYPE "
        "sos_notification_channel USING channel::sos_notification_channel"
    )
