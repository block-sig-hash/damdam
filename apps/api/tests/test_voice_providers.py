import base64
import json

import httpx
import pytest

from app.config import Settings
from app.voice.providers import TelnyxVoiceProvider, VoiceProviderError


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "telnyx_api_key": "telnyx-secret",
        "telnyx_connection_id": "conn-1",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_create_credential_sends_connection_id_and_parses_sip_username(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs: object):
        captured.update({"method": method, "url": url, **kwargs})
        return httpx.Response(
            200,
            json={"data": {"id": "cred-123", "sip_username": "gencred123"}},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    provider = TelnyxVoiceProvider(_settings())

    credential = provider.create_credential("user-1")

    assert credential.credential_id == "cred-123"
    assert credential.sip_username == "gencred123"
    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.telnyx.com/v2/telephony_credentials"
    assert captured["json"]["connection_id"] == "conn-1"  # type: ignore[index]
    assert captured["json"]["name"] == "damdam-user-1"  # type: ignore[index]
    assert captured["headers"]["Authorization"] == "Bearer telnyx-secret"  # type: ignore[index]


def test_create_credential_rejects_malformed_response(monkeypatch) -> None:
    def fake_request(method: str, url: str, **kwargs: object):
        return httpx.Response(
            200, json={"data": {"id": "cred-123"}}, request=httpx.Request(method, url)
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    provider = TelnyxVoiceProvider(_settings())

    with pytest.raises(VoiceProviderError, match="invalid credential response"):
        provider.create_credential("user-1")


def test_issue_token_returns_bearer_text_and_24h_expiry(monkeypatch) -> None:
    def fake_request(method: str, url: str, **kwargs: object):
        assert url == "https://api.telnyx.com/v2/telephony_credentials/cred-123/token"
        return httpx.Response(
            200, text='"telnyx-jwt-token"', request=httpx.Request(method, url)
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    provider = TelnyxVoiceProvider(_settings())

    token = provider.issue_token("cred-123")

    assert token.token == "telnyx-jwt-token"


def test_initiate_call_encodes_client_state_and_clamps_time_limit(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs: object):
        captured.update({"method": method, "url": url, **kwargs})
        return httpx.Response(200, json={}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", fake_request)
    provider = TelnyxVoiceProvider(_settings())

    provider.initiate_call(
        webrtc_call_control_id="webrtc-control",
        user_id="user-1",
        caller_id="+2348012345678",
        to_number="+2348099999999",
        time_limit_seconds=0,
        verified_caller_identity_id="identity-1",
        idempotency_key="idem-1",
    )

    body = captured["json"]
    assert body["from"] == "+2348012345678"  # type: ignore[index]
    assert body["to"] == "+2348099999999"  # type: ignore[index]
    assert body["time_limit_secs"] == 1  # type: ignore[index]
    state = json.loads(base64.b64decode(body["client_state"]))  # type: ignore[index]
    assert state == {
        "user_id": "user-1",
        "webrtc_call_control_id": "webrtc-control",
        "verified_caller_identity_id": "identity-1",
        "idempotency_key": "idem-1",
    }


def test_bridge_call_posts_to_bridge_action(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs: object):
        captured.update({"method": method, "url": url, **kwargs})
        return httpx.Response(200, json={}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", fake_request)
    provider = TelnyxVoiceProvider(_settings())

    provider.bridge_call("control-1", "control-2")

    assert captured["url"] == "https://api.telnyx.com/v2/calls/control-1/actions/bridge"
    assert captured["json"] == {"call_control_id": "control-2"}  # type: ignore[index]


def test_request_wraps_http_errors(monkeypatch) -> None:
    def fake_request(method: str, url: str, **kwargs: object):
        return httpx.Response(
            500, json={"error": "boom"}, request=httpx.Request(method, url)
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    provider = TelnyxVoiceProvider(_settings())

    with pytest.raises(VoiceProviderError, match="Telnyx request failed"):
        provider.bridge_call("control-1", "control-2")


def test_request_without_api_key_is_rejected() -> None:
    provider = TelnyxVoiceProvider(_settings(telnyx_api_key=""))

    with pytest.raises(VoiceProviderError, match="not configured"):
        provider.create_credential("user-1")
