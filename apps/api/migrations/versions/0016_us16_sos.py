"""US-16 SOS alerts and durable per-channel dispatch queue.

Revision ID: 0016_us16_sos
Revises: 0015_us15_checkins
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_us16_sos"
down_revision: str | None = "0015_us15_checkins"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str):
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    status = _enum("sos_status", "active", "resolved", "cancelled")
    channel = _enum(
        "sos_notification_channel",
        "push",
        "email",
        "whatsapp_operator",
        "whatsapp_family",
    )
    event = _enum("sos_notification_event", "triggered", "cancelled")
    delivery = _enum("sos_notification_status", "pending", "sent", "failed")
    for enum in (status, channel, event, delivery):
        enum.create(bind, checkfirst=True)
    op.create_table(
        "sos_alerts",
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
        sa.Column("status", status, nullable=False, server_default="active"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolved_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_sos_alerts_user_id", "sos_alerts", ["user_id"])
    op.create_index(
        "ix_sos_alerts_client_generated_id",
        "sos_alerts",
        ["client_generated_id"],
        unique=True,
    )
    op.create_index("ix_sos_alerts_timestamp", "sos_alerts", ["timestamp"])
    op.create_index("ix_sos_alerts_status", "sos_alerts", ["status"])
    op.create_table(
        "sos_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "sos_alert_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sos_alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", channel, nullable=False),
        sa.Column("event", event, nullable=False, server_default="triggered"),
        sa.Column("status", delivery, nullable=False, server_default="pending"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(255), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("admin_queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "sos_alert_id", "channel", "event", name="uq_sos_notification_event_channel"
        ),
    )
    op.create_index(
        "ix_sos_notifications_sos_alert_id", "sos_notifications", ["sos_alert_id"]
    )
    op.create_index("ix_sos_notifications_status", "sos_notifications", ["status"])
    op.create_index(
        "ix_sos_notifications_admin_queued_at", "sos_notifications", ["admin_queued_at"]
    )


def downgrade() -> None:
    op.drop_table("sos_notifications")
    op.drop_table("sos_alerts")
    bind = op.get_bind()
    for name, values in reversed(
        (
            ("sos_status", ("active", "resolved", "cancelled")),
            (
                "sos_notification_channel",
                ("push", "email", "whatsapp_operator", "whatsapp_family"),
            ),
            ("sos_notification_event", ("triggered", "cancelled")),
            ("sos_notification_status", ("pending", "sent", "failed")),
        )
    ):
        _enum(name, *values).drop(bind, checkfirst=True)
