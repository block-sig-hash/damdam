import pytest
from sqlmodel import Session

from app.auth.models import User
from app.otp.service import OTPError, OTPService

PHONE = "08012345678"


def test_request_dispatches_primary_six_digit_otp_and_schedules_failover(
    otp_service: OTPService,
    session_factory: type[Session],
    providers: dict,
    scheduler: object,
) -> None:
    """AC-01.3/01.8: primary sends six digits and failover is automatic."""
    with session_factory() as session:
        otp_service.request(session, PHONE)

    assert providers["termii"].send_calls == ["+2348012345678"]
    assert providers["twilio"].send_calls == []
    assert scheduler.calls[0][0] == PHONE
    assert scheduler.calls[0][2] == 180


def test_otp_expires_after_ten_minutes(
    otp_service: OTPService,
    session_factory: type[Session],
    clock: object,
) -> None:
    """AC-01.4: OTP expires after 10 minutes."""
    with session_factory() as session:
        otp_service.request(session, PHONE)
        clock.advance(minutes=10, seconds=1)
        with pytest.raises(OTPError, match="otp_expired"):
            otp_service.verify(session, PHONE, "123456", "android")


def test_third_failed_attempt_locks_for_sixty_seconds(
    otp_service: OTPService,
    session_factory: type[Session],
    clock: object,
) -> None:
    """AC-01.5: three failed attempts cause a 60-second lockout."""
    with session_factory() as session:
        otp_service.request(session, PHONE)
        for _ in range(2):
            with pytest.raises(OTPError, match="invalid_otp"):
                otp_service.verify(session, PHONE, "000000", "android")
        with pytest.raises(OTPError, match="locked") as caught:
            otp_service.verify(session, PHONE, "000000", "android")
        assert caught.value.retry_after == 60

        clock.advance(seconds=59)
        with pytest.raises(OTPError, match="locked"):
            otp_service.verify(session, PHONE, "123456", "android")

        clock.advance(seconds=1)
        result = otp_service.verify(session, PHONE, "123456", "android")
        assert result.is_new_user is True


def test_success_creates_account_and_returns_session(
    otp_service: OTPService,
    session_factory: type[Session],
) -> None:
    """AC-01.6: successful verification creates and logs in the pilgrim."""
    with session_factory() as session:
        otp_service.request(session, PHONE)
        result = otp_service.verify(session, PHONE, "123456", "ios")
        user = session.get(User, result.user.id)

    assert result.is_new_user is True
    assert result.access_token
    assert result.refresh_token
    assert user is not None
    assert user.phone_number == "+2348012345678"
    assert user.platform == "ios"


def test_existing_account_is_directed_to_login(
    otp_service: OTPService,
    session_factory: type[Session],
) -> None:
    """AC-01.7: signup request for an existing account returns account_exists."""
    with session_factory() as session:
        session.add(
            User(
                phone_number="+2348012345678",
                first_name="",
                last_name="",
                platform="android",
                account_source="direct",
            )
        )
        session.commit()
        with pytest.raises(OTPError, match="account_exists"):
            otp_service.request(session, PHONE)


def test_unconfirmed_primary_fails_over_after_configured_threshold(
    otp_service: OTPService,
    session_factory: type[Session],
    providers: dict,
    clock: object,
) -> None:
    """AC-01.8: no primary delivery report triggers secondary automatically."""
    with session_factory() as session:
        otp_service.request(session, PHONE)

    assert otp_service.failover(PHONE) is False
    clock.advance(seconds=180)
    assert otp_service.failover(PHONE) is True
    assert providers["twilio"].send_calls == ["+2348012345678"]
    assert otp_service.failover(PHONE) is False


def test_delivery_confirmation_suppresses_failover(
    otp_service: OTPService,
    session_factory: type[Session],
    providers: dict,
    clock: object,
) -> None:
    """AC-01.8: a confirmed primary delivery never duplicates via secondary."""
    with session_factory() as session:
        otp_service.request(session, PHONE)
    otp_service.confirm_delivery("termii-message-1", "DELIVERED")
    clock.advance(seconds=180)

    assert otp_service.failover(PHONE) is False
    assert providers["twilio"].send_calls == []


def test_resend_available_at_thirty_seconds_and_rate_limited_per_hour(
    otp_service: OTPService,
    session_factory: type[Session],
    clock: object,
) -> None:
    """AC-01.9/PRD §5.1: resend cooldown is 30s and max three requests/hour."""
    with session_factory() as session:
        otp_service.request(session, PHONE)
        with pytest.raises(OTPError, match="rate_limited") as caught:
            otp_service.request(session, PHONE)
        assert caught.value.retry_after == 30

        clock.advance(seconds=30)
        otp_service.request(session, PHONE)
        clock.advance(seconds=30)
        otp_service.request(session, PHONE)
        clock.advance(seconds=30)
        with pytest.raises(OTPError, match="rate_limited"):
            otp_service.request(session, PHONE)


def test_primary_failure_immediately_uses_secondary(
    otp_service: OTPService,
    session_factory: type[Session],
    providers: dict,
    scheduler: object,
) -> None:
    """PRD §5.1: a provider outage is hidden while the fallback remains available."""
    providers["termii"].fail_send = True
    with session_factory() as session:
        otp_service.request(session, PHONE)

    assert providers["twilio"].send_calls == ["+2348012345678"]
    assert scheduler.calls == []


def test_stale_failover_task_cannot_fallback_a_newer_resend(
    otp_service: OTPService,
    session_factory: type[Session],
    scheduler: object,
    providers: dict,
    clock: object,
) -> None:
    """AC-01.8/01.9: an older timer cannot prematurely fail over a resend."""
    with session_factory() as session:
        otp_service.request(session, PHONE)
        old_challenge_id = scheduler.calls[0][1]
        clock.advance(seconds=30)
        otp_service.request(session, PHONE)
        clock.advance(seconds=150)

    assert otp_service.failover(PHONE, old_challenge_id) is False
    assert providers["twilio"].send_calls == []


def test_one_reachable_provider_can_still_reject_an_invalid_code(
    otp_service: OTPService,
    session_factory: type[Session],
    providers: dict,
    clock: object,
) -> None:
    """AC-01.5: a secondary outage does not hide a primary invalid-code result."""
    with session_factory() as session:
        otp_service.request(session, PHONE)
        clock.advance(seconds=180)
        otp_service.failover(PHONE)
        providers["twilio"].fail_verify = True
        with pytest.raises(OTPError, match="invalid_otp"):
            otp_service.verify(session, PHONE, "000000", "android")
