from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String
from sqlmodel import Field, SQLModel

from app.auth.models import Platform, utc_now


class FamilyContact(SQLModel, table=True):
    __tablename__ = "family_contacts"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
            index=True,
        )
    )
    phone_number: str = Field(sa_column=Column(String(14), nullable=False))
    name: str | None = Field(default=None, max_length=100)
    notified_of_nomination: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class DeviceToken(SQLModel, table=True):
    """Current FCM registration for one signed-in app installation."""

    __tablename__ = "device_tokens"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    fcm_token: str = Field(
        sa_column=Column(String(4096), unique=True, nullable=False)
    )
    platform: Platform = Field(
        sa_column=Column(
            Enum(
                Platform,
                name="platform",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        )
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
