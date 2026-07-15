from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.auth.models import Platform, utc_now


class DeviceCompatibilityEvent(str, Enum):
    COMPATIBILITY_CHECK = "compatibility_check"
    ISSUANCE_ATTEMPT = "issuance_attempt"


class EsimAggregator(str, Enum):
    MONTY_MOBILE = "monty_mobile"
    ESIM_ACCESS = "esim_access"
    ONEGLOBAL = "1global"


class EsimProfileStatus(str, Enum):
    ISSUED = "issued"
    DOWNLOADED = "downloaded"
    ACTIVATED = "activated"


class DeviceCompatibilityLog(SQLModel, table=True):
    __tablename__ = "device_compatibility_log"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    # Reuses the "platform" enum type already created for users.platform
    # (0001_us01_auth) rather than a new one — see migration 0011.
    event_type: DeviceCompatibilityEvent = Field(
        default=DeviceCompatibilityEvent.COMPATIBILITY_CHECK,
        sa_column=Column(
            SAEnum(
                DeviceCompatibilityEvent,
                name="device_compatibility_event",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        ),
    )
    platform: Platform | None = Field(
        default=None,
        sa_column=Column(
            SAEnum(
                Platform,
                name="platform",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=True,
        )
    )
    device_model: str | None = Field(
        default=None, sa_column=Column(String(100), nullable=True)
    )
    os_version: str | None = Field(default=None, max_length=20)
    esim_supported: bool | None = Field(
        default=None, sa_column=Column(Boolean(), nullable=True)
    )
    aggregator: EsimAggregator | None = Field(
        default=None,
        sa_column=Column(
            SAEnum(
                EsimAggregator,
                name="esim_aggregator",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=True,
        ),
    )
    attempt_succeeded: bool | None = Field(
        default=None, sa_column=Column(Boolean(), nullable=True)
    )
    failure_reason: str | None = Field(default=None, max_length=255)
    checked_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class EsimProfile(SQLModel, table=True):
    __tablename__ = "esim_profiles"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    package_id: UUID = Field(
        sa_column=Column(
            ForeignKey("packages.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        )
    )
    aggregator: EsimAggregator = Field(
        sa_column=Column(
            SAEnum(
                EsimAggregator,
                name="esim_aggregator",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        )
    )
    iccid: str = Field(sa_column=Column(String(22), nullable=False))
    activation_code_lpa: str = Field(sa_column=Column(String(255), nullable=False))
    qr_code_url: str = Field(sa_column=Column(String(500), nullable=False))
    status: EsimProfileStatus = Field(
        default=EsimProfileStatus.ISSUED,
        sa_column=Column(
            SAEnum(
                EsimProfileStatus,
                name="esim_profile_status",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        ),
    )
    downloaded_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    activated_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class EsimIssuanceJob(SQLModel, table=True):
    """Persistent retry/admin queue for all-vendor issuance failures."""

    __tablename__ = "esim_issuance_jobs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    package_id: UUID = Field(
        sa_column=Column(
            ForeignKey("packages.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        )
    )
    attempt_count: int = Field(
        default=0, sa_column=Column(Integer(), nullable=False)
    )
    next_attempt_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    admin_queued_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    success_notified_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_error: str | None = Field(default=None, max_length=255)
