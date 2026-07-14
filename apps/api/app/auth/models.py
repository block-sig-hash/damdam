from datetime import date as Date
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
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


class OrganizationType(str, Enum):
    HTO_OPERATOR = "hto_operator"
    ENTERPRISE = "enterprise"
    GOVERNMENT = "government"


class ManifestStatus(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    PARTIALLY_ORDERED = "partially_ordered"
    PROVISIONED = "provisioned"


class ManifestValidationStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    DUPLICATE_WARNING = "duplicate_warning"


class ManifestOrderStatus(str, Enum):
    AWAITING_PAYMENT = "awaiting_payment"
    PAID = "paid"
    PROVISIONING = "provisioning"
    PROVISIONED = "provisioned"


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
    departure_date: Date | None = Field(default=None, index=True)
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


class Organization(SQLModel, table=True):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint(
            "(org_type = 'hto_operator' AND nahcon_licence_number IS NOT NULL) "
            "OR (org_type != 'hto_operator' AND nahcon_licence_number IS NULL)",
            name="ck_organizations_hto_licence",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    org_type: OrganizationType = Field(
        sa_column=Column(
            SAEnum(
                OrganizationType,
                name="organization_type",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        )
    )
    name: str = Field(max_length=255)
    primary_contact_name: str = Field(max_length=100)
    email: str = Field(
        sa_column=Column(String(255), unique=True, nullable=False, index=True)
    )
    password_hash: str = Field(max_length=255)
    phone_number: str = Field(max_length=14)
    nahcon_licence_number: str | None = Field(default=None, max_length=50)
    email_verified: bool = Field(default=False)
    approval_status: HTOApprovalStatus = Field(
        default=HTOApprovalStatus.PENDING,
        sa_column=Column(
            SAEnum(
                HTOApprovalStatus,
                name="organization_approval_status",
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


class OrganizationRefreshToken(SQLModel, table=True):
    __tablename__ = "organization_refresh_tokens"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(foreign_key="organizations.id", index=True)
    token_hash: str = Field(
        sa_column=Column(String(64), unique=True, nullable=False, index=True)
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )
    revoked_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class Manifest(SQLModel, table=True):
    __tablename__ = "manifests"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(
        sa_column=Column(
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    name: str | None = Field(default=None, max_length=255)
    status: ManifestStatus = Field(
        default=ManifestStatus.DRAFT,
        sa_column=Column(
            SAEnum(
                ManifestStatus,
                name="manifest_status",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        ),
    )
    total_rows: int = Field(default=0)
    valid_rows: int = Field(default=0)
    uploaded_file_url: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ManifestPilgrim(SQLModel, table=True):
    __tablename__ = "manifest_pilgrims"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    manifest_id: UUID = Field(
        sa_column=Column(
            ForeignKey("manifests.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    first_name: str = Field(max_length=100)
    last_name: str = Field(max_length=100)
    phone_number: str = Field(max_length=14, index=True)
    passport_number: str | None = Field(default=None, max_length=50)
    seat_number: str | None = Field(default=None, max_length=10)
    row_number: int = Field(sa_column=Column(Integer, nullable=False))
    validation_status: ManifestValidationStatus = Field(
        sa_column=Column(
            SAEnum(
                ManifestValidationStatus,
                name="manifest_validation_status",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        )
    )
    validation_error: str | None = Field(default=None, max_length=255)
    family_group_id: UUID | None = Field(default=None)
    manifest_order_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("manifest_orders.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
    )
    user_id: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    activation_code: str | None = Field(
        default=None,
        sa_column=Column(String(8), unique=True, nullable=True, index=True),
    )
    activation_code_used: bool = Field(default=False)
    activation_code_expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    activation_link_sent_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    esim_incompatible_flag: bool = Field(default=False)


class PricingTier(SQLModel, table=True):
    __tablename__ = "pricing_tiers"
    __table_args__ = (
        CheckConstraint(
            "(is_group_tier AND min_group_size IS NOT NULL "
            "AND max_group_size IS NOT NULL "
            "AND min_group_size >= 2 AND max_group_size >= min_group_size) "
            "OR (NOT is_group_tier AND min_group_size IS NULL "
            "AND max_group_size IS NULL)",
            name="ck_pricing_tiers_group_bounds",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=50)
    usd_reference_price: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False)
    )
    data_gb: int
    pstn_minutes: int
    is_group_tier: bool = Field(default=False)
    min_group_size: int | None = Field(default=None)
    max_group_size: int | None = Field(default=None)
    wholesale_usd_price: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False)
    )
    active: bool = Field(default=True)
    ngn_price: Decimal = Field(sa_column=Column(Numeric(12, 2), nullable=False))


class PricingTierPriceChange(SQLModel, table=True):
    __tablename__ = "pricing_tier_price_changes"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    pricing_tier_id: UUID = Field(
        sa_column=Column(
            ForeignKey("pricing_tiers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    admin_id: UUID = Field(
        sa_column=Column(ForeignKey("admin_users.id"), nullable=False)
    )
    old_ngn_price: Decimal = Field(sa_column=Column(Numeric(12, 2), nullable=False))
    new_ngn_price: Decimal = Field(sa_column=Column(Numeric(12, 2), nullable=False))
    changed_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ManifestOrder(SQLModel, table=True):
    __tablename__ = "manifest_orders"
    __table_args__ = (
        CheckConstraint("pilgrim_count > 0", name="ck_manifest_orders_count"),
        CheckConstraint(
            "wholesale_price_ngn > 0 AND total_ngn > 0",
            name="ck_manifest_orders_amounts",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    manifest_id: UUID = Field(
        sa_column=Column(
            ForeignKey("manifests.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    pricing_tier_id: UUID = Field(
        sa_column=Column(
            ForeignKey("pricing_tiers.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
    )
    pilgrim_count: int
    wholesale_price_ngn: Decimal = Field(
        sa_column=Column(Numeric(12, 2), nullable=False)
    )
    total_ngn: Decimal = Field(sa_column=Column(Numeric(12, 2), nullable=False))
    status: ManifestOrderStatus = Field(
        default=ManifestOrderStatus.AWAITING_PAYMENT,
        sa_column=Column(
            SAEnum(
                ManifestOrderStatus,
                name="manifest_order_status",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        ),
    )
    invoice_url: str | None = Field(default=None, max_length=500)
    invoice_object_key: str | None = Field(default=None, max_length=500)
    invoice_email_sent_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    payment_confirmed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    payment_confirmed_by: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True
        ),
    )
    provisioning_enqueued_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
