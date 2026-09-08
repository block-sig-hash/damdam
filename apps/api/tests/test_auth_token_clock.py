"""US-42 / AC-42.1 — one controlled clock for token creation and validation.

`TokenService.issue` mints tokens against an injected `now`, and
`TokenService.decode_access` deliberately validates `exp` against that same
injected clock (`options={"verify_exp": False, "verify_iat": False}` plus a
manual comparison). The refresh-rotation path did not follow that rule: the
route passed `datetime.now(timezone.utc)` instead of the application clock, and
`TokenService.rotate` let PyJWT validate `exp` against real wall-clock time.

That is why `test_otp_request_and_verify_contract` began failing without any
code change. The test clock is pinned to 2026-07-13, so a refresh token carries
`exp` around 2026-08-12; once real time passed that date, PyJWT rejected a
token that was entirely self-consistent with the clock that minted it.

These tests pin the fixed behavior from both directions: rotation must succeed
at the injected clock, and it must still refuse an expired token when the
injected clock advances past `exp`. Production expiry is unchanged, because in
production the injected clock *is* wall-clock (`app.main.utc_now`).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from sqlmodel import select

from app.auth.models import User
from app.auth.routes import refresh_token, request_otp, verify_otp
from app.auth.schemas import OTPRequest, OTPVerifyRequest, RefreshRequest
from app.auth.tokens import InvalidRefreshTokenError, TokenService
from app.otp.service import OTPError

PHONE = "08012345678"


def _sign_in(api: FastAPI) -> str:
    """Complete an OTP sign-in and return the issued refresh token."""
    request = SimpleNamespace(app=api)
    request_otp(OTPRequest(phone_number=PHONE), request)
    verified = verify_otp(
        OTPVerifyRequest(phone_number=PHONE, otp="123456", platform="android"),
        request,
    )
    return verified.refresh_token


def test_rotation_uses_the_application_clock_not_wall_clock(
    api: FastAPI, clock
) -> None:
    """AC-42.1: a token minted at the injected clock rotates at that same clock.

    This is the regression test for the reported CI failure. Before the fix it
    failed with `OTPError: invalid_refresh_token`, raised from an
    `ExpiredSignatureError` produced by PyJWT's wall-clock `exp` check, even
    though the token was minted moments earlier at the very same injected
    clock.
    """
    refresh = _sign_in(api)
    request = SimpleNamespace(app=api)

    rotated = refresh_token(RefreshRequest(refresh_token=refresh), request)

    assert rotated.access_token
    assert rotated.refresh_token
    assert rotated.refresh_token != refresh
    # The clock never moved, so the failure mode cannot be "time passed".
    assert clock() == datetime(2026, 7, 13, tzinfo=timezone.utc)


def test_rotation_rejects_a_refresh_token_after_the_clock_passes_expiry(
    api: FastAPI, clock, settings
) -> None:
    """AC-42.1: expiry is still enforced — against the injected clock.

    Disabling PyJWT's own `exp` check must not disable expiry. Advancing the
    controlled clock one second past `exp` has to reject the token.
    """
    refresh = _sign_in(api)
    request = SimpleNamespace(app=api)

    clock.advance(days=settings.jwt_refresh_ttl_days, seconds=1)

    with pytest.raises(OTPError, match="invalid_refresh_token"):
        refresh_token(RefreshRequest(refresh_token=refresh), request)


def test_rotation_boundary_accepts_just_before_and_rejects_exactly_at_expiry(
    api: FastAPI, clock, settings
) -> None:
    """AC-42.1: the boundary is `expires_at <= now` -> rejected.

    One second before `exp` the token still works; exactly at `exp` it does
    not. Asserting both sides pins the comparison operator, so a later change
    from `<=` to `<` cannot pass silently.
    """
    ttl = timedelta(days=settings.jwt_refresh_ttl_days)

    refresh = _sign_in(api)
    request = SimpleNamespace(app=api)
    clock.advance(days=settings.jwt_refresh_ttl_days, seconds=-1)
    accepted = refresh_token(RefreshRequest(refresh_token=refresh), request)
    assert accepted.refresh_token != refresh

    # The rotated token was minted at the advanced clock, so its own expiry is
    # one full TTL further out. Land the clock exactly on that instant.
    clock.value = clock() + ttl
    with pytest.raises(OTPError, match="invalid_refresh_token"):
        refresh_token(
            RefreshRequest(refresh_token=accepted.refresh_token), request
        )


def test_rotation_still_revokes_the_previous_refresh_token(api: FastAPI) -> None:
    """AC-42.1: fixing the clock must not turn rotation into a replayable call."""
    refresh = _sign_in(api)
    request = SimpleNamespace(app=api)

    refresh_token(RefreshRequest(refresh_token=refresh), request)

    with pytest.raises(OTPError, match="invalid_refresh_token"):
        refresh_token(RefreshRequest(refresh_token=refresh), request)


def test_rotation_rejects_a_tampered_signature(api: FastAPI) -> None:
    """AC-42.1: relaxing PyJWT's `exp` check must not relax signature checking."""
    refresh = _sign_in(api)
    request = SimpleNamespace(app=api)
    head, payload, signature = refresh.split(".")
    forged = f"{head}.{payload}.{signature[:-1]}{'A' if signature[-1] != 'A' else 'B'}"

    with pytest.raises(OTPError, match="invalid_refresh_token"):
        refresh_token(RefreshRequest(refresh_token=forged), request)


def test_production_wall_clock_still_expires_tokens(
    api: FastAPI, settings, session_factory
) -> None:
    """AC-42.1: production expiry enforcement is unchanged.

    In production the injected clock *is* wall-clock, so this drives
    `TokenService` directly with `datetime.now(timezone.utc)` — exactly what
    `app.main.utc_now` supplies — and mints a token that was already expired
    when it was issued. It must be refused.
    """
    service = TokenService(settings)
    real_now = datetime.now(timezone.utc)
    _sign_in(api)

    with session_factory() as session:
        user = session.exec(
            select(User).where(User.phone_number == "+2348012345678")
        ).one()
        long_expired = real_now - timedelta(days=settings.jwt_refresh_ttl_days + 1)
        pair = service.issue(session, user, long_expired)
        session.commit()

        with pytest.raises(InvalidRefreshTokenError):
            service.rotate(session, pair.refresh_token, real_now)


def test_access_token_validation_already_uses_the_injected_clock(
    api: FastAPI, settings, session_factory
) -> None:
    """AC-42.1: characterization of the pattern `rotate` is being aligned to.

    `decode_access` already validates against the injected clock. This asserts
    that both directions hold, so the two paths cannot drift apart again
    without a test failing.
    """
    service = TokenService(settings)
    minted_at = datetime(2026, 7, 13, tzinfo=timezone.utc)

    with session_factory() as session:
        _sign_in(api)
        user = session.exec(
            select(User).where(User.phone_number == "+2348012345678")
        ).one()
        pair = service.issue(session, user, minted_at)
        session.commit()

        assert service.decode_access(pair.access_token, minted_at) == user.id

        expired_at = minted_at + timedelta(
            minutes=settings.jwt_access_ttl_minutes, seconds=1
        )
        with pytest.raises(InvalidRefreshTokenError):
            service.decode_access(pair.access_token, expired_at)
