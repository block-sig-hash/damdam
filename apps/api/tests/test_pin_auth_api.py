import json
from contextlib import suppress
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError

from app.auth.dependencies import get_current_user
from app.auth.pin import PINError
from app.auth.routes import (
    request_otp,
    request_pin_recovery,
    set_pin,
    verify_otp,
    verify_pin,
    verify_pin_recovery,
)
from app.auth.schemas import (
    OTPRequest,
    OTPVerifyRequest,
    PINPayload,
    PINRecoveryRequest,
)
from app.otp.service import OTPError

PHONE = "08012345678"


def register(api: FastAPI) -> tuple[SimpleNamespace, object]:
    request = SimpleNamespace(app=api)
    request_otp(OTPRequest(phone_number=PHONE), request)
    auth = verify_otp(
        OTPVerifyRequest(phone_number=PHONE, otp="123456", platform="android"),
        request,
    )
    return request, auth


def authenticated_user(api: FastAPI, access_token: str) -> object:
    return get_current_user(
        SimpleNamespace(app=api),
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=access_token),
    )


def test_pin_set_and_verify_api_contract(api: FastAPI) -> None:
    """AC-02.2/02.3: authenticated setup never echoes PIN and verify unlocks."""
    request, auth = register(api)
    user = authenticated_user(api, auth.access_token)

    configured = set_pin(PINPayload(pin="2580"), request, user)
    unlocked = verify_pin(PINPayload(pin="2580"), request, user)

    assert configured.model_dump() == {"message": "PIN set"}
    assert unlocked.model_dump() == {"unlocked": True}


@pytest.mark.anyio
async def test_pin_payload_validation_preserves_pin_too_weak_contract(
    api: FastAPI,
) -> None:
    """AC-02.1: schema validation retains the documented 400 error contract."""
    with pytest.raises(ValidationError) as validation:
        PINPayload(pin="1234")

    error = validation.value.errors()[0]
    assert error["type"] == "pin_too_weak"
    handler = api.exception_handlers[RequestValidationError]
    response = await handler(
        SimpleNamespace(), RequestValidationError(validation.value.errors())
    )
    assert response.status_code == 400
    assert json.loads(response.body)["error"] == "pin_too_weak"


def test_pin_endpoints_reject_invalid_access_token(api: FastAPI) -> None:
    """AC-02.3: PIN operations require a valid pilgrim access session."""
    with pytest.raises(PINError, match="invalid_access_token"):
        authenticated_user(api, "not-a-jwt")


def test_signup_otp_cannot_be_used_as_recovery_otp(api: FastAPI) -> None:
    """AC-02.4: recovery accepts only an OTP requested for PIN recovery."""
    request = SimpleNamespace(app=api)
    request_otp(OTPRequest(phone_number=PHONE), request)

    with pytest.raises(OTPError, match="invalid_otp"):
        verify_pin_recovery(
            OTPVerifyRequest(phone_number=PHONE, otp="123456", platform="android"),
            request,
        )


def test_locked_user_can_recover_with_otp_immediately(api: FastAPI) -> None:
    """AC-02.4: recovery OTP bypasses the PIN lock and resets its counters."""
    request, auth = register(api)
    user = authenticated_user(api, auth.access_token)
    set_pin(PINPayload(pin="2580"), request, user)

    for _ in range(5):
        with suppress(PINError):
            verify_pin(PINPayload(pin="1357"), request, user)

    sent = request_pin_recovery(PINRecoveryRequest(phone_number=PHONE), request)
    recovered = verify_pin_recovery(
        OTPVerifyRequest(phone_number=PHONE, otp="123456", platform="android"),
        request,
    )

    assert sent.model_dump() == {"message": "OTP sent"}
    assert recovered.is_new_user is False
    with api.state.session_factory() as session:
        api.state.pin_service.verify_pin(session, user.id, "2580")
