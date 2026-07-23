import json
import math
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.auth.models import AccountSource, Locale, Platform, User
from app.auth.schemas import to_e164
from app.auth.tokens import TokenService
from app.config import Settings
from app.otp.providers.base import OTPDispatch, OTPProvider, OTPProviderError


class FailoverScheduler(Protocol):
    def schedule_failover(
        self, phone_number: str, challenge_id: str, countdown: int
    ) -> None: ...


class RedisClient(Protocol):
    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str, ex: int, nx: bool = False) -> object: ...

    def delete(self, *names: str) -> int: ...

    def zremrangebyscore(self, name: str, minimum: object, maximum: object) -> int: ...

    def zrevrange(
        self, name: str, start: int, end: int, withscores: bool
    ) -> list[tuple[str, float]]: ...

    def zrange(
        self, name: str, start: int, end: int, withscores: bool
    ) -> list[tuple[str, float]]: ...

    def zcard(self, name: str) -> int: ...

    def zadd(self, name: str, mapping: dict[str, float]) -> int: ...

    def expire(self, name: str, time: int) -> bool: ...


class OTPError(Exception):
    def __init__(self, code: str, retry_after: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


@dataclass
class Challenge:
    id: str
    purpose: str
    phone_number: str
    created_at: str
    expires_at: str
    attempts: int
    locked_until: str | None
    primary_provider: str
    primary_reference: str
    primary_delivery_reference: str
    primary_delivered: bool
    secondary_provider: str
    secondary_reference: str | None = None
    secondary_delivery_reference: str | None = None
    locale: str = Locale.EN.value


@dataclass(frozen=True)
class AuthResult:
    access_token: str
    refresh_token: str
    user: User
    is_new_user: bool


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OTPService:
    def __init__(
        self,
        settings: Settings,
        redis_client: RedisClient,
        providers: Mapping[str, OTPProvider],
        scheduler: FailoverScheduler,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.settings = settings
        self.redis = redis_client
        self.providers = providers
        self.scheduler = scheduler
        self.clock = clock
        self.tokens = TokenService(settings)

    @staticmethod
    def _challenge_key(phone_number: str) -> str:
        return f"otp:challenge:{phone_number}"

    @staticmethod
    def _delivery_key(provider: str, reference: str) -> str:
        return f"otp:delivery:{provider}:{reference}"

    @staticmethod
    def _rate_key(phone_number: str, scope: str) -> str:
        return f"otp:requests:{scope}:{phone_number}"

    def _load(self, phone_number: str) -> Challenge | None:
        value = self.redis.get(self._challenge_key(phone_number))
        if value is None:
            return None
        return Challenge(**json.loads(value))

    def _save(self, challenge: Challenge) -> None:
        expiry = datetime.fromisoformat(challenge.expires_at)
        ttl = max(1, math.ceil((expiry - self.clock()).total_seconds()))
        self.redis.set(
            self._challenge_key(challenge.phone_number),
            json.dumps(asdict(challenge)),
            ex=ttl,
        )

    def _remember_delivery(self, challenge: Challenge, dispatch: OTPDispatch) -> None:
        self.redis.set(
            self._delivery_key(challenge.primary_provider, dispatch.delivery_reference),
            json.dumps({"phone_number": challenge.phone_number, "id": challenge.id}),
            ex=self.settings.otp_ttl_seconds,
        )

    def _check_request_limit(self, phone_number: str, scope: str) -> None:
        now = self.clock().timestamp()
        key = self._rate_key(phone_number, scope)
        cutoff = now - 3600
        self.redis.zremrangebyscore(key, "-inf", cutoff)
        most_recent = self.redis.zrevrange(key, 0, 0, withscores=True)
        if most_recent:
            elapsed = now - float(most_recent[0][1])
            if elapsed < self.settings.otp_resend_cooldown_seconds:
                raise OTPError(
                    "rate_limited",
                    math.ceil(self.settings.otp_resend_cooldown_seconds - elapsed),
                )
        if self.redis.zcard(key) >= self.settings.otp_requests_per_hour:
            oldest = self.redis.zrange(key, 0, 0, withscores=True)
            retry_after = math.ceil(3600 - (now - float(oldest[0][1])))
            raise OTPError("rate_limited", retry_after)
        member = f"{now}:{uuid4()}"
        self.redis.zadd(key, {member: now})
        self.redis.expire(key, 3600)

    def request(
        self,
        session: Session,
        phone_number: str,
        allow_existing: bool = False,
        locale: Locale = Locale.EN,
    ) -> None:
        e164 = to_e164(phone_number)
        existing = session.exec(select(User).where(User.phone_number == e164)).first()
        if existing is not None and not allow_existing:
            raise OTPError("account_exists")
        if existing is None and allow_existing:
            raise OTPError("account_not_found")
        rate_scope = "recovery" if allow_existing else "signup"
        self._check_request_limit(phone_number, rate_scope)

        primary_name = self.settings.otp_provider_primary
        secondary_name = self.settings.otp_provider_secondary
        try:
            dispatch = self.providers[primary_name].send(e164, locale.value)
        except OTPProviderError:
            try:
                dispatch = self.providers[secondary_name].send(e164, locale.value)
            except OTPProviderError as exc:
                raise OTPError("otp_unavailable") from exc
            challenge = self._new_challenge(
                phone_number,
                rate_scope,
                secondary_name,
                dispatch,
                primary_name,
                locale,
            )
            challenge.primary_delivered = True
            self._save(challenge)
            return

        challenge = self._new_challenge(
            phone_number,
            rate_scope,
            primary_name,
            dispatch,
            secondary_name,
            locale,
        )
        self._save(challenge)
        self._remember_delivery(challenge, dispatch)
        self.scheduler.schedule_failover(
            phone_number,
            challenge.id,
            self.settings.otp_failover_threshold_seconds,
        )

    def _new_challenge(
        self,
        phone_number: str,
        purpose: str,
        primary_name: str,
        dispatch: OTPDispatch,
        secondary_name: str,
        locale: Locale,
    ) -> Challenge:
        now = self.clock()
        return Challenge(
            id=str(uuid4()),
            purpose=purpose,
            phone_number=phone_number,
            created_at=now.isoformat(),
            expires_at=(
                now + timedelta(seconds=self.settings.otp_ttl_seconds)
            ).isoformat(),
            attempts=0,
            locked_until=None,
            primary_provider=primary_name,
            primary_reference=dispatch.reference,
            primary_delivery_reference=dispatch.delivery_reference,
            primary_delivered=False,
            secondary_provider=secondary_name,
            locale=locale.value,
        )

    def failover(self, phone_number: str, challenge_id: str | None = None) -> bool:
        challenge = self._load(phone_number)
        if challenge is None:
            return False
        if challenge_id is not None and challenge.id != challenge_id:
            return False
        if challenge.primary_delivered or challenge.secondary_reference is not None:
            return False
        failover_at = datetime.fromisoformat(challenge.created_at) + timedelta(
            seconds=self.settings.otp_failover_threshold_seconds
        )
        if self.clock() < failover_at:
            return False
        if self.clock() >= datetime.fromisoformat(challenge.expires_at):
            return False
        try:
            dispatch = self.providers[challenge.secondary_provider].send(
                to_e164(phone_number), challenge.locale
            )
        except OTPProviderError:
            return False
        challenge.secondary_reference = dispatch.reference
        challenge.secondary_delivery_reference = dispatch.delivery_reference
        self._save(challenge)
        return True

    def confirm_delivery(
        self, provider: str, delivery_reference: str, status: str
    ) -> bool:
        if status.upper() != "DELIVERED":
            return False
        raw = self.redis.get(self._delivery_key(provider, delivery_reference))
        if raw is None:
            return False
        correlation: dict[str, Any] = json.loads(raw)
        challenge = self._load(str(correlation["phone_number"]))
        if challenge is None or challenge.id != correlation["id"]:
            return False
        challenge.primary_delivered = True
        self._save(challenge)
        return True

    def verify(
        self,
        session: Session,
        phone_number: str,
        code: str,
        platform: Platform,
        locale: Locale = Locale.EN,
        purpose: str = "signup",
    ) -> AuthResult:
        challenge = self._load(phone_number)
        if challenge is None:
            raise OTPError("otp_expired")
        if challenge.purpose != purpose:
            raise OTPError("invalid_otp")
        now = self.clock()
        if now >= datetime.fromisoformat(challenge.expires_at):
            raise OTPError("otp_expired")
        if challenge.locked_until is not None:
            locked_until = datetime.fromisoformat(challenge.locked_until)
            if now < locked_until:
                retry_after = math.ceil((locked_until - now).total_seconds())
                raise OTPError("locked", retry_after)
            challenge.locked_until = None
            challenge.attempts = 0

        verified = self._verify_with_providers(challenge, code)
        if not verified:
            challenge.attempts += 1
            if challenge.attempts >= self.settings.otp_attempt_limit:
                challenge.locked_until = (
                    now + timedelta(seconds=self.settings.otp_lockout_seconds)
                ).isoformat()
                self._save(challenge)
                raise OTPError("locked", self.settings.otp_lockout_seconds)
            self._save(challenge)
            raise OTPError("invalid_otp")

        e164 = to_e164(phone_number)
        user = session.exec(select(User).where(User.phone_number == e164)).first()
        is_new_user = user is None
        if user is None:
            user = User(
                phone_number=e164,
                first_name="",
                last_name="",
                platform=platform,
                account_source=AccountSource.DIRECT,
                locale=locale,
                last_login_at=now,
            )
            session.add(user)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                user = session.exec(select(User).where(User.phone_number == e164)).one()
                is_new_user = False
        else:
            user.last_login_at = now
            user.locale = locale

        pair = self.tokens.issue(session, user, now)
        session.commit()
        session.refresh(user)
        self.redis.delete(self._challenge_key(phone_number))
        return AuthResult(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            user=user,
            is_new_user=is_new_user,
        )

    def _verify_with_providers(self, challenge: Challenge, code: str) -> bool:
        e164 = to_e164(challenge.phone_number)
        available = False
        attempts = [(challenge.primary_provider, challenge.primary_reference)]
        if challenge.secondary_reference is not None:
            attempts.append(
                (challenge.secondary_provider, challenge.secondary_reference)
            )
        for provider_name, reference in attempts:
            try:
                if self.providers[provider_name].verify(e164, code, reference):
                    return True
                available = True
            except OTPProviderError:
                continue
        if not available:
            raise OTPError("otp_unavailable")
        return False
