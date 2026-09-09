"""Core domain identities and separated states -- US-28 (data-model.md §6.44).

Revision ID: 0027_core_domain_model
Revises: 0026_i18n_locales

**Additive only.** No existing table is altered, no column is dropped, no row is
touched and no data is backfilled. Every legacy table -- users, organizations,
packages, pricing_tiers, transactions, esim_profiles, manifests and their
history -- is left exactly as it was, and the new tables start empty.

That is deliberate, not incremental caution. The tables these anchor are used by
chunks 09-11 and 15; backfilling legacy `packages` rows into `orders`,
`order_items` and `entitlements` before any code reads them would mean writing a
translation whose correctness nothing exercises. The phased plan --
add nullable, backfill, then constrain -- is documented in
docs/implementation/CORE-MODEL-UPGRADE.md, and its constraint phase is a later
migration, not this one.

Downgrade drops only what this revision created.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_core_domain_model"
down_revision: str | None = "0026_i18n_locales"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(20, 6)
CURRENCY = sa.String(3)

_NEW_ENUMS = (
    ("product_kind", ("data", "voice", "bundle")),
    ("order_payment_state", ("unpaid", "authorized", "paid", "refunded", "failed")),
    (
        "order_item_provisioning_state",
        (
            "not_started",
            "requested",
            "outcome_unknown",
            "provisioned",
            "failed",
            "cancelled",
        ),
    ),
    ("esim_installation_state", ("not_installed", "installed", "removed")),
    (
        "carrier_line_activation_state",
        ("pending", "activating", "active", "suspended", "terminated"),
    ),
    ("carrier_line_network_state", ("unknown", "attached", "detached")),
)

_NEW_TABLES = (
    "assigned_numbers",
    "carrier_lines",
    "esim_installations",
    "entitlements",
    "order_items",
    "orders",
    "product_prices",
    "products",
    "legal_entities",
)


def _timestamp(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _NEW_ENUMS:
        postgresql.ENUM(*values, name=name, create_type=False).create(
            bind, checkfirst=True
        )

    op.create_table(
        "legal_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _timestamp("created_at"),
    )

    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("sku", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(name="product_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _timestamp("created_at"),
    )

    op.create_table(
        "product_prices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "legal_entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("legal_entities.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("currency", CURRENCY, nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        _timestamp("effective_from"),
        _timestamp("effective_to", nullable=True),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_product_prices_currency_iso4217"
        ),
        sa.CheckConstraint(
            "amount >= 0", name="ck_product_prices_amount_not_negative"
        ),
    )
    op.create_index(
        "ux_product_prices_version",
        "product_prices",
        ["product_id", "legal_entity_id", "currency", "version"],
        unique=True,
    )

    op.create_table(
        "orders",
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
            "payer_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "payer_organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
        sa.Column("currency", CURRENCY, nullable=False),
        sa.Column("total_amount", MONEY, nullable=False),
        sa.Column("settlement_currency", CURRENCY, nullable=True),
        sa.Column("settlement_amount", MONEY, nullable=True),
        sa.Column(
            "payment_state",
            postgresql.ENUM(name="order_payment_state", create_type=False),
            nullable=False,
            server_default="unpaid",
        ),
        _timestamp("placed_at"),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_orders_currency_iso4217"
        ),
        sa.CheckConstraint(
            "settlement_currency ~ '^[A-Z]{3}$'",
            name="ck_orders_settlement_currency_iso4217",
        ),
        sa.CheckConstraint(
            "(payer_user_id IS NOT NULL AND payer_organization_id IS NULL) "
            "OR (payer_user_id IS NULL AND payer_organization_id IS NOT NULL)",
            name="ck_orders_exactly_one_payer",
        ),
        sa.CheckConstraint("total_amount >= 0", name="ck_orders_total_not_negative"),
        sa.CheckConstraint(
            "(settlement_currency IS NULL AND settlement_amount IS NULL) OR "
            "(settlement_currency IS NOT NULL AND settlement_amount IS NOT NULL)",
            name="ck_orders_settlement_pair",
        ),
        sa.CheckConstraint(
            "settlement_amount >= 0",
            name="ck_orders_settlement_amount_not_negative",
        ),
        sa.UniqueConstraint("id", "currency", name="uq_orders_id_currency"),
    )

    op.create_table(
        "order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "recipient_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("unit_currency", CURRENCY, nullable=False),
        sa.Column("unit_amount", MONEY, nullable=False),
        sa.Column(
            "provisioning_state",
            postgresql.ENUM(name="order_item_provisioning_state", create_type=False),
            nullable=False,
            server_default="not_started",
        ),
        sa.Column("operation_reference", sa.String(64), nullable=True, unique=True),
        sa.CheckConstraint(
            "unit_currency ~ '^[A-Z]{3}$'", name="ck_order_items_unit_currency_iso4217"
        ),
        sa.CheckConstraint("quantity = 1", name="ck_order_items_single_line"),
        sa.CheckConstraint(
            "unit_amount >= 0", name="ck_order_items_amount_not_negative"
        ),
        sa.ForeignKeyConstraint(
            ["order_id", "unit_currency"],
            ["orders.id", "orders.currency"],
            name="fk_order_items_order_currency",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "entitlements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "order_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("order_items.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column(
            "holder_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column("data_bytes_total", sa.BigInteger(), nullable=False),
        sa.Column("voice_seconds_total", sa.BigInteger(), nullable=False),
        _timestamp("granted_at"),
        _timestamp("expires_at", nullable=True),
        sa.CheckConstraint(
            "data_bytes_total >= 0", name="ck_entitlements_data_not_negative"
        ),
        sa.CheckConstraint(
            "voice_seconds_total >= 0", name="ck_entitlements_voice_not_negative"
        ),
    )

    op.create_table(
        "esim_installations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "entitlement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entitlements.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "esim_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("esim_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "installation_state",
            postgresql.ENUM(name="esim_installation_state", create_type=False),
            nullable=False,
            server_default="not_installed",
        ),
        _timestamp("installed_at", nullable=True),
    )

    op.create_table(
        "carrier_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "entitlement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entitlements.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("carrier", sa.String(32), nullable=False),
        sa.Column("carrier_line_reference", sa.String(128), nullable=False),
        sa.Column("iccid", sa.String(22), nullable=True),
        sa.Column(
            "activation_state",
            postgresql.ENUM(name="carrier_line_activation_state", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "network_state",
            postgresql.ENUM(name="carrier_line_network_state", create_type=False),
            nullable=False,
            server_default="unknown",
        ),
        _timestamp("network_state_observed_at", nullable=True),
        _timestamp("created_at"),
    )
    op.create_index(
        "ux_carrier_lines_carrier_reference",
        "carrier_lines",
        ["carrier", "carrier_line_reference"],
        unique=True,
    )

    op.create_table(
        "assigned_numbers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "carrier_line_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("carrier_lines.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("e164", sa.String(16), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        _timestamp("assigned_at"),
        _timestamp("released_at", nullable=True),
        sa.CheckConstraint(
            "e164 ~ '^\\+[1-9][0-9]{6,14}$'", name="ck_assigned_numbers_e164"
        ),
    )
    # Partial unique index: one *live* holder per number, while released
    # assignments stay in place so a historic call can still be attributed.
    op.create_index(
        "ux_assigned_numbers_live_e164",
        "assigned_numbers",
        ["e164"],
        unique=True,
        postgresql_where=sa.text("released_at IS NULL"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table in _NEW_TABLES:
        op.drop_table(table)
    for name, _ in _NEW_ENUMS:
        postgresql.ENUM(name=name, create_type=False).drop(bind, checkfirst=True)
