from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.config import Settings
from app.esim.providers import (
    EsimAccessProvider,
    EsimIssueRequest,
    EsimProviderError,
    EsimProviderPending,
    HttpEsimProvider,
    build_esim_providers,
)


def test_http_adapter_sends_package_id_as_vendor_idempotency_key(monkeypatch) -> None:
    package_id = uuid4()
    captured: dict[str, object] = {}

    def post(url: str, **kwargs: object) -> object:
        captured.update(url=url, **kwargs)
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "data": {
                    "iccid": "8944501234567890123456",
                    "lpa": "LPA:1$vendor.example$match",
                    "qr_code_url": "https://cdn.example/qr.png",
                }
            },
        )

    monkeypatch.setattr(httpx, "post", post)
    provider = HttpEsimProvider("monty_mobile", "https://vendor.example", "key", 20)

    issued = provider.issue(EsimIssueRequest(package_id, uuid4(), 5, "SA"))

    assert issued.iccid == "8944501234567890123456"
    assert captured["url"] == "https://vendor.example/esims"
    assert captured["headers"] == {
        "Authorization": "Bearer key",
        "Idempotency-Key": str(package_id),
    }
    assert captured["json"] == {
        "package_reference": str(package_id),
        "destination_country": "SA",
        "data_gb": 5,
    }


def test_http_adapter_normalizes_configuration_and_vendor_failures(monkeypatch) -> None:
    settings = Settings(
        app_env="test",
        jwt_secret="test-secret-at-least-32-characters-long",
        monty_mobile_base_url="https://monty.example",
        monty_mobile_api_key="monty-key",
    )
    providers = build_esim_providers(settings)
    assert set(providers) == {"monty_mobile", "esim_access", "1global"}

    with pytest.raises(EsimProviderError, match="not configured"):
        providers["esim_access"].issue(EsimIssueRequest(uuid4(), uuid4(), 5, "SA"))

    def unavailable(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "post", unavailable)
    with pytest.raises(EsimProviderError, match="issuance failed"):
        providers["monty_mobile"].issue(EsimIssueRequest(uuid4(), uuid4(), 5, "SA"))


def test_esim_access_uses_signed_order_then_query_contract(monkeypatch) -> None:
    package_id = uuid4()
    requests: list[tuple[str, dict[str, object]]] = []
    responses = iter(
        [
            {"success": True, "obj": {"orderNo": "ORDER-1"}},
            {"success": False, "errorCode": "200010"},
            {
                "success": True,
                "obj": {
                    "esimList": [
                        {
                            "iccid": "8944501234567890123456",
                            "ac": "LPA:1$access.example$match",
                            "qrCodeUrl": "https://p.qrsim.net/qr.png",
                        }
                    ]
                },
            },
        ]
    )

    def post(url: str, **kwargs: object) -> object:
        requests.append((url, kwargs))
        payload = next(responses)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)

    monkeypatch.setattr(httpx, "post", post)
    settings = Settings(
        app_env="test",
        jwt_secret="test-secret-at-least-32-characters-long",
        esim_access_access_code="access",
        esim_access_secret_key="secret",
        esim_access_package_codes={"SA:5": "SA_5GB"},
    )
    provider = EsimAccessProvider(settings, monotonic=lambda: 0, sleeper=lambda _: None)

    issued = provider.issue(EsimIssueRequest(package_id, uuid4(), 5, "SA"))

    assert issued.qr_code_url == "https://p.qrsim.net/qr.png"
    assert requests[0][0].endswith("/api/v1/open/esim/order")
    order_body = str(requests[0][1]["content"])
    assert f'"transactionId":"{package_id}"' in order_body
    assert '"packageCode":"SA_5GB"' in order_body
    headers = requests[0][1]["headers"]
    assert isinstance(headers, dict)
    assert headers["RT-AccessCode"] == "access"
    assert len(str(headers["RT-Signature"])) == 64
    assert requests[1][0].endswith("/api/v1/open/esim/query")


def test_esim_access_query_error_after_accepted_order_is_pending(monkeypatch) -> None:
    calls = 0

    def post(url: str, **kwargs: object) -> object:
        nonlocal calls
        del url, kwargs
        calls += 1
        if calls == 1:
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"success": True, "obj": {"orderNo": "ORDER-1"}},
            )
        raise httpx.ConnectError("query connection reset")

    monkeypatch.setattr(httpx, "post", post)
    settings = Settings(
        app_env="test",
        jwt_secret="test-secret-at-least-32-characters-long",
        esim_access_access_code="access",
        esim_access_secret_key="secret",
        esim_access_package_codes={"SA:5": "SA_5GB"},
    )
    provider = EsimAccessProvider(settings, monotonic=lambda: 0, sleeper=lambda _: None)

    with pytest.raises(EsimProviderPending, match="status is temporarily unavailable"):
        provider.issue(EsimIssueRequest(uuid4(), uuid4(), 5, "SA"))

    assert calls == 2


def test_esim_access_rejects_unconfigured_destination_tier() -> None:
    settings = Settings(
        app_env="test",
        jwt_secret="test-secret-at-least-32-characters-long",
        esim_access_access_code="access",
        esim_access_secret_key="secret",
        esim_access_package_codes={"SA:5": "SA_5GB"},
    )

    with pytest.raises(EsimProviderError, match="not configured for this tier"):
        EsimAccessProvider(settings).issue(
            EsimIssueRequest(uuid4(), uuid4(), 5, "KE")
        )


def test_settings_parses_destination_package_codes_from_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ESIM_ACCESS_PACKAGE_CODES", '{"SA:5":"SA_5GB"}')

    settings = Settings(
        app_env="test",
        jwt_secret="test-secret-at-least-32-characters-long",
    )

    assert settings.esim_access_package_codes == {"SA:5": "SA_5GB"}
