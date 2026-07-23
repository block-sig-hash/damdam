from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now


class SOSStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class SOSNotificationChannel(str, Enum):
    PUSH = "push"
    EMAIL = "email"
    WHATSAPP_OPERATOR = "whatsapp_operator"
    WHATSAPP_FAMILY = "whatsapp_family"
    SMS_FAMILY = "sms_family"


class SOSNotificationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class SOSNotificationEvent(str, Enum):
    TRIGGERED = "triggered"
    CANCELLED = "cancelled"


class SOSAlert(SQLModel, table=True):
    __tablename__ = "sos_alerts"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    client_generated_id: UUID = Field(
        sa_column=Column(Uuid, nullable=False, unique=True, index=True)
    )
    timestamp: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )
    latitude: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(9, 6), nullable=True)
    )
    longitude: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(9, 6), nullable=True)
    )
    status: SOSStatus = Field(
        default=SOSStatus.ACTIVE,
        sa_column=Column(
            SAEnum(
                SOSStatus,
                name="sos_status",
                values_callable=lambda values: [value.value for value in values],
            ),
            nullable=False,
            index=True,
        ),
    )
    resolved_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    resolved_by: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
        ),
    )


class SOSNotification(SQLModel, table=True):
    __tablename__ = "sos_notifications"
    __table_args__ = (
        UniqueConstraint(
            "sos_alert_id", "channel", "event", name="uq_sos_notification_event_channel"
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    sos_alert_id: UUID = Field(
        sa_column=Column(
            ForeignKey("sos_alerts.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    channel: SOSNotificationChannel = Field(
        sa_column=Column(
            SAEnum(
                SOSNotificationChannel,
                name="sos_notification_channel",
                values_callable=lambda values: [value.value for value in values],
            ),
            nullable=False,
        )
    )
    event: SOSNotificationEvent = Field(
        default=SOSNotificationEvent.TRIGGERED,
        sa_column=Column(
            SAEnum(
                SOSNotificationEvent,
                name="sos_notification_event",
                values_callable=lambda values: [value.value for value in values],
            ),
            nullable=False,
        ),
    )
    status: SOSNotificationStatus = Field(
        default=SOSNotificationStatus.PENDING,
        sa_column=Column(
            SAEnum(
                SOSNotificationStatus,
                name="sos_notification_status",
                values_callable=lambda values: [value.value for value in values],
            ),
            nullable=False,
            index=True,
        ),
    )
    sent_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    failure_reason: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    retry_count: int = Field(default=0)
    # The three fields below apply only to the WHATSAPP_FAMILY channel's
    # AC-22.3 SMS fallback (§6.27): whatsapp_message_id correlates the same
    # shared Meta delivery webhook already used for check-in;
    # whatsapp_delivered_at (distinct from `status`, which stays SENT once
    # Meta accepts the send) suppresses the fallback if delivery is
    # confirmed within the window; fallback_due_at marks when the
    # SMS_FAMILY row becomes eligible.
    whatsapp_message_id: str | None = Field(
        default=None,
        sa_column=Column(String(255), nullable=True, unique=True, index=True),
    )
    whatsapp_delivered_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    fallback_due_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    admin_queued_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
