from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Numeric, String, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now


class PackageSource(str, Enum):
    RETAIL = "retail"
    HTO_MANIFEST = "hto_manifest"


class PackageStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class Package(SQLModel, table=True):
    __tablename__ = "packages"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    pricing_tier_id: UUID = Field(
        sa_column=Column(ForeignKey("pricing_tiers.id"), nullable=False)
    )
    source: PackageSource = Field(
        sa_column=Column(
            SAEnum(
                PackageSource,
                name="package_source",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        )
    )
    status: PackageStatus = Field(
        default=PackageStatus.ACTIVE,
        sa_column=Column(
            SAEnum(
                PackageStatus,
                name="package_status",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        ),
    )
    group_size: int = Field(default=1)
    data_gb_total: int
    data_gb_remaining: Decimal = Field(sa_column=Column(Numeric(6, 2), nullable=False))
    pstn_minutes_total: int
    pstn_minutes_remaining: Decimal = Field(
        sa_column=Column(Numeric(6, 2), nullable=False)
    )
    purchased_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class PaymentProcessor(str, Enum):
    PAYSTACK = "paystack"
    FLUTTERWAVE = "flutterwave"


class PaymentMethod(str, Enum):
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    USSD = "ussd"
    INVOICE = "invoice"


class TransactionStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class Transaction(SQLModel, table=True):
    __tablename__ = "transactions"
    __table_args__ = (
        Index(
            "ux_transactions_processor_reference",
            "processor_reference",
            unique=True,
            postgresql_where=text("processor_reference IS NOT NULL"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    package_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("packages.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    manifest_order_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("manifest_orders.id", ondelete="SET NULL"), nullable=True
        ),
    )
    processor: PaymentProcessor = Field(
        default=PaymentProcessor.PAYSTACK,
        sa_column=Column(
            SAEnum(
                PaymentProcessor,
                name="payment_processor",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        ),
    )
    processor_reference: str | None = Field(
        default=None,
        sa_column=Column(String(100), nullable=True),
    )
    amount_ngn: Decimal = Field(sa_column=Column(Numeric(12, 2), nullable=False))
    payment_method: PaymentMethod | None = Field(
        default=None,
        sa_column=Column(
            SAEnum(
                PaymentMethod,
                name="payment_method",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=True,
        ),
    )
    status: TransactionStatus = Field(
        default=TransactionStatus.PENDING,
        sa_column=Column(
            SAEnum(
                TransactionStatus,
                name="transaction_status",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        ),
    )
    webhook_payload: dict[str, object] | None = Field(
        default=None,
        sa_column=Column(JSON().with_variant(JSONB, "postgresql"), nullable=True),
    )
    receipt_sent_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
