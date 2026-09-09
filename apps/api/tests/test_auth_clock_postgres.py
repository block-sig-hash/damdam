"""US-42: token clocks, expiry and rotation checked on actual PostgreSQL."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, Lock
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import jwt
import pytest
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.dependencies import get_current_organization
from app.auth.hto import HTOAuthError
from app.auth.models import (
    HTOApprovalStatus,
    Organization,
    OrganizationType,
    Platform,
    RefreshToken,
    User,
)
from app.auth.tokens import InvalidRefreshTokenError, TokenService

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="requires the PostgreSQL service configured in CI",
)


@pytest.fixture
def session_factory():
    url = os.environ["TEST_DATABASE_URL"]
    schema = f"clock_review_{uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        SQLModel.metadata.create_all(engine)
        yield lambda: Session(engine)
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def seed_user(session_factory, settings, now):
    service = TokenService(settings)
    with session_factory() as session:
        user = User(
            phone_number="+2348012345678",
            first_name="",
            last_name="",
            platform=Platform.ANDROID,
        )
        session.add(user)
        session.flush()
        pair = service.issue(session, user, now)
        session.commit()
        return service, pair, user.id


@pytest.mark.parametrize("year", [2000, 2100])
def test_consumer_clock_both_directions(session_factory, settings, year):
    now = datetime(year, 1, 1, tzinfo=timezone.utc)
    service, pair, user_id = seed_user(session_factory, settings, now)
    assert service.decode_access(pair.access_token, now) == user_id
    with session_factory() as session:
        rotated = service.rotate(session, pair.refresh_token, now)
        assert service.decode_access(rotated.access_token, now) == user_id


@pytest.mark.parametrize("token_type", ["access", "refresh"])
def test_future_issued_tokens_rejected_against_injected_clock(
    session_factory, settings, token_type
):
    now = datetime(2100, 1, 1, tzinfo=timezone.utc)
    service, pair, _ = seed_user(session_factory, settings, now + timedelta(days=1))
    with session_factory() as session, pytest.raises(InvalidRefreshTokenError):
        if token_type == "access":
            service.decode_access(pair.access_token, now)
        else:
            service.rotate(session, pair.refresh_token, now)


@pytest.mark.parametrize("claim", ["exp", "iat", "nbf"])
@pytest.mark.parametrize("value", [float("inf"), float("nan"), "bad-date"])
def test_invalid_numeric_dates_are_auth_errors(settings, claim, value):
    now = datetime(2100, 1, 1, tzinfo=timezone.utc)
    claims = {
        "aud": "pilgrim",
        "sub": str(uuid4()),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        claim: value,
    }
    token = jwt.encode(claims, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(InvalidRefreshTokenError):
        TokenService(settings).decode_access(token, now)


def test_stored_refresh_expiry_remains_authoritative(session_factory, settings):
    now = datetime(2100, 1, 1, tzinfo=timezone.utc)
    service, pair, _ = seed_user(session_factory, settings, now)
    with session_factory() as session:
        stored = session.exec(select(RefreshToken)).one()
        stored.expires_at = now
        session.add(stored)
        session.commit()
        with pytest.raises(InvalidRefreshTokenError):
            service.rotate(session, pair.refresh_token, now)


def test_concurrent_refresh_only_rotates_once(session_factory, settings, monkeypatch):
    now = datetime.now(timezone.utc)
    service, pair, _ = seed_user(session_factory, settings, now)
    start = Barrier(2)
    second_issue = Event()
    issue_lock = Lock()
    issue_count = 0
    original_issue = service.issue

    def delayed_issue(session, user, instant):
        nonlocal issue_count
        with issue_lock:
            issue_count += 1
            if issue_count == 2:
                second_issue.set()
        # Widen the read-before-revoke race without replacing PostgreSQL locking.
        # With FOR UPDATE, the second request cannot reach issue until commit;
        # without it, both requests reach issue and unblock this wait.
        second_issue.wait(timeout=1)
        return original_issue(session, user, instant)

    monkeypatch.setattr(service, "issue", delayed_issue)

    def rotate_once():
        with session_factory() as session:
            start.wait(timeout=10)
            try:
                service.rotate(session, pair.refresh_token, now)
                return "accepted"
            except InvalidRefreshTokenError:
                return "rejected"

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: rotate_once(), range(2)))
    assert sorted(results) == ["accepted", "rejected"]
    with session_factory() as session:
        rows = session.exec(select(RefreshToken)).all()
        assert len(rows) == 2
        assert sum(row.revoked_at is None for row in rows) == 1


def test_organization_access_and_verification_use_forward_clock(
    api, clock, session_factory
):
    clock.value = datetime(2100, 1, 1, tzinfo=timezone.utc)
    service = api.state.hto_service
    with session_factory() as session:
        org = Organization(
            org_type=OrganizationType.HTO_OPERATOR,
            name="Test organization",
            primary_contact_name="Test",
            email="clock@example.test",
            password_hash="synthetic",
            phone_number="+2348012345678",
            nahcon_licence_number="TEST",
            email_verified=True,
            approval_status=HTOApprovalStatus.APPROVED,
        )
        session.add(org)
        session.flush()
        pair = service._issue_tokens(session, org)
        org_id = org.id
        verification = parse_qs(urlparse(service._verification_url(org)).query)[
            "token"
        ][0]
        session.commit()
        assert service.verify_email(session, verification).id == org_id

    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=pair.access_token
    )
    request = SimpleNamespace(app=api)
    assert get_current_organization(request, credentials).id == org_id
    clock.advance(minutes=api.state.settings.jwt_access_ttl_minutes)
    with pytest.raises(HTOAuthError, match="invalid_operator_token"):
        get_current_organization(request, credentials)
