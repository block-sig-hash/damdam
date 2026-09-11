"""Supported-market catalog, versioned tariffs and immutable quotes — US-31.

Revision ID: 0030_catalog_and_quotes
Revises: 0029_organization_memberships

Additive. No existing table is altered and no row is touched: the legacy
`pricing_tiers` / `packages` path keeps working exactly as it does today, and
chunk 11 is what moves purchases onto these tables.

**Nothing is seeded.** Not one market, product, offering or tariff. D1 (carrier
capability), D2 (markets and coverage), D3 (selling entity) and D4 (merchant
approval) are all open, and a seeded catalog is a claim that some market is
sellable. The CHECK constraints here are how those open decisions express
themselves: a market cannot leave draft without recorded evidence, and cannot be
published without a legal entity — and `legal_entities` is itself deliberately
unseeded by chunk 05.

The two triggers are the substance of "immutable quotes". A quote whose total
can be edited is not a promise, and enforcing that in the service alone means
enforcing it in every future caller as well.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030_catalog_and_quotes"
down_revision: str | None = "0029_organization_memberships"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUMS = (
    ("publication_status", ("draft", "verified", "published", "withdrawn")),
    ("number_type", ("none", "mobile", "landline")),
    ("number_assignment", ("none", "new_assigned")),
    ("voice_origin_kind", ("internet", "carrier_visited_network")),
    ("voice_destination_kind", ("mobile", "landline", "premium")),
    ("quote_status", ("issued", "redeemed", "void")),
)

_QUOTE_TRIGGER = """
CREATE OR REPLACE FUNCTION damdam_quotes_immutable() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'quotes are immutable (quote %)', OLD.id;
    END IF;
    IF OLD.status <> 'issued' AND NEW.status IS DISTINCT FROM OLD.status THEN
        RAISE EXCEPTION 'quote status % is terminal (quote %)', OLD.status, OLD.id;
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
        OR NEW.reference IS DISTINCT FROM OLD.reference
        OR NEW.seller_legal_entity_id IS DISTINCT FROM OLD.seller_legal_entity_id
        OR NEW.sales_market_id IS DISTINCT FROM OLD.sales_market_id
        OR NEW.currency IS DISTINCT FROM OLD.currency
        OR NEW.subtotal_amount IS DISTINCT FROM OLD.subtotal_amount
        OR NEW.tax_amount IS DISTINCT FROM OLD.tax_amount
        OR NEW.tax_configuration_reference
            IS DISTINCT FROM OLD.tax_configuration_reference
        OR NEW.fee_amount IS DISTINCT FROM OLD.fee_amount
        OR NEW.total_amount IS DISTINCT FROM OLD.total_amount
        OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
        OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
        OR NEW.digest IS DISTINCT FROM OLD.digest
    THEN
        RAISE EXCEPTION
            'quotes are immutable: only status and redeemed_at may change (quote %)',
            OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_quotes_immutable
    BEFORE UPDATE OR DELETE ON quotes
    FOR EACH ROW EXECUTE FUNCTION damdam_quotes_immutable();
"""

_QUOTE_ITEM_TRIGGER = """
CREATE OR REPLACE FUNCTION damdam_quote_items_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'quote items are immutable (item %)', OLD.id;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_quote_items_immutable
    BEFORE UPDATE OR DELETE ON quote_items
    FOR EACH ROW EXECUTE FUNCTION damdam_quote_items_immutable();
"""


def _publication(name: str = "publication_status") -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _ENUMS:
        postgresql.ENUM(*values, name=name, create_type=True).create(
            bind, checkfirst=True
        )

    op.create_table(
        "sales_markets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("country", sa.String(2), nullable=False, index=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", _publication(), nullable=False, server_default="draft"),
        sa.Column(
            "legal_entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("legal_entities.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "country", "currency", name="uq_sales_markets_country_currency"
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_sales_markets_currency_iso4217"
        ),
        sa.CheckConstraint("country ~ '^[A-Z]{2}$'", name="ck_sales_markets_country"),
        # Evidence is not optional past draft, and publishing needs a seller.
        # These two are where D2 and D3 stop being paperwork.
        sa.CheckConstraint(
            "status = 'draft' OR (evidence_reference IS NOT NULL "
            "AND verified_at IS NOT NULL)",
            name="ck_sales_markets_evidence",
        ),
        sa.CheckConstraint(
            "status <> 'published' OR legal_entity_id IS NOT NULL",
            name="ck_sales_markets_published_needs_seller",
        ),
    )

    op.create_table(
        "coverage_regions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "region_countries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "region_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("coverage_regions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("country", sa.String(2), nullable=False),
        sa.UniqueConstraint("region_id", "country", name="uq_region_countries"),
    )

    op.create_table(
        "product_coverage",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.UniqueConstraint("product_id", "country", name="uq_product_coverage"),
    )
    op.create_index("ix_product_coverage_country", "product_coverage", ["country"])

    op.create_table(
        "provider_offerings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_sku", sa.String(128), nullable=False),
        sa.Column("status", _publication(), nullable=False, server_default="draft"),
        # Every capability defaults to false. An unverified capability is an
        # absent one; defaulting to true would make each new offering claim
        # everything until somebody remembered to say otherwise.
        *[
            sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false())
            for name in (
                "supports_data",
                "supports_native_voice",
                "supports_internet_voice",
                "supports_number_assignment",
                "supports_topup",
                "supports_suspension",
                "supports_spending_enforcement",
            )
        ],
        sa.Column("usage_latency_seconds", sa.Integer(), nullable=True),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "product_id", "provider", "provider_sku", name="uq_provider_offerings"
        ),
        sa.CheckConstraint(
            "status = 'draft' OR (evidence_reference IS NOT NULL "
            "AND verified_at IS NOT NULL)",
            name="ck_provider_offerings_evidence",
        ),
        sa.CheckConstraint(
            "usage_latency_seconds IS NULL OR usage_latency_seconds >= 0",
            name="ck_provider_offerings_latency",
        ),
    )

    op.create_table(
        "device_eligibility_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "requires_esim", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "requires_unlocked_device",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.UniqueConstraint("product_id", name="uq_device_eligibility_product"),
    )

    op.create_table(
        "number_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "number_type",
            postgresql.ENUM(name="number_type", create_type=False),
            nullable=False,
            server_default="none",
        ),
        sa.Column("number_country", sa.String(2), nullable=True),
        sa.Column(
            "assignment",
            postgresql.ENUM(name="number_assignment", create_type=False),
            nullable=False,
            server_default="none",
        ),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.UniqueConstraint("product_id", name="uq_number_policies_product"),
        sa.CheckConstraint(
            "(number_type = 'none' AND number_country IS NULL "
            "AND assignment = 'none') "
            "OR (number_type <> 'none' AND number_country IS NOT NULL)",
            name="ck_number_policies_country",
        ),
        sa.CheckConstraint(
            "number_country IS NULL OR number_country ~ '^[A-Z]{2}$'",
            name="ck_number_policies_country_shape",
        ),
    )

    op.create_table(
        "tariffs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", _publication(), nullable=False, server_default="draft"),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "product_id", "currency", "version", name="uq_tariffs_version"
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_tariffs_currency_iso4217"
        ),
        sa.CheckConstraint("version >= 1", name="ck_tariffs_version"),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_tariffs_window",
        ),
        sa.CheckConstraint(
            "status = 'draft' OR (evidence_reference IS NOT NULL "
            "AND verified_at IS NOT NULL)",
            name="ck_tariffs_evidence",
        ),
    )
    # One live tariff per product and currency. Two is not a pricing decision,
    # it is a race about which one a quote happened to read.
    op.create_index(
        "ux_tariffs_published",
        "tariffs",
        ["product_id", "currency"],
        unique=True,
        postgresql_where=sa.text("status = 'published' AND effective_to IS NULL"),
    )

    op.create_table(
        "tariff_rates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tariff_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tariffs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "origin_kind",
            postgresql.ENUM(name="voice_origin_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("origin_country", sa.String(2), nullable=True),
        sa.Column("destination_country", sa.String(2), nullable=False),
        sa.Column(
            "destination_kind",
            postgresql.ENUM(name="voice_destination_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("per_minute_amount", sa.Numeric(20, 10), nullable=False),
        sa.Column("setup_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "minimum_seconds", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "increment_seconds", sa.Integer(), nullable=False, server_default="60"
        ),
        sa.UniqueConstraint(
            "tariff_id",
            "origin_kind",
            "origin_country",
            "destination_country",
            "destination_kind",
            name="uq_tariff_rates_pair",
        ),
        sa.CheckConstraint(
            "per_minute_amount >= 0 AND setup_amount >= 0",
            name="ck_tariff_rates_not_negative",
        ),
        sa.CheckConstraint(
            "minimum_seconds >= 0 AND increment_seconds >= 1",
            name="ck_tariff_rates_increments",
        ),
    )
    op.create_index(
        "ix_tariff_rates_lookup",
        "tariff_rates",
        ["tariff_id", "destination_country", "destination_kind"],
    )

    op.create_table(
        "quotes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("reference", sa.String(32), nullable=False, unique=True),
        sa.Column(
            "seller_legal_entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("legal_entities.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "sales_market_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sales_markets.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("tax_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("tax_configuration_reference", sa.String(200), nullable=True),
        sa.Column("fee_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("total_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="quote_status", create_type=False),
            nullable=False,
            server_default="issued",
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.UniqueConstraint("id", "currency", name="uq_quotes_id_currency"),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_quotes_currency_iso4217"
        ),
        sa.CheckConstraint("expires_at > issued_at", name="ck_quotes_window"),
        sa.CheckConstraint(
            "subtotal_amount >= 0 AND tax_amount >= 0 AND fee_amount >= 0 "
            "AND total_amount >= 0",
            name="ck_quotes_amounts_not_negative",
        ),
        sa.CheckConstraint(
            "total_amount = subtotal_amount + tax_amount + fee_amount",
            name="ck_quotes_total_is_sum",
        ),
        sa.CheckConstraint(
            "(status = 'redeemed' AND redeemed_at IS NOT NULL) "
            "OR (status <> 'redeemed' AND redeemed_at IS NULL)",
            name="ck_quotes_redeemed_at",
        ),
    )
    op.create_index("ix_quotes_status_expiry", "quotes", ["status", "expires_at"])

    op.create_table(
        "quote_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("quote_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "product_price_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_prices.id"),
            nullable=False,
        ),
        sa.Column(
            "tariff_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tariffs.id"),
            nullable=True,
        ),
        sa.Column(
            "recipient_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_currency", sa.String(3), nullable=False),
        sa.Column("unit_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("line_amount", sa.Numeric(20, 6), nullable=False),
        # Composite foreign key: a line cannot exist in a currency its parent
        # quote is not in, so a cross-currency total cannot be assembled.
        sa.ForeignKeyConstraint(
            ["quote_id", "unit_currency"],
            ["quotes.id", "quotes.currency"],
            name="fk_quote_items_quote_currency",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "unit_currency ~ '^[A-Z]{3}$'", name="ck_quote_items_unit_currency_iso4217"
        ),
        sa.CheckConstraint("quantity >= 1", name="ck_quote_items_quantity"),
        sa.CheckConstraint(
            "unit_amount >= 0 AND line_amount >= 0",
            name="ck_quote_items_amounts_not_negative",
        ),
        sa.CheckConstraint(
            "line_amount = unit_amount * quantity", name="ck_quote_items_line_total"
        ),
    )
    op.create_index("ix_quote_items_quote", "quote_items", ["quote_id"])

    op.execute(sa.text(_QUOTE_TRIGGER))
    op.execute(sa.text(_QUOTE_ITEM_TRIGGER))


def downgrade() -> None:
    bind = op.get_bind()
    op.execute(
        sa.text("DROP TRIGGER IF EXISTS trg_quote_items_immutable ON quote_items")
    )
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_quotes_immutable ON quotes"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS damdam_quote_items_immutable()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS damdam_quotes_immutable()"))
    for table in (
        "quote_items",
        "quotes",
        "tariff_rates",
        "tariffs",
        "number_policies",
        "device_eligibility_rules",
        "provider_offerings",
        "product_coverage",
        "region_countries",
        "coverage_regions",
        "sales_markets",
    ):
        op.drop_table(table)
    for name, _ in _ENUMS:
        postgresql.ENUM(name=name, create_type=False).drop(bind, checkfirst=True)
