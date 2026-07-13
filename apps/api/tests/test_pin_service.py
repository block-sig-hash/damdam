from datetime import timedelta

import pytest
from sqlmodel import Session

from app.auth.models import Platform, User
from app.auth.pin import PINError, PINService


def make_user(session: Session) -> User:
    user = User(
        phone_number="+2348012345678",
        first_name="",
        last_name="",
        platform=Platform.ANDROID,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.mark.parametrize(
    "pin",
    [
        "123",
        "12345",
        "12a4",
        "0000",
        "1111",
        "0123",
        "1234",
        "6789",
        "9876",
        "4321",
        "3210",
    ],
)
def test_rejects_non_four_digit_repeated_and_sequential_pins(
    pin: str,
    session_factory: type[Session],
    clock: object,
) -> None:
    """AC-02.1: PIN is four digits and neither repeated nor sequential."""
    service = PINService(clock=clock)
    with session_factory() as session:
        user = make_user(session)
        with pytest.raises(PINError, match="pin_too_weak"):
            service.set_pin(session, user.id, pin)


def test_pin_is_bcrypt_hashed_at_cost_twelve_and_never_returned(
    session_factory: type[Session],
    clock: object,
) -> None:
    """AC-02.2/security §10.4: only a cost-12 bcrypt hash is persisted."""
    service = PINService(clock=clock)
    with session_factory() as session:
        user = make_user(session)
        service.set_pin(session, user.id, "2580")
        session.refresh(user)

        assert user.pin_hash is not None
        assert user.pin_hash.startswith("$2b$12$")
        assert user.pin_hash != "2580"


def test_valid_pin_unlocks_and_resets_previous_failures(
    session_factory: type[Session],
    clock: object,
) -> None:
    """AC-02.3: the configured PIN unlocks the account on later opens."""
    service = PINService(clock=clock)
    with session_factory() as session:
        user = make_user(session)
        service.set_pin(session, user.id, "2580")
        with pytest.raises(PINError, match="invalid_pin"):
            service.verify_pin(session, user.id, "1357")

        service.verify_pin(session, user.id, "2580")
        session.refresh(user)
        assert user.pin_failed_attempts == 0
        assert user.pin_locked_until is None


def test_fifth_failure_locks_for_thirty_minutes(
    session_factory: type[Session],
    clock: object,
) -> None:
    """AC-02.4: five failures cause an exact 30-minute PIN lock."""
    service = PINService(clock=clock)
    with session_factory() as session:
        user = make_user(session)
        service.set_pin(session, user.id, "2580")
        for _ in range(4):
            with pytest.raises(PINError, match="invalid_pin"):
                service.verify_pin(session, user.id, "1357")

        with pytest.raises(PINError, match="locked") as caught:
            service.verify_pin(session, user.id, "1357")
        assert caught.value.retry_after == 1800

        clock.advance(minutes=29, seconds=59)
        with pytest.raises(PINError, match="locked") as caught:
            service.verify_pin(session, user.id, "2580")
        assert caught.value.retry_after == 1

        clock.advance(seconds=1)
        service.verify_pin(session, user.id, "2580")


def test_otp_recovery_clears_pin_lock_immediately(
    session_factory: type[Session],
    clock: object,
) -> None:
    """AC-02.4: verified OTP recovery clears a PIN lock immediately."""
    service = PINService(clock=clock)
    with session_factory() as session:
        user = make_user(session)
        user.pin_failed_attempts = 5
        user.pin_locked_until = clock() + timedelta(minutes=30)
        session.add(user)
        session.commit()

        service.clear_lock_after_otp(session, user.id)
        session.refresh(user)
        assert user.pin_failed_attempts == 0
        assert user.pin_locked_until is None
