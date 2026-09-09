"""Seller and product identities (US-28, data-model.md §6.44).

Minimal on purpose. Chunk 09 builds the supported-market catalog, eligibility
and immutable quotes; these are the identities those need to point at, and
nothing more.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now
from app.money import currency_check, currency_column, money_column


def _enum(enum_type: type[Enum], name: str, nullable: bool = False) -> "Column[Any]":
    return Column(
        SAEnum(
            enum_type,
            name=name,
            values_callable=lambda choices: [choice.value for choice in choices],
        ),
        nullable=nullable,
    )


class ProductKind(str, Enum):
    DATA = "data"
    VOICE = "voice"
    BUNDLE = "bundle"


class LegalEntity(SQLModel, table=True):
    """The legal entity that sells an order -- the seller party.

    **No row is seeded.** Which entity sells, and from where, is decision D3,
    which is open. The table exists so an order can name its seller from the
    first day one is decided, rather than having the answer implied by whichever
    bank account a payment landed in.
    """

    __tablename__ = "legal_entities"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    code: str = Field(sa_column=Column(String(16), nullable=False, unique=True))
    name: str = Field(sa_column=Column(String(200), nullable=False))
    country: str = Field(sa_column=Column(String(2), nullable=False))
    active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class Product(SQLModel, table=True):
    """What is sold, independent of what it costs or where it is sold."""

    __tablename__ = "products"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    sku: str = Field(sa_column=Column(String(64), nullable=False, unique=True))
    name: str = Field(sa_column=Column(String(200), nullable=False))
    kind: ProductKind = Field(sa_column=_enum(ProductKind, "product_kind"))
    active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ProductPrice(SQLModel, table=True):
    """A versioned, currency-explicit price for one product from one seller.

    Rows are append-only: a price change is a new version with a new effective
    window, never an update. An order item copies the amount it was sold at, so
    a later version cannot rewrite what someone was charged.
    """

    __tablename__ = "product_prices"
    __table_args__ = (
        currency_check("product_prices"),
        Index(
            "ux_product_prices_version",
            "product_id",
            "legal_entity_id",
            "currency",
            "version",
            unique=True,
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    product_id: UUID = Field(
        sa_column=Column(
            ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    legal_entity_id: UUID = Field(
        sa_column=Column(ForeignKey("legal_entities.id"), nullable=False, index=True)
    )
    currency: str = Field(sa_column=currency_column())
    amount: Decimal = Field(sa_column=money_column())
    version: int = Field(default=1)
    effective_from: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    effective_to: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
