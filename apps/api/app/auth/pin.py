import math
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
from sqlmodel import Session, select

from app.auth.models import User
from app.auth.schemas import is_strong_pin
from app.otp.service import OTPError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PINError(OTPError):
    pass


class PINService:
    ATTEMPT_LIMIT = 5
    LOCKOUT_SECONDS = 30 * 60
    BCRYPT_ROUNDS = 12

    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self.clock = clock

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @staticmethod
    def _user_for_update(session: Session, user_id: UUID) -> User:
        statement = select(User).where(User.id == user_id).with_for_update()
        user = session.exec(statement).first()
        if user is None:
            raise PINError("invalid_access_token")
        return user

    def set_pin(self, session: Session, user_id: UUID, pin: str) -> None:
        if not is_strong_pin(pin):
            raise PINError("pin_too_weak")
        user = self._user_for_update(session, user_id)
        user.pin_hash = bcrypt.hashpw(
            pin.encode(), bcrypt.gensalt(rounds=self.BCRYPT_ROUNDS)
        ).decode()
        user.pin_failed_attempts = 0
        user.pin_locked_until = None
        user.updated_at = self.clock()
        session.add(user)
        session.commit()

    def verify_pin(self, session: Session, user_id: UUID, pin: str) -> None:
        user = self._user_for_update(session, user_id)
        if user.pin_hash is None:
            raise PINError("pin_not_set")
        now = self.clock()
        if user.pin_locked_until is not None:
            locked_until = self._aware(user.pin_locked_until)
            if now < locked_until:
                retry_after = math.ceil((locked_until - now).total_seconds())
                raise PINError("locked", retry_after)
            user.pin_failed_attempts = 0
            user.pin_locked_until = None

        if bcrypt.checkpw(pin.encode(), user.pin_hash.encode()):
            user.pin_failed_attempts = 0
            user.pin_locked_until = None
            user.updated_at = now
            session.add(user)
            session.commit()
            return

        user.pin_failed_attempts += 1
        if user.pin_failed_attempts >= self.ATTEMPT_LIMIT:
            user.pin_locked_until = now + timedelta(seconds=self.LOCKOUT_SECONDS)
            session.add(user)
            session.commit()
            raise PINError("locked", self.LOCKOUT_SECONDS)
        session.add(user)
        session.commit()
        raise PINError("invalid_pin")

    def clear_lock_after_otp(self, session: Session, user_id: UUID) -> None:
        user = self._user_for_update(session, user_id)
        user.pin_failed_attempts = 0
        user.pin_locked_until = None
        user.updated_at = self.clock()
        session.add(user)
        session.commit()
