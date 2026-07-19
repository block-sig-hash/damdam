import fakeredis
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_liveness_does_not_probe_dependencies(api: FastAPI) -> None:
    response = TestClient(api).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_probes_postgres_and_redis(api: FastAPI) -> None:
    response = TestClient(api).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"postgres": "ok", "redis": "ok"},
    }


def test_readiness_fails_when_postgres_is_unavailable(api: FastAPI) -> None:
    def unavailable_session_factory() -> None:
        raise ConnectionError("postgres unavailable")

    api.state.session_factory = unavailable_session_factory
    response = TestClient(api).get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"postgres": "unavailable", "redis": "ok"},
    }


def test_readiness_fails_when_redis_is_unavailable(api: FastAPI) -> None:
    unavailable_redis = fakeredis.FakeRedis(decode_responses=True)
    unavailable_redis.ping = lambda: (_ for _ in ()).throw(  # type: ignore[method-assign]
        ConnectionError("redis unavailable")
    )
    api.state.redis_client = unavailable_redis
    response = TestClient(api).get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"postgres": "ok", "redis": "unavailable"},
    }
