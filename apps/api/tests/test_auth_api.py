import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from app.auth.routes import refresh_token, request_otp, verify_otp
from app.auth.schemas import OTPRequest, OTPVerifyRequest, RefreshRequest
from app.otp.routes import termii_delivery_report
from app.otp.service import OTPError

PHONE = "08012345678"


def test_otp_request_and_verify_contract(api: FastAPI) -> None:
    """AC-01.3/01.6: documented request and verification response shapes work."""
    request = SimpleNamespace(app=api)
    sent = request_otp(OTPRequest(phone_number=PHONE), request)
    verified = verify_otp(
        OTPVerifyRequest(phone_number=PHONE, otp="123456", platform="android"),
        request,
    )

    assert sent.model_dump() == {"message": "OTP sent"}
    assert verified.is_new_user is True
    assert verified.user.phone_number == "+2348012345678"

    rotated = refresh_token(
        RefreshRequest(refresh_token=verified.refresh_token), request
    )
    assert rotated.access_token != verified.access_token
    assert rotated.refresh_token != verified.refresh_token

    with pytest.raises(OTPError, match="invalid_refresh_token"):
        refresh_token(RefreshRequest(refresh_token=verified.refresh_token), request)


@pytest.mark.anyio
async def test_termii_webhook_requires_signature_and_confirms_delivery(
    api: FastAPI,
    providers: dict,
) -> None:
    """AC-01.8: only an authentic Termii delivery report suppresses failover."""
    request_otp(OTPRequest(phone_number=PHONE), SimpleNamespace(app=api))
    body = json.dumps(
        {"message_id": "termii-message-1", "status": "DELIVERED"},
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(b"termii-webhook-secret", body, hashlib.sha512).hexdigest()

    def make_request(provided_signature: str) -> Request:
        consumed = False

        async def receive() -> dict:
            nonlocal consumed
            if consumed:
                return {"type": "http.disconnect"}
            consumed = True
            return {"type": "http.request", "body": body, "more_body": False}

        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/v1/webhooks/otp/termii",
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"x-termii-signature", provided_signature.encode()),
                ],
                "app": api,
            },
            receive,
        )

    with pytest.raises(OTPError, match="invalid_webhook_signature"):
        await termii_delivery_report(make_request("bad"))
    accepted = await termii_delivery_report(make_request(signature))

    assert accepted == {"received": True}
