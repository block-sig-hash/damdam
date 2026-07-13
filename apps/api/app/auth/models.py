from datetime import date, datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, String
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AccountSource(str, Enum):
    DIRECT = "direct"
    HTO_MANIFEST = "hto_manifest"


class Platform(str, Enum):
    IOS = "ios"
    ANDROID = "android"


class UserStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    phone_number: str = Field(
        sa_column=Column(String(14), unique=True, nullable=False, index=True)
    )
    first_name: str = Field(default="", max_length=100)
    last_name: str = Field(default="", max_length=100)
    email: str | None = Field(default=None, max_length=255)
    pin_hash: str | None = Field(default=None, max_length=255)
    pin_failed_attempts: int = Field(default=0)
    pin_locked_until: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    account_source: AccountSource = Field(
        default=AccountSource.DIRECT,
        sa_column=Column(
            SAEnum(
                AccountSource,
                name="account_source",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        ),
    )
    verified_cli: bool = Field(default=False)
    departure_date: date | None = Field(default=None, index=True)
    destination_country: str = Field(default="SA", max_length=2)
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
    status: UserStatus = Field(
        default=UserStatus.ACTIVE,
        sa_column=Column(
            SAEnum(
                UserStatus,
                name="user_status",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        ),
    )
    last_login_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class RefreshToken(SQLModel, table=True):
    __tablename__ = "refresh_tokens"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    token_hash: str = Field(
        sa_column=Column(String(64), unique=True, nullable=False, index=True)
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )
    revoked_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
