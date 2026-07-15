from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.auth.models import Platform, utc_now


class DeviceCompatibilityLog(SQLModel, table=True):
    __tablename__ = "device_compatibility_log"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    # Reuses the "platform" enum type already created for users.platform
    # (0001_us01_auth) rather than a new one — see migration 0011.
    platform: Platform = Field(
        sa_column=Column(
            SAEnum(
                Platform,
                name="platform",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        )
    )
    device_model: str = Field(sa_column=Column(String(100), nullable=False))
    os_version: str | None = Field(default=None, max_length=20)
    esim_supported: bool = Field(sa_column=Column(Boolean(), nullable=False))
    checked_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
