import httpx
import pytest

from app.config import Settings
from app.otp.providers.base import OTPProviderError
from app.otp.providers.termii import TermiiProvider
from app.otp.providers.twilio import TwilioVerifyProvider


def client_for(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler, base_url="https://provider.test")


def test_termii_send_and_verify_use_managed_six_digit_token(
    settings: Settings,
) -> None:
    settings.termii_api_key = "termii-key"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/send"):
            payload = __import__("json").loads(request.content)
            assert payload["pin_length"] == 6
            assert payload["pin_time_to_live"] == 10
            assert payload["to"] == "2348012345678"
            return httpx.Response(
                200,
                json={"pin_id": "pin-1", "message_id_str": "message-1"},
            )
        return httpx.Response(200, json={"verified": "True"})

    provider = TermiiProvider(settings, client_for(httpx.MockTransport(handler)))
    dispatch = provider.send("+2348012345678")

    assert dispatch.reference == "pin-1"
    assert dispatch.delivery_reference == "message-1"
    assert provider.verify("+2348012345678", "123456", "pin-1") is True


def test_termii_rejects_bad_response_and_unconfigured_credentials(
    settings: Settings,
) -> None:
    provider = TermiiProvider(
        settings,
        client_for(httpx.MockTransport(lambda request: httpx.Response(200, json={}))),
    )
    with pytest.raises(OTPProviderError, match="not configured"):
        provider.send("+2348012345678")

    settings.termii_api_key = "termii-key"
    with pytest.raises(OTPProviderError, match="omitted references"):
        provider.send("+2348012345678")


def test_twilio_send_and_verify_contract(settings: Settings) -> None:
    settings.twilio_account_sid = "AC123"
    settings.twilio_auth_token = "secret"
    settings.twilio_verify_service_sid = "VA123"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Verifications"):
            assert b"To=%2B2348012345678" in request.content
            assert b"Channel=sms" in request.content
            return httpx.Response(201, json={"sid": "VE123"})
        return httpx.Response(200, json={"status": "approved"})

    provider = TwilioVerifyProvider(settings, client_for(httpx.MockTransport(handler)))
    dispatch = provider.send("+2348012345678")

    assert dispatch.reference == "VE123"
    assert provider.verify("+2348012345678", "654321", "VE123") is True


def test_twilio_missing_credentials_and_expired_check(settings: Settings) -> None:
    provider = TwilioVerifyProvider(
        settings,
        client_for(httpx.MockTransport(lambda request: httpx.Response(404))),
    )
    with pytest.raises(OTPProviderError, match="not configured"):
        provider.send("+2348012345678")

    settings.twilio_account_sid = "AC123"
    settings.twilio_auth_token = "secret"
    settings.twilio_verify_service_sid = "VA123"
    assert provider.verify("+2348012345678", "000000", "VE123") is False
