"""US-29 — identity linking, purpose-bound tokens and recovery, on real PostgreSQL.

Written before the implementation, per the repository's strict-TDD policy for
auth. Every test here describes an attack or a race, because that is what this
chunk exists to withstand: a recovery link that can be replayed, a verification
token that doubles as a recovery token, or an unverified email that lets a
stranger claim someone else's account are all account takeover.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, col, create_engine, select

from app.auth.models import RefreshToken, User
from app.identity.delivery import RecordingDeliveryTransport
from app.identity.models import (
    AccountIdentifier,
    IdentifierKind,
    IdentityToken,
    IdentityTokenPurpose,
)
from app.identity.service import IdentityError, IdentityService

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="identity races and constraints require PostgreSQL",
)

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def engine():
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    """A clean slate per test.

    These tests commit, so without truncation a second run would collide with
    the first run's rows and the suite would only pass once.
    """
    with Session(engine) as session:
        session.exec(
            text(
                "TRUNCATE identity_tokens, account_identifiers, refresh_tokens, "
                "users RESTART IDENTITY CASCADE"
            )
        )
        session.commit()
        yield session
        session.rollback()


@pytest.fixture
def transport():
    return RecordingDeliveryTransport()


@pytest.fixture
def service(transport):
    return IdentityService(
        transport=transport,
        clock=lambda: NOW,
        token_ttl=timedelta(hours=1),
    )


def _user(session: Session, phone: str | None = None) -> User:
    user = User(phone_number=phone or f"+234801{uuid4().hex[:7]}", platform="android")
    session.add(user)
    session.flush()
    return user


# --- single-use, expiring, purpose-bound ----------------------------------


def test_a_verification_token_cannot_be_used_twice(session, service, transport):
    user = _user(session)
    service.start_identifier_verification(
        session, user, IdentifierKind.EMAIL, "amina@example.test"
    )
    session.commit()
    raw = transport.last_token()

    service.confirm_identifier(session, raw)
    session.commit()

    with pytest.raises(IdentityError) as exc:
        service.confirm_identifier(session, raw)
    assert exc.value.code == "identity_token_invalid"


def test_expiry_is_exclusive_at_the_exact_boundary(session, service, transport):
    """One second before expiry works; exactly at expiry does not."""

    def newest_token_for(user_id):
        return session.exec(
            select(IdentityToken)
            .where(
                IdentityToken.user_id == user_id,
                col(IdentityToken.consumed_at).is_(None),
            )
            .order_by(col(IdentityToken.created_at).desc())
        ).first()

    user = _user(session)
    service.start_identifier_verification(
        session, user, IdentifierKind.EMAIL, f"b{uuid4().hex[:6]}@example.test"
    )
    session.commit()
    raw = transport.last_token()
    token = newest_token_for(user.id)
    assert token is not None

    service.confirm_identifier(
        session, raw, now=token.expires_at - timedelta(seconds=1)
    )
    session.commit()

    service.start_identifier_verification(
        session, user, IdentifierKind.EMAIL, f"b{uuid4().hex[:6]}@example.test"
    )
    session.commit()
    raw2 = transport.last_token()
    token2 = newest_token_for(user.id)
    assert token2 is not None

    with pytest.raises(IdentityError) as exc:
        service.confirm_identifier(session, raw2, now=token2.expires_at)
    assert exc.value.code == "identity_token_expired"


def test_a_verification_token_cannot_complete_a_recovery(session, service, transport):
    """Purpose-bound: the two flows must not share credentials."""
    user = _user(session)
    service.start_identifier_verification(
        session, user, IdentifierKind.EMAIL, "purpose@example.test"
    )
    session.commit()
    raw = transport.last_token()

    with pytest.raises(IdentityError) as exc:
        service.complete_recovery(session, raw)
    assert exc.value.code == "identity_token_invalid"


def test_a_recovery_token_cannot_verify_an_identifier(session, service, transport):
    user = _user(session)
    identifier = service.start_identifier_verification(
        session, user, IdentifierKind.EMAIL, "rec@example.test"
    )
    session.commit()
    service.confirm_identifier(session, transport.last_token())
    session.commit()

    service.request_recovery(session, IdentifierKind.EMAIL, "rec@example.test")
    session.commit()
    recovery_raw = transport.last_token()

    with pytest.raises(IdentityError) as exc:
        service.confirm_identifier(session, recovery_raw)
    assert exc.value.code == "identity_token_invalid"
    assert identifier is not None


# --- races ----------------------------------------------------------------


def test_concurrent_use_of_one_token_consumes_it_once(engine, service, transport):
    """Two simultaneous clicks on the same link must not both succeed."""
    with Session(engine) as setup:
        user = _user(setup)
        service.start_identifier_verification(
            setup, user, IdentifierKind.EMAIL, f"race{uuid4().hex[:6]}@example.test"
        )
        setup.commit()
    raw = transport.last_token()

    barrier = Barrier(2)
    outcomes = []

    def attempt():
        with Session(engine) as s:
            barrier.wait(timeout=10)
            try:
                service.confirm_identifier(s, raw)
                s.commit()
                outcomes.append("ok")
            except IdentityError as exc:
                s.rollback()
                outcomes.append(exc.code)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: attempt(), range(2)))

    assert outcomes.count("ok") == 1, outcomes
    assert "identity_token_invalid" in outcomes


# --- takeover resistance ---------------------------------------------------


def test_an_unverified_claim_cannot_take_over_a_verified_identifier(
    session, service, transport
):
    """The attack this table exists to stop.

    An attacker adds the victim's email to their own account. Until they prove
    ownership it grants nothing, and once the victim has verified it the
    attacker can never confirm it.
    """
    victim = _user(session)
    attacker = _user(session)
    shared = "victim@example.test"

    service.start_identifier_verification(session, victim, IdentifierKind.EMAIL, shared)
    session.commit()
    victim_token = transport.last_token()
    service.confirm_identifier(session, victim_token)
    session.commit()

    service.start_identifier_verification(
        session, attacker, IdentifierKind.EMAIL, shared
    )
    session.commit()
    attacker_token = transport.last_token()

    with pytest.raises(IdentityError) as exc:
        service.confirm_identifier(session, attacker_token)
    assert exc.value.code == "identifier_already_verified"

    owner = session.exec(
        select(AccountIdentifier).where(
            AccountIdentifier.value == shared,
            AccountIdentifier.verified_at.is_not(None),  # type: ignore[union-attr]
        )
    ).one()
    assert owner.user_id == victim.id


def test_an_unverified_duplicate_does_not_block_the_real_owner(
    session, service, transport
):
    """Squatting must not become denial of service."""
    attacker = _user(session)
    victim = _user(session)
    shared = "contested@example.test"

    service.start_identifier_verification(
        session, attacker, IdentifierKind.EMAIL, shared
    )
    session.commit()

    service.start_identifier_verification(session, victim, IdentifierKind.EMAIL, shared)
    session.commit()
    service.confirm_identifier(session, transport.last_token())
    session.commit()

    verified = session.exec(
        select(AccountIdentifier).where(
            AccountIdentifier.value == shared,
            AccountIdentifier.verified_at.is_not(None),  # type: ignore[union-attr]
        )
    ).one()
    assert verified.user_id == victim.id


def test_the_database_refuses_two_verified_rows_for_one_identifier(session):
    """Enforced by a partial unique index, not only by service code."""
    from sqlalchemy.exc import IntegrityError

    a, b = _user(session), _user(session)
    value = f"dup{uuid4().hex[:6]}@example.test"
    session.add(
        AccountIdentifier(
            user_id=a.id, kind=IdentifierKind.EMAIL, value=value, verified_at=NOW
        )
    )
    session.commit()
    session.add(
        AccountIdentifier(
            user_id=b.id, kind=IdentifierKind.EMAIL, value=value, verified_at=NOW
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


# --- recovery --------------------------------------------------------------


def test_recovery_revokes_every_existing_session(session, service, transport, engine):
    """Recovering an account must log out whoever else was holding it."""
    user = _user(session)
    service.start_identifier_verification(
        session, user, IdentifierKind.EMAIL, "revoke@example.test"
    )
    session.commit()
    service.confirm_identifier(session, transport.last_token())
    session.commit()

    for _ in range(3):
        session.add(
            RefreshToken(
                user_id=user.id,
                token_hash=uuid4().hex,
                expires_at=NOW + timedelta(days=30),
            )
        )
    session.commit()

    service.request_recovery(session, IdentifierKind.EMAIL, "revoke@example.test")
    session.commit()
    recovered = service.complete_recovery(session, transport.last_token())
    session.commit()

    assert recovered.id == user.id
    live = session.exec(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),  # type: ignore[union-attr]
        )
    ).all()
    assert live == []


def test_recovery_for_an_unknown_identifier_is_indistinguishable(
    session, service, transport
):
    """Enumeration resistance: same outcome, and nothing is sent."""
    user = _user(session)
    service.start_identifier_verification(
        session, user, IdentifierKind.EMAIL, "known@example.test"
    )
    session.commit()
    service.confirm_identifier(session, transport.last_token())
    session.commit()
    transport.clear()

    known = service.request_recovery(
        session, IdentifierKind.EMAIL, "known@example.test"
    )
    sent_for_known = len(transport.sent)
    unknown = service.request_recovery(
        session, IdentifierKind.EMAIL, "nobody@example.test"
    )
    session.commit()

    assert known == unknown          # identical return value
    assert sent_for_known == 1
    assert len(transport.sent) == 1  # nothing sent for the unknown address


def test_recovery_is_refused_for_an_unverified_identifier(session, service, transport):
    """An unverified address must not be a route into the account."""
    user = _user(session)
    service.start_identifier_verification(
        session, user, IdentifierKind.EMAIL, "unverified@example.test"
    )
    session.commit()
    transport.clear()

    service.request_recovery(session, IdentifierKind.EMAIL, "unverified@example.test")
    session.commit()

    assert transport.sent == []


# --- legacy accounts -------------------------------------------------------


def test_an_existing_phone_user_keeps_access_and_gains_an_identifier(session, service):
    """Migration must not strand anyone who signed up before this chunk."""
    legacy = _user(session, phone="+2348012345678")
    session.commit()

    identifier = service.adopt_legacy_phone(session, legacy)
    session.commit()

    assert identifier.kind is IdentifierKind.PHONE
    assert identifier.value == "+2348012345678"
    assert identifier.verified_at is not None
    assert identifier.is_primary is True
    assert session.get(User, legacy.id) is not None


def test_adopting_a_legacy_phone_twice_is_idempotent(session, service):
    legacy = _user(session, phone="+2348099999999")
    session.commit()
    first = service.adopt_legacy_phone(session, legacy)
    session.commit()
    second = service.adopt_legacy_phone(session, legacy)
    session.commit()
    assert first.id == second.id
    rows = session.exec(
        select(AccountIdentifier).where(AccountIdentifier.user_id == legacy.id)
    ).all()
    assert len(rows) == 1


# --- token storage ---------------------------------------------------------


def test_the_raw_token_is_never_stored(session, service, transport):
    """Only a hash is persisted, so a database leak is not a set of live links."""
    user = _user(session)
    service.start_identifier_verification(
        session, user, IdentifierKind.EMAIL, "hash@example.test"
    )
    session.commit()
    raw = transport.last_token()

    stored = session.exec(select(IdentityToken)).all()[-1]
    assert stored.token_hash != raw
    assert raw not in stored.token_hash
    assert stored.purpose is IdentityTokenPurpose.VERIFY_IDENTIFIER
