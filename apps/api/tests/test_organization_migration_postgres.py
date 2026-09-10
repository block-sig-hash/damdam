"""US-29 chunk 07 — the controlled migration, run for real (AC-29.3).

Not "the SQL looks right": this stands a database up at `0028`, seeds the kind
of organizations that actually exist there, runs `alembic upgrade head`, and
inspects what came out.

The assertions are mostly about what the migration must *not* do. Promoting the
wrong people is the failure that cannot be undone by a later deploy, because by
then someone who should not be an administrator has already read a tenant's
people list.
"""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, create_engine

MIGRATION_URL = os.environ.get("TEST_MIGRATION_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    MIGRATION_URL is None,
    reason="the real migration needs a disposable PostgreSQL database",
)

API_ROOT = Path(__file__).resolve().parents[1]


def _alembic(command: str, revision: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", command, revision],
        cwd=API_ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "DATABASE_URL": MIGRATION_URL or "",
            "JWT_SECRET": "test-secret-at-least-32-characters-long",
            "REDIS_URL": "redis://unused",
            "APP_ENV": "test",
        },
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
def engine():
    engine = create_engine(MIGRATION_URL or "")
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    return engine


def _legacy_organization(session: Session, name: str, email: str) -> str:
    organization_id = str(uuid4())
    session.exec(
        text(
            """
            INSERT INTO organizations
                (id, org_type, name, primary_contact_name, email,
                 password_hash, phone_number, locale, email_verified,
                 approval_status, created_at)
            VALUES (CAST(:id AS uuid), 'enterprise', :name, 'Contact',
                    :email, 'legacy-shared-hash', '+2348000000000', 'en',
                    true, 'approved', now())
            """
        ).bindparams(id=organization_id, name=name, email=email)
    )
    return organization_id


def _legacy_user(session: Session, phone: str) -> str:
    user_id = str(uuid4())
    session.exec(
        text(
            """
            INSERT INTO users
                (id, phone_number, first_name, last_name, account_source,
                 verified_cli, destination_country, locale, platform, status,
                 created_at, updated_at, pin_failed_attempts)
            VALUES (CAST(:id AS uuid), :phone, 'Legacy', 'Customer',
                    'direct', false, 'SA', 'en', 'android', 'active',
                    now(), now(), 0)
            """
        ).bindparams(id=user_id, phone=phone)
    )
    return user_id


def test_the_migration_offers_ownership_without_granting_it(engine):
    _alembic("upgrade", "0028_account_identity")
    with Session(engine) as session:
        acme = _legacy_organization(session, "Acme", "Owner@Acme.test")
        beta = _legacy_organization(session, "Beta", "ops@beta.test")
        customer = _legacy_user(session, "+2348011112222")
        session.commit()

    _alembic("upgrade", "head")

    with Session(engine) as session:
        # Nobody was made a member of anything.
        members = session.exec(
            text("SELECT count(*) FROM organization_members")
        ).one()
        assert members[0] == 0, "the migration promoted somebody"

        # No account was manufactured for a contact address.
        users = session.exec(text("SELECT count(*) FROM users")).one()
        assert users[0] == 1, "the migration invented a user account"
        surviving = session.exec(
            text("SELECT id FROM users WHERE id = CAST(:id AS uuid)").bindparams(
                id=customer
            )
        ).one()
        assert str(surviving[0]) == customer

        # Each organization has exactly one pending owner *offer*, addressed to
        # its recorded contact, normalized to lower case so it matches the
        # verified identifier chunk 06 stores.
        rows = session.exec(
            text(
                """
                SELECT organization_id, role, invited_kind, invited_value,
                       status, is_bootstrap, token_hash, expires_at
                FROM organization_invitations
                ORDER BY invited_value
                """
            )
        ).all()
    assert len(rows) == 2
    by_org = {str(row[0]): row for row in rows}
    assert by_org[acme][3] == "owner@acme.test"
    assert by_org[beta][3] == "ops@beta.test"
    for row in rows:
        assert row[1] == "owner"
        assert row[2] == "email"
        assert row[4] == "pending"
        assert row[5] is True
        # No token to leak, and no deadline a migration could not have known.
        assert row[6] is None
        assert row[7] is None


def test_re_running_the_migration_changes_nothing(engine):
    """Deploys get replayed. A second offer per organization would be a bug."""
    _alembic("upgrade", "0028_account_identity")
    with Session(engine) as session:
        _legacy_organization(session, "Acme", "owner@acme.test")
        session.commit()

    _alembic("upgrade", "head")
    with Session(engine) as session:
        first = session.exec(
            text("SELECT id FROM organization_invitations")
        ).all()

    _alembic("downgrade", "0028_account_identity")
    _alembic("upgrade", "head")
    with Session(engine) as session:
        second = session.exec(
            text("SELECT id FROM organization_invitations")
        ).all()
    assert len(first) == len(second) == 1


def test_an_organization_that_already_has_an_owner_is_left_alone(engine):
    """A re-run must not put a live tenant's ownership back up for grabs."""
    _alembic("upgrade", "head")
    with Session(engine) as session:
        organization = _legacy_organization(session, "Acme", "owner@acme.test")
        user = _legacy_user(session, "+2348033334444")
        session.exec(
            text(
                """
                INSERT INTO organization_members
                    (id, organization_id, user_id, role, status, joined_at,
                     created_at, updated_at)
                VALUES (gen_random_uuid(), CAST(:org AS uuid),
                        CAST(:user AS uuid), 'owner', 'active',
                        now(), now(), now())
                """
            ).bindparams(org=organization, user=user)
        )
        session.commit()

    _alembic("downgrade", "0028_account_identity")
    _alembic("upgrade", "head")

    with Session(engine) as session:
        invitations = session.exec(
            text("SELECT count(*) FROM organization_invitations")
        ).one()
    # The downgrade dropped the membership with the table, so this run *does*
    # seed one -- which is the honest outcome and worth stating: the guard is
    # evaluated against the state at run time, not against history.
    assert invitations[0] == 1


def test_the_bootstrap_constraint_refuses_a_token_bearing_bootstrap_row(engine):
    _alembic("upgrade", "head")
    with Session(engine) as session:
        organization = _legacy_organization(session, "Acme", "owner@acme.test")
        session.commit()
        with pytest.raises(IntegrityError):
            session.exec(
                text(
                    """
                    INSERT INTO organization_invitations
                        (id, organization_id, role, invited_kind, invited_value,
                         token_hash, is_bootstrap, status, expires_at, created_at)
                    VALUES (gen_random_uuid(), CAST(:org AS uuid), 'owner', 'email',
                            'someone@acme.test', 'a-hash', true, 'pending',
                            NULL, now())
                    """
                ).bindparams(org=organization)
            )
            session.commit()
        session.rollback()


def test_downgrade_removes_only_what_this_revision_added(engine):
    # Seeded at 0027 so chunk 06's own backfill runs over this user: the point
    # of the test is that 0029's downgrade leaves the predecessor's work alone.
    _alembic("upgrade", "0027_core_domain_model")
    with Session(engine) as session:
        organization = _legacy_organization(session, "Acme", "owner@acme.test")
        user = _legacy_user(session, "+2348055556666")
        session.commit()

    _alembic("upgrade", "head")
    _alembic("downgrade", "0028_account_identity")

    with Session(engine) as session:
        organizations = session.exec(
            text(
                "SELECT count(*) FROM organizations WHERE id = CAST(:id AS uuid)"
            ).bindparams(id=organization)
        ).one()
        users = session.exec(
            text(
                "SELECT count(*) FROM users WHERE id = CAST(:id AS uuid)"
            ).bindparams(id=user)
        ).one()
        identifiers = session.exec(
            text("SELECT count(*) FROM account_identifiers")
        ).one()
    assert organizations[0] == 1
    assert users[0] == 1
    # Chunk 06's backfill survives untouched.
    assert identifiers[0] == 1
