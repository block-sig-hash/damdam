from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String, Uuid
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now


class WhatsAppDeliveryStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    FAILED = "failed"


class SmsDeliveryStatus(str, Enum):
    SENT = "sent"
    FAILED = "failed"


class CheckIn(SQLModel, table=True):
    __tablename__ = "check_ins"

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
    received_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    location_retention_due_at: datetime = Field(
        default_factory=lambda: utc_now() + timedelta(days=90),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class CheckInNotification(SQLModel, table=True):
    __tablename__ = "check_in_notifications"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    check_in_id: UUID = Field(
        sa_column=Column(
            ForeignKey("check_ins.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        )
    )
    whatsapp_status: WhatsAppDeliveryStatus = Field(
        default=WhatsAppDeliveryStatus.PENDING,
        sa_column=Column(
            SAEnum(
                WhatsAppDeliveryStatus,
                name="checkin_whatsapp_status",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        ),
    )
    whatsapp_message_id: str | None = Field(
        default=None,
        sa_column=Column(String(255), nullable=True, unique=True, index=True),
    )
    whatsapp_attempted_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    whatsapp_delivered_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    whatsapp_failure_reason: str | None = Field(default=None, max_length=255)
    fallback_due_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    sms_status: SmsDeliveryStatus | None = Field(
        default=None,
        sa_column=Column(
            SAEnum(
                SmsDeliveryStatus,
                name="checkin_sms_status",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=True,
        ),
    )
    sms_message_id: str | None = Field(default=None, max_length=255)
    sms_fallback_sent_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    sms_failure_reason: str | None = Field(default=None, max_length=255)
    sms_attempt_count: int = Field(default=0)
    admin_queued_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
