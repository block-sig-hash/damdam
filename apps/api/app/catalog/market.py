"""Where we may sell, what a product covers, and what a supplier can actually do.

US-31, chunk 09. Four questions that the legacy schema answered with one column
(`destination_country`) and that are not the same question:

| Question | Table | Why it is separate |
|---|---|---|
| Where may we *sell* this? | `sales_markets` | Regulatory and merchant (D2/D3/D4) |
| Where does the data *work*? | `product_coverage` | A supplier roaming footprint |
| What number does the customer get? | `number_policies` | A numbering plan |
| Which can carry a *call*? | `provider_offerings` | A per-SKU capability |

Collapsing them is the specific error `prd.md` §10 and `AGENTS.md` both warn
about: **aggregate supplier data coverage is not native-voice eligibility.** A
supplier's data footprint covering ninety countries says nothing about whether a
voice-capable profile can be issued in any of them, and selling a voice plan on
that basis produces a customer with a line that cannot make calls.

Nothing here is purchasable until it is published, and nothing may be published
without recorded evidence — see `PublicationStatus`.
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now
from app.money import currency_check, currency_column


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


class PublicationStatus(str, Enum):
    """The only state in which something can be bought is `PUBLISHED`.

    `VERIFIED` exists as a separate step on purpose. Recording the evidence that
    a market or a capability is real is a different act from deciding to sell
    there, and collapsing them means the moment somebody files evidence the
    product goes on sale. D2, D3 and D4 are all open; publication is where they
    bite.
    """

    DRAFT = "draft"
    VERIFIED = "verified"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"


class NumberType(str, Enum):
    NONE = "none"
    MOBILE = "mobile"
    LANDLINE = "landline"


class NumberAssignment(str, Enum):
    NONE = "none"
    NEW_ASSIGNED = "new_assigned"


class SalesMarket(SQLModel, table=True):
    """A country we are allowed to sell into, and the currency we sell in.

    Selling is not the same as coverage. This row answers "may we take money
    from someone here, in this currency, as this legal entity" — which depends
    on D2 (cleared markets), D3 (selling entity) and D4 (a merchant account),
    all open. So a market may exist in `DRAFT`, carry evidence in `VERIFIED`,
    and still not be sellable.
    """

    __tablename__ = "sales_markets"
    __table_args__ = (
        currency_check("sales_markets"),
        UniqueConstraint(
            "country", "currency", name="uq_sales_markets_country_currency"
        ),
        # Evidence is not optional for anything past draft. A market cannot be
        # verified by someone remembering that it is fine.
        CheckConstraint(
            "status = 'draft' OR (evidence_reference IS NOT NULL "
            "AND verified_at IS NOT NULL)",
            name="ck_sales_markets_evidence",
        ),
        # Publishing additionally needs a seller. D3 is open and
        # `legal_entities` is deliberately unseeded, so in practice this
        # constraint is what stops a market going live before that decision.
        CheckConstraint(
            "status <> 'published' OR legal_entity_id IS NOT NULL",
            name="ck_sales_markets_published_needs_seller",
        ),
        CheckConstraint(
            "country ~ '^[A-Z]{2}$'", name="ck_sales_markets_country"
        ).ddl_if(dialect="postgresql"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    country: str = Field(sa_column=Column(String(2), nullable=False, index=True))
    currency: str = Field(sa_column=currency_column())
    status: PublicationStatus = Field(
        default=PublicationStatus.DRAFT,
        sa_column=_enum(
            PublicationStatus, "publication_status", PublicationStatus.DRAFT
        ),
    )
    legal_entity_id: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("legal_entities.id"), nullable=True, index=True),
    )
    #: Points at the artifact that established this — a decision record, a
    #: signed vendor confirmation. Free text on purpose: what counts as
    #: evidence differs per market, and a foreign key here would force one
    #: shape onto all of them.
    evidence_reference: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    verified_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    published_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class CoverageRegion(SQLModel, table=True):
    """A named group of countries a region product is sold against."""

    __tablename__ = "coverage_regions"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    code: str = Field(sa_column=Column(String(32), nullable=False, unique=True))
    name: str = Field(sa_column=Column(String(200), nullable=False))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class RegionCountry(SQLModel, table=True):
    __tablename__ = "region_countries"
    __table_args__ = (
        UniqueConstraint("region_id", "country", name="uq_region_countries"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    region_id: UUID = Field(
        sa_column=Column(
            ForeignKey("coverage_regions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    country: str = Field(sa_column=Column(String(2), nullable=False))


class ProductCoverage(SQLModel, table=True):
    """A country whose *visited network* this product's data works on.

    Deliberately not called "destination": for a data plan the country that
    matters is where the handset attaches, for a call it is where the other
    party is, and for a number it is where the number is issued. Three different
    countries, three different columns, three different tables.
    """

    __tablename__ = "product_coverage"
    __table_args__ = (
        UniqueConstraint("product_id", "country", name="uq_product_coverage"),
        Index("ix_product_coverage_country", "country"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    product_id: UUID = Field(
        sa_column=Column(
            ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    country: str = Field(sa_column=Column(String(2), nullable=False))
    #: What established this coverage. A supplier's published list is a claim,
    #: not proof, and D1 is open.
    evidence_reference: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )


class ProviderOffering(SQLModel, table=True):
    """What one supplier will actually sell us for one product, and what it does.

    Every capability is a separate boolean because suppliers advertise them
    separately and a plan that needs one cannot be fulfilled by an offering that
    lacks it. `AGENTS.md` states the rule this table exists to enforce: *a
    data-only adapter cannot satisfy a native-voice plan.*

    Capabilities default to **false**. An unverified capability is an absent
    capability; defaulting to true would make every new offering claim
    everything until somebody remembered to say otherwise.
    """

    __tablename__ = "provider_offerings"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "provider", "provider_sku", name="uq_provider_offerings"
        ),
        CheckConstraint(
            "status = 'draft' OR (evidence_reference IS NOT NULL "
            "AND verified_at IS NOT NULL)",
            name="ck_provider_offerings_evidence",
        ),
        CheckConstraint(
            "usage_latency_seconds IS NULL OR usage_latency_seconds >= 0",
            name="ck_provider_offerings_latency",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    product_id: UUID = Field(
        sa_column=Column(
            ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    provider: str = Field(sa_column=Column(String(32), nullable=False))
    provider_sku: str = Field(sa_column=Column(String(128), nullable=False))
    status: PublicationStatus = Field(
        default=PublicationStatus.DRAFT,
        sa_column=_enum(
            PublicationStatus, "publication_status", PublicationStatus.DRAFT
        ),
    )

    supports_data: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    #: The one that matters most. Aggregate data coverage never implies this.
    supports_native_voice: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default="false")
    )
    supports_internet_voice: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default="false")
    )
    supports_number_assignment: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default="false")
    )
    supports_topup: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default="false")
    )
    supports_suspension: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default="false")
    )
    supports_spending_enforcement: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default="false")
    )
    #: How stale a usage reading from this supplier can be. Feeds the "last
    #: updated" the UI is required to show (design-system.md §17.4).
    usage_latency_seconds: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
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


class DeviceEligibilityRule(SQLModel, table=True):
    """What a device must be for this product to be installable on it.

    One row per product, because "needs an eSIM" is a property of what is being
    sold. An internet-only calling product sets `requires_esim = false` and is
    therefore sellable to someone whose phone cannot take one — which is the
    whole point of `VOICE-EXPANSION.md`'s internet-only offer.
    """

    __tablename__ = "device_eligibility_rules"
    __table_args__ = (
        UniqueConstraint("product_id", name="uq_device_eligibility_product"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    product_id: UUID = Field(
        sa_column=Column(
            ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    requires_esim: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default="true")
    )
    requires_unlocked_device: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default="true")
    )
    notes: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )


class NumberPolicy(SQLModel, table=True):
    """Which number, from which country, of which kind — or none at all.

    Separate from coverage because the country a number is issued in is not the
    country the service is used in, and a customer roaming across a region keeps
    one number throughout.
    """

    __tablename__ = "number_policies"
    __table_args__ = (
        UniqueConstraint("product_id", name="uq_number_policies_product"),
        CheckConstraint(
            "(number_type = 'none' AND number_country IS NULL "
            "AND assignment = 'none') "
            "OR (number_type <> 'none' AND number_country IS NOT NULL)",
            name="ck_number_policies_country",
        ),
        CheckConstraint(
            "number_country IS NULL OR number_country ~ '^[A-Z]{2}$'",
            name="ck_number_policies_country_shape",
        ).ddl_if(dialect="postgresql"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    product_id: UUID = Field(
        sa_column=Column(
            ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    number_type: NumberType = Field(
        default=NumberType.NONE,
        sa_column=_enum(NumberType, "number_type", NumberType.NONE),
    )
    number_country: str | None = Field(
        default=None, sa_column=Column(String(2), nullable=True)
    )
    assignment: NumberAssignment = Field(
        default=NumberAssignment.NONE,
        sa_column=_enum(NumberAssignment, "number_assignment", NumberAssignment.NONE),
    )
    evidence_reference: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
