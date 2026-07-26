import httpx
import pytest

from app.config import Settings
from app.voice.verified_numbers import (
    MockIdentityProvider,
    PhoneVerificationProviderError,
    TelnyxVerifiedNumbersProvider,
)


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {"telnyx_api_key": "telnyx-secret"}
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_start_verification_returns_provider_reference(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs: object):
        captured.update({"method": method, "url": url, **kwargs})
        return httpx.Response(
            200, json={"data": {"id": "vn-1"}}, request=httpx.Request(method, url)
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    provider = TelnyxVerifiedNumbersProvider(_settings())

    attempt = provider.start_verification("+2348012345678")

    assert attempt.reference == "vn-1"
    assert captured["json"]["phone_number"] == "+2348012345678"  # type: ignore[index]
    assert captured["url"].endswith("/verified_numbers")  # type: ignore[union-attr]


def test_confirm_verification_true_only_when_status_verified(monkeypatch) -> None:
    def fake_request(method: str, url: str, **kwargs: object):
        del method, kwargs
        assert url.endswith("/verified_numbers/vn-1/actions/verify")
        return httpx.Response(
            200,
            json={"data": {"status": "verified"}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    provider = TelnyxVerifiedNumbersProvider(_settings())

    assert provider.confirm_verification("vn-1", "123456") is True


def test_confirm_verification_false_on_non_verified_status(monkeypatch) -> None:
    def fake_request(method: str, url: str, **kwargs: object):
        del method, url, kwargs
        return httpx.Response(
            200,
            json={"data": {"status": "failed"}},
            request=httpx.Request("POST", "http://x/verified_numbers/vn-1/actions/verify"),
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    provider = TelnyxVerifiedNumbersProvider(_settings())

    assert provider.confirm_verification("vn-1", "000000") is False


def test_missing_api_key_raises_before_any_request() -> None:
    provider = TelnyxVerifiedNumbersProvider(_settings(telnyx_api_key=""))

    with pytest.raises(PhoneVerificationProviderError):
        provider.start_verification("+2348012345678")


def test_http_error_is_wrapped(monkeypatch) -> None:
    def fake_request(method: str, url: str, **kwargs: object):
        del kwargs
        return httpx.Response(500, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", fake_request)
    provider = TelnyxVerifiedNumbersProvider(_settings())

    with pytest.raises(PhoneVerificationProviderError):
        provider.start_verification("+2348012345678")


def test_mock_identity_provider_never_reports_a_match() -> None:
    """LABELED MOCK invariant (verified-cli-scoping.md §4): must never
    silently report a real identity match, even given plausible inputs."""
    provider = MockIdentityProvider()

    result = provider.verify_identity("12345678901", "+2348012345678")

    assert result.status == "rejected"
    assert result.nin_msisdn_match_status == "unavailable"
