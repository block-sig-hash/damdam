from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import fakeredis
import pytest
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import Settings
from app.main import create_app
from app.otp.providers.base import OTPDispatch, OTPProviderError
from app.otp.service import OTPService


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass
class MutableClock:
    value: datetime = field(
        default_factory=lambda: datetime(2026, 7, 13, tzinfo=timezone.utc)
    )

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: float) -> None:
        self.value += timedelta(**kwargs)


class FakeProvider:
    def __init__(self, name: str, code: str) -> None:
        self.name = name
        self.code = code
        self.send_calls: list[str] = []
        self.verify_calls: list[tuple[str, str, str]] = []
        self.fail_send = False
        self.fail_verify = False

    def send(self, phone_number: str, locale: str = "en") -> OTPDispatch:
        del locale
        if self.fail_send:
            raise OTPProviderError(f"{self.name} unavailable")
        self.send_calls.append(phone_number)
        suffix = len(self.send_calls)
        return OTPDispatch(
            reference=f"{self.name}-verification-{suffix}",
            delivery_reference=f"{self.name}-message-{suffix}",
        )

    def verify(self, phone_number: str, code: str, reference: str) -> bool:
        if self.fail_verify:
            raise OTPProviderError(f"{self.name} unavailable")
        self.verify_calls.append((phone_number, code, reference))
        return code == self.code


class FakeScheduler:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def schedule_failover(
        self, phone_number: str, challenge_id: str, countdown: int
    ) -> None:
        self.calls.append((phone_number, challenge_id, countdown))


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="sqlite://",
        redis_url="redis://unused",
        jwt_secret="test-secret-at-least-32-characters-long",
        otp_provider_primary="termii",
        otp_provider_secondary="twilio",
        otp_failover_threshold_seconds=180,
        otp_request_timeout_seconds=10,
        termii_webhook_secret="termii-webhook-secret",
    )


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock()


@pytest.fixture
def redis_client() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def providers() -> dict[str, FakeProvider]:
    return {
        "termii": FakeProvider("termii", "123456"),
        "twilio": FakeProvider("twilio", "654321"),
    }


@pytest.fixture
def scheduler() -> FakeScheduler:
    return FakeScheduler()


@pytest.fixture
def session_factory() -> Generator[type[Session], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def factory() -> Session:
        return Session(engine)

    yield factory  # type: ignore[misc]
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def otp_service(
    settings: Settings,
    redis_client: fakeredis.FakeRedis,
    providers: dict[str, FakeProvider],
    scheduler: FakeScheduler,
    clock: MutableClock,
) -> OTPService:
    return OTPService(
        settings=settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        clock=clock,
    )


@pytest.fixture
def api(
    settings: Settings,
    redis_client: fakeredis.FakeRedis,
    providers: dict[str, FakeProvider],
    scheduler: FakeScheduler,
    clock: MutableClock,
    session_factory: type[Session],
) -> FastAPI:
    return create_app(
        settings=settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
    )
