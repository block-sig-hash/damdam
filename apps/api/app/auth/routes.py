from datetime import datetime, timezone
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from app.auth.dependencies import get_current_user
from app.auth.hto import HTOService
from app.auth.models import User
from app.auth.pin import PINService
from app.auth.schemas import (
    AuthResponse,
    HTOLoginRequest,
    HTOLoginResponse,
    HTOOperatorResponse,
    HTORegistrationRequest,
    HTOVerifyEmailRequest,
    MessageResponse,
    OTPRequest,
    OTPVerifyRequest,
    PINPayload,
    PINRecoveryRequest,
    PINVerifyResponse,
    RefreshRequest,
    TokenResponse,
    UserResponse,
)
from app.auth.tokens import InvalidRefreshTokenError
from app.otp.service import AuthResult, OTPError, OTPService
from app.voice.models import VerifiedCallerIdentity, VerifiedCallerIdentityStatus

router = APIRouter(prefix="/auth", tags=["authentication"])


def _service(request: Request) -> OTPService:
    return cast(OTPService, request.app.state.otp_service)


def _pin_service(request: Request) -> PINService:
    return cast(PINService, request.app.state.pin_service)


def _hto_service(request: Request) -> HTOService:
    return cast(HTOService, request.app.state.hto_service)


@router.post("/otp/request", response_model=MessageResponse)
def request_otp(payload: OTPRequest, request: Request) -> MessageResponse:
    with request.app.state.session_factory() as session:
        _service(request).request(session, payload.phone_number)
    return MessageResponse(message="OTP sent")


def _auth_response(session: Session, result: AuthResult) -> AuthResponse:
    # `User.verified_cli` is a retired, legacy flag (data-model.md §6.40) --
    # the login OTP no longer sets it. `active` VerifiedCallerIdentity
    # status is the current source of truth for CLI verification.
    has_active_cli = (
        session.exec(
            select(VerifiedCallerIdentity).where(
                VerifiedCallerIdentity.user_id == result.user.id,
                VerifiedCallerIdentity.status == VerifiedCallerIdentityStatus.ACTIVE,
            )
        ).first()
        is not None
    )
    user = UserResponse.model_validate(result.user).model_copy(
        update={"verified_cli": has_active_cli}
    )
    return AuthResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        user=user,
        is_new_user=result.is_new_user,
    )


@router.post("/otp/verify", response_model=AuthResponse)
def verify_otp(payload: OTPVerifyRequest, request: Request) -> AuthResponse:
    with request.app.state.session_factory() as session:
        result = _service(request).verify(
            session, payload.phone_number, payload.otp, payload.platform
        )
        return _auth_response(session, result)


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
        return _auth_response(session, result)


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


@router.post("/hto/register", response_model=MessageResponse, status_code=201)
def register_hto(
    payload: HTORegistrationRequest, request: Request
) -> MessageResponse:
    with request.app.state.session_factory() as session:
        _hto_service(request).register(session, payload)
    return MessageResponse(message="Verification email sent")


@router.post("/hto/verify-email", response_model=MessageResponse)
def verify_hto_email(
    payload: HTOVerifyEmailRequest, request: Request
) -> MessageResponse:
    with request.app.state.session_factory() as session:
        _hto_service(request).verify_email(session, payload.token)
    return MessageResponse(message="Email verified, pending admin approval")


@router.post("/hto/login", response_model=HTOLoginResponse)
def login_hto(payload: HTOLoginRequest, request: Request) -> HTOLoginResponse:
    with request.app.state.session_factory() as session:
        pair, organization = _hto_service(request).login(
            session, payload.email, payload.password
        )
        response = HTOLoginResponse(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            operator=HTOOperatorResponse.model_validate(organization),
        )
    return response
