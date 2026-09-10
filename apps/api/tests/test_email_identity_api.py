"""US-29 — email identity linking and recovery over HTTP.

Email is the launch account identity and primary recovery channel (founder
decision, 2026-09-09), and recovery must not require access to a SIM.

Two properties matter more than the happy path and are tested hardest:
the endpoints must not reveal whether an address is known, and the uniform
response must not become a way to post mail to a stranger repeatedly.
"""

import asyncio
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi.security import HTTPAuthorizationCredentials
from sqlmodel import select

from app.auth.dependencies import get_current_user
from app.auth.models import RefreshToken, User
from app.auth.pin import PINError
from app.auth.routes import request_otp, verify_otp
from app.auth.schemas import OTPRequest, OTPVerifyRequest
from app.identity.delivery import NullDeliveryTransport
from app.identity.models import AccountIdentifier, IdentifierKind
from app.main import create_app

VICTIM_EMAIL = "amina@example.test"
UNKNOWN_EMAIL = "nobody@example.test"


class ApiClient:
    """ASGI client that avoids the local Conda blocking-portal regression."""

    def __init__(self, api, headers: dict[str, str]) -> None:
        self.api = api
        self.headers = headers
        self.refresh_token: str | None = None

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        async def run() -> httpx.Response:
            headers = {**self.headers, **kwargs.pop("headers", {})}
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.api),
                base_url="http://testserver",
                headers=headers,
            ) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(run())

    def post(self, path: str, **kwargs) -> httpx.Response:
        return self.request("POST", path, **kwargs)


@pytest.fixture
def api(settings, redis_client, providers, scheduler, session_factory, clock):
    return create_app(
        settings=settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
    )


@pytest.fixture
def transport(api):
    return api.state.identity_transport


def _authenticated(api, phone: str = "08012345678") -> tuple[ApiClient, UUID]:
    request = SimpleNamespace(app=api)
    request_otp(OTPRequest(phone_number=phone), request)
    auth = verify_otp(
        OTPVerifyRequest(phone_number=phone, otp="123456", platform="android"), request
    )

    async def current_user_override():
        return auth.user

    api.dependency_overrides[get_current_user] = current_user_override
    client = ApiClient(
        api, headers={"Authorization": f"Bearer {auth.access_token}"}
    )
    client.refresh_token = auth.refresh_token
    return client, auth.user.id


def _anonymous(api) -> ApiClient:
    return ApiClient(api, headers={})


# --- linking ---------------------------------------------------------------


def test_linking_an_email_requires_authentication(api):
    response = _anonymous(api).post(
        "/v1/auth/email/verify/request", json={"email": VICTIM_EMAIL}
    )
    assert response.status_code in (401, 403)


def test_link_then_confirm_marks_the_identifier_verified(
    api, transport, session_factory
):
    client, user_id = _authenticated(api)

    started = client.post(
        "/v1/auth/email/verify/request", json={"email": VICTIM_EMAIL}
    )
    assert started.status_code == 200

    confirmed = _anonymous(api).post(
        "/v1/auth/email/verify/confirm", json={"token": transport.last_token()}
    )
    assert confirmed.status_code == 200

    with session_factory() as session:
        identifier = session.exec(
            select(AccountIdentifier).where(
                AccountIdentifier.value == VICTIM_EMAIL,
                AccountIdentifier.kind == IdentifierKind.EMAIL,
            )
        ).one()
        assert identifier.user_id == user_id
        assert identifier.verified_at is not None
        assert identifier.is_primary is True
        phone = session.exec(
            select(AccountIdentifier).where(
                AccountIdentifier.user_id == user_id,
                AccountIdentifier.kind == IdentifierKind.PHONE,
            )
        ).one()
        assert phone.is_primary is False
        account = session.get(User, user_id)
        assert account is not None and account.email == VICTIM_EMAIL


def test_a_confirmation_token_cannot_be_replayed(api, transport):
    client, _ = _authenticated(api)
    client.post("/v1/auth/email/verify/request", json={"email": VICTIM_EMAIL})
    token = transport.last_token()

    assert (
        _anonymous(api)
        .post("/v1/auth/email/verify/confirm", json={"token": token})
        .status_code
        == 200
    )
    replay = _anonymous(api).post(
        "/v1/auth/email/verify/confirm", json={"token": token}
    )
    assert replay.status_code == 400


def test_email_is_normalised_before_storage(api, transport, session_factory):
    client, _ = _authenticated(api)
    client.post(
        "/v1/auth/email/verify/request", json={"email": "  Amina@Example.TEST  "}
    )
    _anonymous(api).post(
        "/v1/auth/email/verify/confirm", json={"token": transport.last_token()}
    )
    with session_factory() as session:
        stored = session.exec(
            select(AccountIdentifier).where(
                AccountIdentifier.kind == IdentifierKind.EMAIL
            )
        ).one()
    assert stored.value == VICTIM_EMAIL


# --- recovery without a SIM ------------------------------------------------


def test_recovery_by_email_issues_a_session_without_any_otp(
    api, transport, session_factory
):
    """The founder decision: recovery must not require access to a SIM."""
    client, user_id = _authenticated(api)
    client.post("/v1/auth/email/verify/request", json={"email": VICTIM_EMAIL})
    _anonymous(api).post(
        "/v1/auth/email/verify/confirm", json={"token": transport.last_token()}
    )

    requested = _anonymous(api).post(
        "/v1/auth/email/recovery/request", json={"email": VICTIM_EMAIL}
    )
    assert requested.status_code == 200

    recovered = _anonymous(api).post(
        "/v1/auth/email/recovery/confirm", json={"token": transport.last_token()}
    )
    assert recovered.status_code == 200
    body = recovered.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user"]["id"] == str(user_id)


def test_recovery_revokes_sessions_held_by_anyone_else(
    api, transport, session_factory
):
    client, user_id = _authenticated(api)
    client.post("/v1/auth/email/verify/request", json={"email": VICTIM_EMAIL})
    _anonymous(api).post(
        "/v1/auth/email/verify/confirm", json={"token": transport.last_token()}
    )

    _anonymous(api).post(
        "/v1/auth/email/recovery/request", json={"email": VICTIM_EMAIL}
    )
    recovery_token = transport.last_token()

    with session_factory() as session:
        before = session.exec(
            select(RefreshToken).where(RefreshToken.user_id == user_id)
        ).all()
        assert before, "the signed-in session should exist before recovery"

    _anonymous(api).post(
        "/v1/auth/email/recovery/confirm", json={"token": recovery_token}
    )

    with session_factory() as session:
        stale = session.exec(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),  # type: ignore[union-attr]
            )
        ).all()
    # Only the freshly issued recovery session may remain live.
    assert len(stale) == 1


def test_email_is_a_first_class_signup_and_login_identity(
    api, transport, session_factory, clock
):
    anon = _anonymous(api)

    requested = anon.post(
        "/v1/auth/email/login/request",
        json={"email": VICTIM_EMAIL, "locale": "fr"},
    )
    assert requested.status_code == 200
    first = anon.post(
        "/v1/auth/email/login/confirm", json={"token": transport.last_token()}
    )

    assert first.status_code == 200
    assert first.json()["is_new_user"] is True
    assert first.json()["user"]["phone_number"] is None
    assert first.json()["user"]["platform"] is None
    assert first.json()["user"]["email"] == VICTIM_EMAIL
    with session_factory() as session:
        users = session.exec(select(User)).all()
        identifiers = session.exec(
            select(AccountIdentifier).where(
                AccountIdentifier.kind == IdentifierKind.EMAIL,
                AccountIdentifier.value == VICTIM_EMAIL,
            )
        ).all()
    assert len(users) == 1
    assert len(identifiers) == 1
    assert identifiers[0].verified_at is not None
    assert identifiers[0].is_primary is True

    clock.advance(seconds=61)
    anon.post(
        "/v1/auth/email/login/request",
        json={"email": VICTIM_EMAIL, "locale": "en"},
    )
    second = anon.post(
        "/v1/auth/email/login/confirm", json={"token": transport.last_token()}
    )
    assert second.status_code == 200
    assert second.json()["is_new_user"] is False
    assert second.json()["user"]["id"] == first.json()["user"]["id"]


def test_email_login_adopts_a_single_legacy_email_account(
    api, transport, session_factory
):
    """A pre-identity email must not produce a duplicate customer account."""
    with session_factory() as session:
        legacy = User(
            phone_number="+2348012345678",
            email=VICTIM_EMAIL,
            platform="android",
        )
        session.add(legacy)
        session.commit()
        legacy_id = legacy.id

    anon = _anonymous(api)
    assert (
        anon.post("/v1/auth/email/login/request", json={"email": VICTIM_EMAIL})
        .status_code
        == 200
    )
    confirmed = anon.post(
        "/v1/auth/email/login/confirm", json={"token": transport.last_token()}
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["is_new_user"] is False
    assert confirmed.json()["user"]["id"] == str(legacy_id)
    with session_factory() as session:
        assert len(session.exec(select(User)).all()) == 1
        identifier = session.exec(
            select(AccountIdentifier).where(
                AccountIdentifier.kind == IdentifierKind.EMAIL,
                AccountIdentifier.value == VICTIM_EMAIL,
            )
        ).one()
        assert identifier.user_id == legacy_id
        assert identifier.verified_at is not None
        assert identifier.is_primary is True


def test_email_login_request_is_uniform_and_delivers_for_signup_and_login(
    api, transport, clock
):
    anon = _anonymous(api)
    unknown = anon.post(
        "/v1/auth/email/login/request", json={"email": UNKNOWN_EMAIL}
    )
    unknown_token = transport.last_token()
    created = anon.post(
        "/v1/auth/email/login/confirm", json={"token": unknown_token}
    )
    assert created.status_code == 200

    clock.advance(seconds=61)
    known = anon.post(
        "/v1/auth/email/login/request", json={"email": UNKNOWN_EMAIL}
    )
    assert unknown.status_code == known.status_code == 200
    assert unknown.json() == known.json()
    assert len(transport.sent) == 2


def test_recovery_invalidates_already_issued_access_tokens(api, transport):
    client, _ = _authenticated(api)
    old_access = client.headers["Authorization"].removeprefix("Bearer ")
    client.post("/v1/auth/email/verify/request", json={"email": VICTIM_EMAIL})
    _anonymous(api).post(
        "/v1/auth/email/verify/confirm", json={"token": transport.last_token()}
    )
    _anonymous(api).post(
        "/v1/auth/email/recovery/request", json={"email": VICTIM_EMAIL}
    )
    recovered = _anonymous(api).post(
        "/v1/auth/email/recovery/confirm", json={"token": transport.last_token()}
    )
    assert recovered.status_code == 200

    assert client.refresh_token is not None
    stale_refresh = _anonymous(api).post(
        "/v1/auth/token/refresh",
        json={"refresh_token": client.refresh_token},
    )
    assert stale_refresh.status_code == 401

    request = SimpleNamespace(app=api)
    with pytest.raises(PINError, match="invalid_access_token"):
        get_current_user(
            request,
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=old_access),
        )
    current = get_current_user(
        request,
        HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=recovered.json()["access_token"]
        ),
    )
    assert str(current.id) == recovered.json()["user"]["id"]


def test_non_test_app_does_not_retain_raw_identity_tokens(
    settings, redis_client, providers, scheduler, session_factory, clock
):
    staging = create_app(
        settings=settings.model_copy(update={"app_env": "staging"}),
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
    )
    assert isinstance(staging.state.identity_transport, NullDeliveryTransport)


# --- enumeration resistance ------------------------------------------------


def test_recovery_request_is_identical_for_known_and_unknown_addresses(
    api, transport
):
    client, _ = _authenticated(api)
    client.post("/v1/auth/email/verify/request", json={"email": VICTIM_EMAIL})
    _anonymous(api).post(
        "/v1/auth/email/verify/confirm", json={"token": transport.last_token()}
    )
    transport.clear()

    known = _anonymous(api).post(
        "/v1/auth/email/recovery/request", json={"email": VICTIM_EMAIL}
    )
    sent_after_known = len(transport.sent)
    unknown = _anonymous(api).post(
        "/v1/auth/email/recovery/request", json={"email": UNKNOWN_EMAIL}
    )

    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    assert sent_after_known == 1
    assert len(transport.sent) == 1, "nothing may be sent for an unknown address"


def test_recovery_sends_nothing_for_an_unverified_address(api, transport):
    """An unverified claim must never be a route into an account."""
    client, _ = _authenticated(api)
    client.post("/v1/auth/email/verify/request", json={"email": VICTIM_EMAIL})
    transport.clear()

    response = _anonymous(api).post(
        "/v1/auth/email/recovery/request", json={"email": VICTIM_EMAIL}
    )

    assert response.status_code == 200
    assert transport.sent == []


# --- the uniform response must not become a mail cannon --------------------


def test_recovery_requests_are_throttled_per_address(api, transport, settings):
    client, _ = _authenticated(api)
    client.post("/v1/auth/email/verify/request", json={"email": VICTIM_EMAIL})
    _anonymous(api).post(
        "/v1/auth/email/verify/confirm", json={"token": transport.last_token()}
    )

    first = _anonymous(api).post(
        "/v1/auth/email/recovery/request", json={"email": VICTIM_EMAIL}
    )
    second = _anonymous(api).post(
        "/v1/auth/email/recovery/request", json={"email": VICTIM_EMAIL}
    )

    assert first.status_code == 200
    assert second.status_code == 429


def test_throttling_an_unknown_address_looks_the_same_as_a_known_one(api):
    """Otherwise the throttle itself becomes the oracle."""
    anon = _anonymous(api)
    first = anon.post(
        "/v1/auth/email/recovery/request", json={"email": UNKNOWN_EMAIL}
    )
    second = anon.post(
        "/v1/auth/email/recovery/request", json={"email": UNKNOWN_EMAIL}
    )
    assert first.status_code == 200
    assert second.status_code == 429


def test_throttling_is_scoped_per_address(api):
    anon = _anonymous(api)
    anon.post("/v1/auth/email/recovery/request", json={"email": UNKNOWN_EMAIL})
    other = anon.post(
        "/v1/auth/email/recovery/request", json={"email": "someone.else@example.test"}
    )
    assert other.status_code == 200
