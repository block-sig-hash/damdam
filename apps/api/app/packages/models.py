from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Numeric
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now


class PackageSource(str, Enum):
    RETAIL = "retail"
    HTO_MANIFEST = "hto_manifest"


class PackageStatus(str, Enum):
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
