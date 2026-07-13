from datetime import datetime, timezone
from typing import cast

from fastapi import APIRouter, Request

from app.auth.schemas import (
    AuthResponse,
    MessageResponse,
    OTPRequest,
    OTPVerifyRequest,
    RefreshRequest,
    TokenResponse,
)
from app.auth.tokens import InvalidRefreshTokenError
from app.otp.service import OTPError, OTPService

router = APIRouter(prefix="/auth", tags=["authentication"])


def _service(request: Request) -> OTPService:
    return cast(OTPService, request.app.state.otp_service)


@router.post("/otp/request", response_model=MessageResponse)
def request_otp(payload: OTPRequest, request: Request) -> MessageResponse:
    with request.app.state.session_factory() as session:
        _service(request).request(session, payload.phone_number)
    return MessageResponse(message="OTP sent")


@router.post("/otp/verify", response_model=AuthResponse)
def verify_otp(payload: OTPVerifyRequest, request: Request) -> AuthResponse:
    with request.app.state.session_factory() as session:
        result = _service(request).verify(
            session, payload.phone_number, payload.otp, payload.platform
        )
    return AuthResponse.model_validate(result, from_attributes=True)


@router.post("/token/refresh", response_model=TokenResponse)
def refresh_token(payload: RefreshRequest, request: Request) -> TokenResponse:
    with request.app.state.session_factory() as session:
        try:
            pair = _service(request).tokens.rotate(
                session, payload.refresh_token, datetime.now(timezone.utc)
            )
        except InvalidRefreshTokenError as exc:
            raise OTPError("invalid_refresh_token") from exc
    return TokenResponse(
        access_token=pair.access_token, refresh_token=pair.refresh_token
    )
