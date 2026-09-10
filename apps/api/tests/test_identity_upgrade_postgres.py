"""US-29 migration proof against a populated revision-0027 database."""

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.config import get_settings

PRE_IDENTITY_REVISION = "0027_core_domain_model"
IDENTITY_REVISION = "0028_account_identity"
API_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="migration upgrade proof requires PostgreSQL",
)


def _config(url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


@pytest.fixture
def legacy_url():
    base_url = os.environ["TEST_DATABASE_URL"]
    admin = create_engine(base_url)
    schema = f"identity_upgrade_{uuid4().hex[:12]}"
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    separator = "&" if "?" in base_url else "?"
    url = f"{base_url}{separator}options=-csearch_path={schema}"
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        command.upgrade(_config(url), PRE_IDENTITY_REVISION)
        yield url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _seed_phone_user(url: str) -> tuple[object, datetime]:
    user_id = uuid4()
    created_at = datetime(2026, 9, 1, 10, 30, tzinfo=timezone.utc)
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
            {"id": user_id, "now": created_at},
        )
    engine.dispose()
    return user_id, created_at


def test_upgrade_backfills_phone_and_allows_email_only_accounts(legacy_url):
    user_id, created_at = _seed_phone_user(legacy_url)
    command.upgrade(_config(legacy_url), IDENTITY_REVISION)

    engine = create_engine(legacy_url)
    with engine.begin() as connection:
        user = connection.execute(
            text(
                "SELECT phone_number, platform, auth_version, created_at "
                "FROM users WHERE id = :id"
            ),
            {"id": user_id},
        ).one()
        identifier = connection.execute(
            text(
                "SELECT kind, value, verified_at, is_primary "
                "FROM account_identifiers WHERE user_id = :id"
            ),
            {"id": user_id},
        ).one()
        nullable = dict(
            connection.execute(
                text(
                    "SELECT column_name, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'users' "
                    "AND column_name IN ('phone_number', 'platform')"
                )
            ).all()
        )
        token_purposes = set(
            connection.execute(
                text(
                    "SELECT enumlabel FROM pg_enum JOIN pg_type "
                    "ON pg_enum.enumtypid = pg_type.oid "
                    "WHERE typname = 'identity_token_purpose'"
                )
            ).scalars()
        )
        connection.execute(
            text(
                "INSERT INTO users (id, first_name, last_name, email, "
                "account_source, verified_cli, destination_country, locale, "
                "status, pin_failed_attempts, auth_version, created_at, updated_at) "
                "VALUES (:id, '', '', 'new@example.test', 'direct', false, "
                "'SA', 'en', 'active', 0, 0, :now, :now)"
            ),
            {"id": uuid4(), "now": created_at},
        )
    engine.dispose()

    assert user == ("+2348012345678", "android", 0, created_at)
    assert identifier[0:2] == ("phone", "+2348012345678")
    assert identifier.verified_at == created_at
    assert identifier.is_primary is True
    assert nullable == {"phone_number": "YES", "platform": "YES"}
    assert token_purposes == {
        "verify_identifier",
        "recover_account",
        "authenticate",
    }


def test_legacy_only_database_can_downgrade_without_data_loss(legacy_url):
    user_id, created_at = _seed_phone_user(legacy_url)
    config = _config(legacy_url)
    command.upgrade(config, IDENTITY_REVISION)
    command.downgrade(config, PRE_IDENTITY_REVISION)

    engine = create_engine(legacy_url)
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT phone_number, platform, created_at FROM users WHERE id = :id"
            ),
            {"id": user_id},
        ).one()
    engine.dispose()
    assert row == ("+2348012345678", "android", created_at)


def test_downgrade_refuses_to_corrupt_email_only_accounts(legacy_url):
    command.upgrade(_config(legacy_url), IDENTITY_REVISION)
    engine = create_engine(legacy_url)
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, first_name, last_name, email, "
                "account_source, verified_cli, destination_country, locale, "
                "status, pin_failed_attempts, auth_version, created_at, updated_at) "
                "VALUES (:id, '', '', 'only@example.test', 'direct', false, "
                "'SA', 'en', 'active', 0, 0, :now, :now)"
            ),
            {"id": uuid4(), "now": now},
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match="email-only accounts exist"):
        command.downgrade(_config(legacy_url), PRE_IDENTITY_REVISION)

    engine = create_engine(legacy_url)
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        count = connection.execute(text("SELECT count(*) FROM users")).scalar_one()
    engine.dispose()
    assert revision == IDENTITY_REVISION
    assert count == 1
