"""US-29 — a caller must not learn whether an account exists.

Founder decision, 2026-09-09.

The pre-verification signal is removed from `/auth/otp/request`: it answers
identically whether or not the number is registered. The "direct to login"
behaviour AC-01.7 asks for survives, but moves *after* OTP verification, where
the caller has already proved control of the number.

The second half of these tests is the part that is easy to get wrong. A uniform
"we sent it" response, on its own, turns the endpoint into a way to flood a
victim's phone or mailbox. Per-identifier throttling has to survive the change.
"""

import pytest
from sqlmodel import Session

from app.auth.models import User
from app.identity.models import IdentifierKind
from app.otp.service import OTPError, OTPService

KNOWN = "08012345678"
UNKNOWN = "08099998888"


def _register(session_factory: type[Session], phone_e164: str) -> None:
    with session_factory() as session:
        session.add(
            User(
                phone_number=phone_e164,
                first_name="",
                last_name="",
                platform="android",
                account_source="direct",
            )
        )
        session.commit()


def test_otp_request_answers_identically_for_known_and_unknown_numbers(
    otp_service: OTPService, session_factory: type[Session]
) -> None:
    """The oracle is gone: no exception, no differing return value."""
    _register(session_factory, "+2348012345678")

    with session_factory() as session:
        known = otp_service.request(session, KNOWN)
    with session_factory() as session:
        unknown = otp_service.request(session, UNKNOWN)

    assert known == unknown


def test_otp_request_no_longer_raises_account_exists(
    otp_service: OTPService, session_factory: type[Session]
) -> None:
    _register(session_factory, "+2348012345678")
    with session_factory() as session:
        try:
            otp_service.request(session, KNOWN)
        except OTPError as exc:  # pragma: no cover - the failure we are removing
            pytest.fail(f"request leaked account state: {exc.code}")


def test_recovery_request_no_longer_raises_account_not_found(
    otp_service: OTPService, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        try:
            otp_service.request(session, UNKNOWN, allow_existing=True)
        except OTPError as exc:  # pragma: no cover
            pytest.fail(f"recovery leaked account state: {exc.code}")


def test_existence_is_revealed_only_after_successful_verification(
    otp_service: OTPService, session_factory: type[Session]
) -> None:
    """AC-01.7's intent, relocated behind proof of control of the number."""
    _register(session_factory, "+2348012345678")
    with session_factory() as session:
        otp_service.request(session, KNOWN)
        result = otp_service.verify(session, KNOWN, "123456", "android")
        assert result.is_new_user is False

    with session_factory() as session:
        otp_service.request(session, UNKNOWN)
        fresh = otp_service.verify(session, UNKNOWN, "123456", "android")
        assert fresh.is_new_user is True


# --- the uniform response must not become a flooding tool -------------------


def test_per_identifier_throttling_survives_for_an_unknown_number(
    otp_service: OTPService, session_factory: type[Session], settings, clock
) -> None:
    """Without this, the generic response is an SMS cannon aimed at anyone."""
    with session_factory() as session:
        for _ in range(settings.otp_requests_per_hour):
            otp_service.request(session, UNKNOWN)
            clock.advance(seconds=settings.otp_resend_cooldown_seconds + 1)
        with pytest.raises(OTPError) as exc:
            otp_service.request(session, UNKNOWN)
    assert exc.value.code == "rate_limited"


def test_the_resend_cooldown_still_applies(
    otp_service: OTPService, session_factory: type[Session]
) -> None:
    """Back-to-back requests are refused even below the hourly cap."""
    with session_factory() as session:
        otp_service.request(session, UNKNOWN)
        with pytest.raises(OTPError) as exc:
            otp_service.request(session, UNKNOWN)
    assert exc.value.code == "rate_limited"


def test_throttling_is_scoped_per_identifier_not_globally(
    otp_service: OTPService, session_factory: type[Session], settings, clock
) -> None:
    """One number's exhausted budget must not deny service to another."""
    with session_factory() as session:
        for _ in range(settings.otp_requests_per_hour):
            otp_service.request(session, UNKNOWN)
            clock.advance(seconds=settings.otp_resend_cooldown_seconds + 1)
        # A different number is unaffected.
        otp_service.request(session, "08055556666")


def test_rate_limiting_applies_equally_to_known_numbers(
    otp_service: OTPService, session_factory: type[Session], settings, clock
) -> None:
    """Otherwise the *rate limit itself* becomes the enumeration oracle."""
    _register(session_factory, "+2348012345678")
    with session_factory() as session:
        for _ in range(settings.otp_requests_per_hour):
            otp_service.request(session, KNOWN)
            clock.advance(seconds=settings.otp_resend_cooldown_seconds + 1)
        with pytest.raises(OTPError) as exc:
            otp_service.request(session, KNOWN)
    assert exc.value.code == "rate_limited"
    assert IdentifierKind.EMAIL is not None  # module import guard
