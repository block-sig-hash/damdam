from datetime import date, datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String
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


class HTOApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AdminRole(str, Enum):
    ADMIN = "admin"


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


class AdminUser(SQLModel, table=True):
    __tablename__ = "admin_users"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    email: str = Field(
        sa_column=Column(String(255), unique=True, nullable=False, index=True)
    )
    password_hash: str = Field(max_length=255)
    role: AdminRole = Field(
        default=AdminRole.ADMIN,
        sa_column=Column(
            SAEnum(
                AdminRole,
                name="admin_role",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        ),
    )


class HTOOperator(SQLModel, table=True):
    __tablename__ = "hto_operators"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    business_name: str = Field(max_length=255)
    operator_name: str = Field(max_length=100)
    email: str = Field(
        sa_column=Column(String(255), unique=True, nullable=False, index=True)
    )
    password_hash: str = Field(max_length=255)
    phone_number: str = Field(max_length=14)
    nahcon_licence_number: str = Field(max_length=50)
    email_verified: bool = Field(default=False)
    approval_status: HTOApprovalStatus = Field(
        default=HTOApprovalStatus.PENDING,
        sa_column=Column(
            SAEnum(
                HTOApprovalStatus,
                name="hto_approval_status",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        ),
    )
    approved_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    approved_by: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True
        ),
    )
    approval_email_sent_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    approval_whatsapp_sent_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class HTORefreshToken(SQLModel, table=True):
    __tablename__ = "hto_refresh_tokens"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    hto_operator_id: UUID = Field(foreign_key="hto_operators.id", index=True)
    token_hash: str = Field(
        sa_column=Column(String(64), unique=True, nullable=False, index=True)
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )
    revoked_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
