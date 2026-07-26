import hashlib
import hmac
import json
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from sqlmodel import select
from starlette.requests import Request

from app.auth.models import User
from app.auth.routes import (
    refresh_token,
    request_otp,
    request_pin_recovery,
    verify_otp,
    verify_pin_recovery,
)
from app.auth.schemas import (
    OTPRequest,
    OTPVerifyRequest,
    PINRecoveryRequest,
    RefreshRequest,
)
from app.otp.routes import termii_delivery_report
from app.otp.service import OTPError

PHONE = "08012345678"


def test_otp_request_and_verify_contract(api: FastAPI) -> None:
    """AC-01.3/01.6: documented request and verification response shapes work."""
    request = SimpleNamespace(app=api)
    sent = request_otp(OTPRequest(phone_number=PHONE, locale="fr"), request)
    verified = verify_otp(
        OTPVerifyRequest(
            phone_number=PHONE,
            otp="123456",
            platform="android",
            locale="fr",
        ),
        request,
    )

    assert sent.model_dump() == {"message": "Code de vérification envoyé"}
    assert verified.is_new_user is True
    assert verified.user.phone_number == "+2348012345678"
    assert verified.user.locale == "fr"

    rotated = refresh_token(
        RefreshRequest(refresh_token=verified.refresh_token), request
    )
    assert rotated.access_token != verified.access_token
    assert rotated.refresh_token != verified.refresh_token

    with pytest.raises(OTPError, match="invalid_refresh_token"):
        refresh_token(RefreshRequest(refresh_token=verified.refresh_token), request)


def test_departure_date_flows_through_to_the_auth_response(
    api: FastAPI, session_factory
) -> None:
    """US-13 AC-13.7: the date-driven Home banner trigger depends on a real
    departure_date reaching the mobile client through login, not a stub —
    regression coverage for the actual `AuthResponse.model_validate(result,
    from_attributes=True)` plumbing, not just that the field exists on the
    Pydantic schema."""
    request = SimpleNamespace(app=api)
    request_otp(OTPRequest(phone_number=PHONE), request)
    first_login = verify_otp(
        OTPVerifyRequest(phone_number=PHONE, otp="123456", platform="android"),
        request,
    )
    assert first_login.user.departure_date is None

    with session_factory() as session:
        user = session.exec(
            select(User).where(User.phone_number == "+2348012345678")
        ).one()
        user.departure_date = date(2026, 8, 1)
        session.add(user)
        session.commit()

    request_pin_recovery(PINRecoveryRequest(phone_number=PHONE), request)
    second_login = verify_pin_recovery(
        OTPVerifyRequest(phone_number=PHONE, otp="123456", platform="android"),
        request,
    )

    assert second_login.user.departure_date == date(2026, 8, 1)


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
