"""Versioned voice tariffs (US-31, chunk 09).

A call's price depends on **where it starts** as well as where it ends, and the
two calling modes start in different kinds of place:

- an **internet** call originates from a network DamDam does not own, identified
  by the customer's country at the time;
- a **carrier** call originates from the *visited network* the eSIM is attached
  to, which is a roaming fact, not a billing address.

`VOICE-EXPANSION.md` requires those to be distinguishable, and they are, by
`origin_kind`. A tariff that recorded only "origin: NG" could not tell a
customer roaming in Nigeria on a carrier line from one sitting in Lagos making
an internet call, and those are different costs to us.

**Versions are immutable and never overwritten.** A rate change is a new tariff
version with its own effective window; a quote pins the version it was priced
from, so a later change cannot rewrite what somebody was quoted — the same rule
`product_prices` already applies to plan prices.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now
from app.catalog.market import PublicationStatus
from app.money import currency_check, currency_column, money_column, rate_column


def _enum(
    enum_type: type[Enum], name: str, default: Enum | None = None
) -> "Column[Any]":
    return Column(
        SAEnum(
            enum_type,
            name=name,
            values_callable=lambda choices: [choice.value for choice in choices],
        ),
        nullable=False,
        server_default=None if default is None else default.value,
    )


class OriginKind(str, Enum):
    """Where a call starts, and in what sense.

    `CARRIER_VISITED_NETWORK` is a roaming fact and `INTERNET` is a network
    location. Recording only the country would conflate them, and they price
    differently because they cost us differently.
    """

    INTERNET = "internet"
    CARRIER_VISITED_NETWORK = "carrier_visited_network"


class DestinationKind(str, Enum):
    MOBILE = "mobile"
    LANDLINE = "landline"
    #: Priced separately and, by default, not sold at all — premium ranges are
    #: where an unbounded bill comes from.
    PREMIUM = "premium"


class Tariff(SQLModel, table=True):
    """One immutable, currency-explicit version of a product's call rates."""

    __tablename__ = "tariffs"
    __table_args__ = (
        currency_check("tariffs"),
        UniqueConstraint(
            "product_id", "currency", "version", name="uq_tariffs_version"
        ),
        CheckConstraint("version >= 1", name="ck_tariffs_version"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_tariffs_window",
        ),
        CheckConstraint(
            "status = 'draft' OR (evidence_reference IS NOT NULL "
            "AND verified_at IS NOT NULL)",
            name="ck_tariffs_evidence",
        ),
        # At most one published version per product/currency at a time. Two
        # live tariffs is not a pricing decision, it is a race about which one
        # a quote happened to read.
        Index(
            "ux_tariffs_published",
            "product_id",
            "currency",
            unique=True,
            postgresql_where=text("status = 'published' AND effective_to IS NULL"),
            sqlite_where=text("status = 'published' AND effective_to IS NULL"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    product_id: UUID = Field(
        sa_column=Column(
            ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    currency: str = Field(sa_column=currency_column())
    version: int = Field(default=1, sa_column=Column(Integer, nullable=False))
    status: PublicationStatus = Field(
        default=PublicationStatus.DRAFT,
        sa_column=_enum(
            PublicationStatus, "publication_status", PublicationStatus.DRAFT
        ),
    )
    effective_from: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    effective_to: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    evidence_reference: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    verified_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class TariffRate(SQLModel, table=True):
    """One origin/destination pair's price within a tariff version.

    `origin_country` is nullable so a tariff can price "from anywhere" without
    enumerating every country, but `origin_kind` never is: a rate that does not
    say whether it applies to an internet call or a roaming carrier call is a
    rate nobody can select correctly.
    """

    __tablename__ = "tariff_rates"
    __table_args__ = (
        UniqueConstraint(
            "tariff_id",
            "origin_kind",
            "origin_country",
            "destination_country",
            "destination_kind",
            name="uq_tariff_rates_pair",
        ),
        CheckConstraint(
            "per_minute_amount >= 0 AND setup_amount >= 0",
            name="ck_tariff_rates_not_negative",
        ),
        CheckConstraint(
            "minimum_seconds >= 0 AND increment_seconds >= 1",
            name="ck_tariff_rates_increments",
        ),
        Index(
            "ix_tariff_rates_lookup",
            "tariff_id",
            "destination_country",
            "destination_kind",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tariff_id: UUID = Field(
        sa_column=Column(
            ForeignKey("tariffs.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    origin_kind: OriginKind = Field(sa_column=_enum(OriginKind, "voice_origin_kind"))
    #: `NULL` means "any origin of this kind". A specific country wins over it;
    #: see `select_rate`.
    origin_country: str | None = Field(
        default=None, sa_column=Column(String(2), nullable=True)
    )
    destination_country: str = Field(sa_column=Column(String(2), nullable=False))
    destination_kind: DestinationKind = Field(
        sa_column=_enum(DestinationKind, "voice_destination_kind")
    )
    per_minute_amount: Decimal = Field(sa_column=rate_column())
    setup_amount: Decimal = Field(sa_column=money_column())
    #: Billing increments. A supplier charging per 60s while we quote per second
    #: is a margin leak, and quoting per 60s while charging per second is a
    #: customer overcharge; both are recorded rather than assumed.
    minimum_seconds: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    increment_seconds: int = Field(
        default=60, sa_column=Column(Integer, nullable=False, server_default="60")
    )


class RateNotFoundError(LookupError):
    """No rate covers this origin and destination, so no call may be priced."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def select_rate(
    rates: list[TariffRate],
    origin_kind: OriginKind,
    origin_country: str | None,
    destination_country: str,
    destination_kind: DestinationKind,
) -> TariffRate:
    """Pick the rate that applies, most specific first.

    Specificity order is deliberate and total, so two runs never disagree:

    1. exact origin country **and** matching origin kind
    2. any-origin (`origin_country IS NULL`) of the matching origin kind
    3. nothing — which raises rather than falling back to a different origin
       kind

    Never falling back across `origin_kind` is the important half. A carrier
    roaming rate is not a substitute for a missing internet rate; using one
    because it happens to be there prices a call at a number that describes a
    different call.
    """
    matching_kind = [
        rate
        for rate in rates
        if rate.origin_kind is origin_kind
        and rate.destination_country == destination_country
        and rate.destination_kind is destination_kind
    ]
    if origin_country is not None:
        exact = [
            rate for rate in matching_kind if rate.origin_country == origin_country
        ]
        if exact:
            return exact[0]
    wildcard = [rate for rate in matching_kind if rate.origin_country is None]
    if wildcard:
        return wildcard[0]
    raise RateNotFoundError(
        f"no {origin_kind.value} rate to {destination_country}/"
        f"{destination_kind.value} from {origin_country or 'any'}"
    )
