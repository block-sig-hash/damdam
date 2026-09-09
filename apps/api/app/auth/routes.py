from collections.abc import Callable
from datetime import datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from app.auth.dependencies import get_current_user
from app.auth.hto import HTOService
from app.auth.models import Locale, User
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
from app.auth.tokens import InvalidRefreshTokenError, TokenService
from app.config import Settings
from app.i18n import translate
from app.identity.models import IdentifierKind
from app.identity.schemas import (
    EmailIdentifierRequest,
    IdentityMessageResponse,
    IdentityTokenRequest,
    RecoverySessionResponse,
)
from app.identity.service import IdentityError, IdentityService
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
        _service(request).request(session, payload.phone_number, locale=payload.locale)
    return MessageResponse(message=translate("otp_sent", payload.locale))


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
            session,
            payload.phone_number,
            payload.otp,
            payload.platform,
            payload.locale,
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
    return MessageResponse(message=translate("pin_set", user.locale))


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
        _service(request).request(
            session,
            payload.phone_number,
            allow_existing=True,
            locale=payload.locale,
        )
    return MessageResponse(message=translate("otp_sent", payload.locale))


@router.post("/pin/recovery/verify", response_model=AuthResponse)
def verify_pin_recovery(payload: OTPVerifyRequest, request: Request) -> AuthResponse:
    with request.app.state.session_factory() as session:
        result = _service(request).verify(
            session,
            payload.phone_number,
            payload.otp,
            payload.platform,
            payload.locale,
            purpose="recovery",
        )
    with request.app.state.session_factory() as session:
        _pin_service(request).clear_lock_after_otp(session, result.user.id)
        return _auth_response(session, result)


@router.post("/token/refresh", response_model=TokenResponse)
def refresh_token(payload: RefreshRequest, request: Request) -> TokenResponse:
    with request.app.state.session_factory() as session:
        try:
            # The application clock, not wall-clock: every other token path
            # (get_current_user, get_current_organization, decode_access)
            # already validates against `app.state.clock`. In production that
            # clock is `utc_now`, so production expiry is unchanged.
            pair = _service(request).tokens.rotate(
                session, payload.refresh_token, request.app.state.clock()
            )
        except InvalidRefreshTokenError as exc:
            raise OTPError("invalid_refresh_token") from exc
    return TokenResponse(
        access_token=pair.access_token, refresh_token=pair.refresh_token
    )


@router.post("/hto/register", response_model=MessageResponse, status_code=201)
def register_hto(payload: HTORegistrationRequest, request: Request) -> MessageResponse:
    with request.app.state.session_factory() as session:
        _hto_service(request).register(session, payload)
    return MessageResponse(message=translate("verification_email_sent", payload.locale))


@router.post("/hto/verify-email", response_model=MessageResponse)
def verify_hto_email(
    payload: HTOVerifyEmailRequest, request: Request
) -> MessageResponse:
    with request.app.state.session_factory() as session:
        organization = _hto_service(request).verify_email(session, payload.token)
    return MessageResponse(message=translate("email_verified", organization.locale))


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

# --- email identity and recovery (US-29) ------------------------------------
#
# Email is the launch account identity and primary recovery channel (founder
# decision, 2026-09-09). Recovery here deliberately requires no OTP and no SIM.
#
# Every response below is uniform: a caller cannot tell a registered address
# from an unregistered one, and throttling is applied per address *before* the
# lookup so the rate limit cannot answer the question either.


def _identity(request: Request) -> IdentityService:
    return cast(IdentityService, request.app.state.identity_service)


@router.post("/email/verify/request", response_model=IdentityMessageResponse)
def request_email_verification(
    payload: EmailIdentifierRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> IdentityMessageResponse:
    """Claim an email for the signed-in account and send proof-of-ownership."""
    with request.app.state.session_factory() as session:
        # The dependency establishes *who* is calling; the entity is loaded in
        # this session so the service works with a mapped instance.
        account = session.get(User, user.id)
        if account is None:  # pragma: no cover - a live token implies a row
            raise IdentityError("identity_token_invalid")
        _identity(request).start_identifier_verification(
            session, account, IdentifierKind.EMAIL, payload.email, payload.locale
        )
        session.commit()
    return IdentityMessageResponse(message=translate("identity_sent", payload.locale))


@router.post("/email/verify/confirm", response_model=IdentityMessageResponse)
def confirm_email_verification(
    payload: IdentityTokenRequest, request: Request
) -> IdentityMessageResponse:
    with request.app.state.session_factory() as session:
        _identity(request).confirm_identifier(session, payload.token)
        session.commit()
    return IdentityMessageResponse(message=translate("identity_verified", Locale.EN))


@router.post("/email/recovery/request", response_model=IdentityMessageResponse)
def request_email_recovery(
    payload: EmailIdentifierRequest, request: Request
) -> IdentityMessageResponse:
    with request.app.state.session_factory() as session:
        _identity(request).request_recovery(
            session, IdentifierKind.EMAIL, payload.email, payload.locale
        )
        session.commit()
    return IdentityMessageResponse(message=translate("identity_sent", payload.locale))


@router.post("/email/recovery/confirm", response_model=RecoverySessionResponse)
def confirm_email_recovery(
    payload: IdentityTokenRequest, request: Request
) -> RecoverySessionResponse:
    """Consume a recovery token, revoke prior sessions and issue a new one."""
    tokens = TokenService(cast(Settings, request.app.state.settings))
    clock = cast(Callable[[], datetime], request.app.state.clock)
    with request.app.state.session_factory() as session:
        user = _identity(request).complete_recovery(session, payload.token)
        pair = tokens.issue(session, user, clock())
        session.commit()
        return RecoverySessionResponse(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            user=UserResponse.model_validate(user),
        )
