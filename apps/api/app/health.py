from typing import Literal

from pydantic import BaseModel
from redis import Redis

from app.db import SessionFactory


class DependencyChecks(BaseModel):
    postgres: Literal["ok", "unavailable"]
    redis: Literal["ok", "unavailable"]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: DependencyChecks


class LivenessResponse(BaseModel):
    status: Literal["alive"] = "alive"


def check_readiness(
    session_factory: SessionFactory, redis_client: Redis
) -> ReadinessResponse:
    postgres_status: Literal["ok", "unavailable"] = "ok"
    redis_status: Literal["ok", "unavailable"] = "ok"

    try:
        with session_factory() as session:
            session.connection().exec_driver_sql("SELECT 1")
    except Exception:
        postgres_status = "unavailable"

    try:
        redis_client.ping()
    except Exception:
        redis_status = "unavailable"

    ready = postgres_status == "ok" and redis_status == "ok"
    return ReadinessResponse(
        status="ready" if ready else "not_ready",
        checks=DependencyChecks(postgres=postgres_status, redis=redis_status),
    )
