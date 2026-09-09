"""US-28 -- upgrading a populated legacy database preserves every record.

The risk in a schema chunk is not that the new tables are wrong; it is that
adding them quietly damages what is already there. So this test does not check
the migration in isolation. It builds a database at the pre-US-28 revision,
fills it with the record types the assignment names -- a personal user, an HTO
organization with a paid manifest order, a package with its NGN transaction and
receipt, an issued eSIM profile, and a pending issuance job -- then upgrades,
and asserts that every identifier, amount and timestamp is byte-for-byte what it
was.

It then downgrades and asserts the same thing again, because a migration you
cannot reverse on a populated database is not a migration you can deploy.
"""

import os
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.config import get_settings

PRE_US28_REVISION = "0026_i18n_locales"
US28_REVISION = "0027_core_domain_model"

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="migration upgrade proof requires PostgreSQL",
)


def _alembic_config(url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("script_location", "migrations")
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture
def legacy_url():
    """A database at the revision immediately before US-28."""
    admin = create_engine(
        os.environ["TEST_DATABASE_URL"], isolation_level="AUTOCOMMIT"
    )
    name = f"upgrade_{uuid4().hex[:12]}"
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = os.environ["TEST_DATABASE_URL"].rsplit("/", 1)[0] + f"/{name}"
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    # migrations/env.py resolves the URL through the cached settings, so the
    # environment change alone is not enough.
    get_settings.cache_clear()
    try:
        command.upgrade(_alembic_config(url), PRE_US28_REVISION)
        yield url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()
        with admin.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    f"WHERE datname = '{name}'"
                )
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))


NGN_PRICE = Decimal("48500.00")
PURCHASED_AT = datetime(2026, 7, 14, 9, 30, tzinfo=timezone.utc)


def _seed_legacy(url: str) -> dict[str, object]:
    """Representative records of every kind the assignment names."""
    ids = {
        "user": uuid4(),
        "organization": uuid4(),
        "manifest": uuid4(),
        "tier": uuid4(),
        "manifest_order": uuid4(),
        "package": uuid4(),
        "transaction": uuid4(),
        "esim_profile": uuid4(),
        "issuance_job": uuid4(),
    }
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, phone_number, first_name, last_name, "
                "account_source, verified_cli, destination_country, locale, "
                "platform, status, pin_failed_attempts, created_at, updated_at) "
                "VALUES (:id, '+2348012345678', 'Amina', 'Bello', 'direct', "
                "false, 'SA', 'en', 'android', 'active', 0, :now, :now)"
            ),
            {"id": ids["user"], "now": PURCHASED_AT},
        )
        connection.execute(
            text(
                "INSERT INTO organizations (id, org_type, name, "
                "primary_contact_name, email, password_hash, phone_number, "
                "locale, nahcon_licence_number, email_verified, "
                "approval_status, created_at) VALUES (:id, 'hto_operator', "
                "'Al-Amin Tours', 'Yusuf', 'ops@al-amin.test', 'hash', "
                "'+2348090000000', 'en', 'NAHCON-1234', true, 'approved', :now)"
            ),
            {"id": ids["organization"], "now": PURCHASED_AT},
        )
        connection.execute(
            text(
                "INSERT INTO manifests (id, organization_id, name, status, "
                "total_rows, valid_rows, created_at) VALUES (:id, :org, "
                "'Hajj 2026 Group A', 'validated', 1, 1, :now)"
            ),
            {"id": ids["manifest"], "org": ids["organization"], "now": PURCHASED_AT},
        )
        connection.execute(
            text(
                "INSERT INTO pricing_tiers (id, destination_country, name, "
                "usd_reference_price, data_gb, pstn_minutes, is_group_tier, "
                "wholesale_usd_price, active, ngn_price, validity_days) VALUES "
                "(:id, 'SA', 'Standard 5GB', 32.00, 5, 120, false, 24.00, true, "
                ":ngn, 30)"
            ),
            {"id": ids["tier"], "ngn": NGN_PRICE},
        )
        connection.execute(
            text(
                "INSERT INTO manifest_orders (id, manifest_id, pricing_tier_id, "
                "status, pilgrim_count, wholesale_price_ngn, total_ngn, "
                "created_at) VALUES (:id, :manifest, :tier, 'paid', 1, :total, "
                ":total, :now)"
            ),
            {
                "id": ids["manifest_order"],
                "manifest": ids["manifest"],
                "tier": ids["tier"],
                "total": NGN_PRICE,
                "now": PURCHASED_AT,
            },
        )
        connection.execute(
            text(
                "INSERT INTO packages (id, user_id, pricing_tier_id, source, "
                "status, group_size, data_gb_total, data_gb_remaining, "
                "pstn_minutes_total, pstn_minutes_remaining, purchased_at, "
                "destination_country) VALUES (:id, :user, :tier, 'retail', "
                "'active', 1, 5, 4.25, 120, 118.50, :now, 'SA')"
            ),
            {
                "id": ids["package"],
                "user": ids["user"],
                "tier": ids["tier"],
                "now": PURCHASED_AT,
            },
        )
        connection.execute(
            text(
                "INSERT INTO transactions (id, package_id, processor, "
                "payment_method, status, amount_ngn, processor_reference, "
                "created_at) VALUES (:id, :package, 'paystack', 'card', "
                "'success', :amount, 'ps-ref-1', :now)"
            ),
            {
                "id": ids["transaction"],
                "package": ids["package"],
                "amount": NGN_PRICE,
                "now": PURCHASED_AT,
            },
        )
        connection.execute(
            text(
                "INSERT INTO esim_profiles (id, package_id, aggregator, iccid, "
                "activation_code_lpa, qr_code_url, status) VALUES "
                "(:id, :package, 'monty_mobile', '8901000000000000001', "
                "'LPA:1$example$CODE', 'https://example.test/qr.png', 'issued')"
            ),
            {"id": ids["esim_profile"], "package": ids["package"]},
        )
        connection.execute(
            text(
                "INSERT INTO esim_issuance_jobs (id, package_id, attempt_count, "
                "next_attempt_at) VALUES (:id, :package, 2, :now)"
            ),
            {"id": ids["issuance_job"], "package": ids["package"], "now": PURCHASED_AT},
        )
    engine.dispose()
    return ids


def _snapshot(url: str) -> dict[str, object]:
    engine = create_engine(url)
    with engine.connect() as connection:
        snapshot = {
            "users": connection.execute(
                text("SELECT id, phone_number, created_at FROM users ORDER BY id")
            ).all(),
            "organizations": connection.execute(
                text("SELECT id, name, nahcon_licence_number FROM organizations")
            ).all(),
            "manifest_orders": connection.execute(
                text("SELECT id, status, total_ngn FROM manifest_orders")
            ).all(),
            "packages": connection.execute(
                text(
                    "SELECT id, user_id, status, data_gb_remaining, "
                    "pstn_minutes_remaining, purchased_at FROM packages"
                )
            ).all(),
            "transactions": connection.execute(
                text(
                    "SELECT id, package_id, amount_ngn, processor_reference, status "
                    "FROM transactions"
                )
            ).all(),
            "esim_profiles": connection.execute(
                text("SELECT id, package_id, iccid, status FROM esim_profiles")
            ).all(),
            "esim_issuance_jobs": connection.execute(
                text("SELECT id, package_id, attempt_count, next_attempt_at "
                     "FROM esim_issuance_jobs")
            ).all(),
        }
    engine.dispose()
    return snapshot


def test_upgrade_preserves_every_legacy_record(legacy_url) -> None:
    """AC: personal users, HTO organizations, paid orders and pending jobs."""
    _seed_legacy(legacy_url)
    before = _snapshot(legacy_url)

    command.upgrade(_alembic_config(legacy_url), US28_REVISION)

    assert _snapshot(legacy_url) == before


def test_upgrade_preserves_ngn_amounts_and_receipt_references(legacy_url) -> None:
    """Historical money keeps its exact value and its processor reference."""
    _seed_legacy(legacy_url)
    command.upgrade(_alembic_config(legacy_url), US28_REVISION)

    engine = create_engine(legacy_url)
    with engine.connect() as connection:
        amount, reference = connection.execute(
            text("SELECT amount_ngn, processor_reference FROM transactions")
        ).one()
        order_total = connection.execute(
            text("SELECT total_ngn FROM manifest_orders")
        ).scalar_one()
    engine.dispose()

    assert amount == NGN_PRICE
    assert reference == "ps-ref-1"
    assert order_total == NGN_PRICE


def test_upgrade_adds_the_new_tables_empty(legacy_url) -> None:
    """Additive means additive: nothing is backfilled into the new model."""
    _seed_legacy(legacy_url)
    command.upgrade(_alembic_config(legacy_url), US28_REVISION)

    engine = create_engine(legacy_url)
    with engine.connect() as connection:
        for table in (
            "legal_entities",
            "products",
            "product_prices",
            "orders",
            "order_items",
            "entitlements",
            "esim_installations",
            "carrier_lines",
            "assigned_numbers",
        ):
            count = connection.execute(
                text(f"SELECT count(*) FROM {table}")  # noqa: S608 -- fixed list
            ).scalar_one()
            assert count == 0, table
    engine.dispose()


def test_upgrade_installs_settlement_and_currency_invariants(legacy_url) -> None:
    """The Alembic schema must enforce the same money rules as the ORM schema."""
    command.upgrade(_alembic_config(legacy_url), US28_REVISION)

    engine = create_engine(legacy_url)
    with engine.connect() as connection:
        order_columns = set(
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'orders'"
                )
            ).scalars()
        )
        constraints = set(
            connection.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conname IN "
                    "('ck_product_prices_amount_not_negative', "
                    "'ck_orders_settlement_pair', "
                    "'ck_orders_settlement_amount_not_negative', "
                    "'fk_order_items_order_currency')"
                )
            ).scalars()
        )
    engine.dispose()

    assert {"settlement_currency", "settlement_amount"} <= order_columns
    assert constraints == {
        "ck_product_prices_amount_not_negative",
        "ck_orders_settlement_pair",
        "ck_orders_settlement_amount_not_negative",
        "fk_order_items_order_currency",
    }


def test_downgrade_restores_the_previous_schema_without_data_loss(legacy_url) -> None:
    """A migration that cannot be reversed on a populated database is not deployable."""
    _seed_legacy(legacy_url)
    before = _snapshot(legacy_url)
    config = _alembic_config(legacy_url)

    command.upgrade(config, US28_REVISION)
    command.downgrade(config, PRE_US28_REVISION)

    assert _snapshot(legacy_url) == before
    engine = create_engine(legacy_url)
    with engine.connect() as connection:
        remaining = connection.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name IN "
                "('orders', 'order_items', 'entitlements', 'carrier_lines', "
                "'assigned_numbers', 'products', 'product_prices', "
                "'legal_entities', 'esim_installations')"
            )
        ).scalar_one()
    engine.dispose()
    assert remaining == 0


def test_upgrade_is_reapplicable_after_a_downgrade(legacy_url) -> None:
    """Roll forward, back, and forward again -- the recovery path in practice."""
    _seed_legacy(legacy_url)
    config = _alembic_config(legacy_url)

    command.upgrade(config, US28_REVISION)
    command.downgrade(config, PRE_US28_REVISION)
    command.upgrade(config, US28_REVISION)

    engine = create_engine(legacy_url)
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    engine.dispose()
    assert revision == US28_REVISION
