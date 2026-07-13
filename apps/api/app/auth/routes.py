from datetime import datetime, timezone
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.auth.pin import PINService
from app.auth.schemas import (
    AuthResponse,
    MessageResponse,
    OTPRequest,
    OTPVerifyRequest,
    PINPayload,
    PINRecoveryRequest,
    PINVerifyResponse,
    RefreshRequest,
    TokenResponse,
)
from app.auth.tokens import InvalidRefreshTokenError
from app.otp.service import OTPError, OTPService

router = APIRouter(prefix="/auth", tags=["authentication"])


def _service(request: Request) -> OTPService:
    return cast(OTPService, request.app.state.otp_service)


def _pin_service(request: Request) -> PINService:
    return cast(PINService, request.app.state.pin_service)


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


@router.post("/pin/set", response_model=MessageResponse)
def set_pin(
    payload: PINPayload,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> MessageResponse:
    with request.app.state.session_factory() as session:
        _pin_service(request).set_pin(session, user.id, payload.pin)
    return MessageResponse(message="PIN set")


@router.post("/pin/verify", response_model=PINVerifyResponse)
def verify_pin(
    payload: PINPayload,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> PINVerifyResponse:
    with request.app.state.session_factory() as session:
        _pin_service(request).verify_pin(session, user.id, payload.pin)
    return PINVerifyResponse()


@router.post("/pin/recovery/request", response_model=MessageResponse)
def request_pin_recovery(
    payload: PINRecoveryRequest, request: Request
) -> MessageResponse:
    with request.app.state.session_factory() as session:
        _service(request).request(session, payload.phone_number, allow_existing=True)
    return MessageResponse(message="OTP sent")


@router.post("/pin/recovery/verify", response_model=AuthResponse)
def verify_pin_recovery(payload: OTPVerifyRequest, request: Request) -> AuthResponse:
    with request.app.state.session_factory() as session:
        result = _service(request).verify(
            session,
            payload.phone_number,
            payload.otp,
            payload.platform,
            purpose="recovery",
        )
    with request.app.state.session_factory() as session:
        _pin_service(request).clear_lock_after_otp(session, result.user.id)
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
