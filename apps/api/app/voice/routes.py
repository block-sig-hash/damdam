from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.db import SessionFactory
from app.voice.caller_identity_service import CallerIdentityService
from app.voice.models import CallerIdRevocationReason
from app.voice.nigerian_numbers import normalize_nigerian_number
from app.voice.schemas import (
    CallHistoryResponse,
    CallResponse,
    CliConsentRequest,
    CliVerificationConfirmRequest,
    CliVerificationStartRequest,
    VerifiedCallerIdentityResponse,
    VoiceEligibilityResponse,
    VoiceTokenRequest,
    VoiceTokenResponse,
    WebhookResponse,
)
from app.voice.service import VoiceService

router = APIRouter(tags=["voice"])


@router.get("/voice/eligibility", response_model=VoiceEligibilityResponse)
async def eligibility(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    phone_number: str = Query(),
) -> VoiceEligibilityResponse:
    number = normalize_nigerian_number(phone_number)
    factory = cast(SessionFactory, request.app.state.session_factory)
    service = cast(VoiceService, request.app.state.voice_service)
    with factory() as session:
        return VoiceEligibilityResponse(**service.eligibility(session, user, number))


@router.post("/voice/token", response_model=VoiceTokenResponse)
async def token(
    payload: VoiceTokenRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> VoiceTokenResponse:
    factory = cast(SessionFactory, request.app.state.session_factory)
    service = cast(VoiceService, request.app.state.voice_service)
    with factory() as session:
        access, credential, result = service.token(
            session, user, payload.to_number, payload.idempotency_key
        )
        return VoiceTokenResponse(
            token=access.token,
            sip_username=credential.sip_username,
            expires_at=access.expires_at,
            call_type=result["call_type"],
            destination=str(result["destination"]),
        )


@router.post(
    "/voice/cli/verify", response_model=VerifiedCallerIdentityResponse, status_code=201
)
async def start_cli_verification(
    payload: CliVerificationStartRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> VerifiedCallerIdentityResponse:
    factory = cast(SessionFactory, request.app.state.session_factory)
    service = cast(CallerIdentityService, request.app.state.caller_identity_service)
    with factory() as session:
        identity = service.start_verification(session, user, payload.phone_number)
        return VerifiedCallerIdentityResponse.model_validate(identity)


@router.post(
    "/voice/cli/{identity_id}/confirm", response_model=VerifiedCallerIdentityResponse
)
async def confirm_cli_verification(
    identity_id: UUID,
    payload: CliVerificationConfirmRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> VerifiedCallerIdentityResponse:
    factory = cast(SessionFactory, request.app.state.session_factory)
    service = cast(CallerIdentityService, request.app.state.caller_identity_service)
    with factory() as session:
        identity = service.confirm_verification(
            session, user, identity_id, payload.code
        )
        return VerifiedCallerIdentityResponse.model_validate(identity)


@router.post(
    "/voice/cli/{identity_id}/consent", response_model=VerifiedCallerIdentityResponse
)
async def capture_cli_consent(
    identity_id: UUID,
    payload: CliConsentRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> VerifiedCallerIdentityResponse:
    factory = cast(SessionFactory, request.app.state.session_factory)
    service = cast(CallerIdentityService, request.app.state.caller_identity_service)
    ip_address = request.client.host if request.client else None
    with factory() as session:
        identity = service.capture_consent(
            session,
            user,
            identity_id,
            payload.consent_version,
            ip_address,
            payload.device_session_id,
        )
        return VerifiedCallerIdentityResponse.model_validate(identity)


@router.post("/voice/cli/revoke", status_code=204)
async def revoke_cli(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    factory = cast(SessionFactory, request.app.state.session_factory)
    service = cast(CallerIdentityService, request.app.state.caller_identity_service)
    with factory() as session:
        service.revoke(session, user, CallerIdRevocationReason.USER_REVOKED)


@router.post("/voice/cli/lost-sim", status_code=204)
async def report_lost_sim(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    factory = cast(SessionFactory, request.app.state.session_factory)
    service = cast(CallerIdentityService, request.app.state.caller_identity_service)
    with factory() as session:
        service.revoke(session, user, CallerIdRevocationReason.LOST_SIM)


@router.get("/voice/cli/status", response_model=VerifiedCallerIdentityResponse | None)
async def cli_status(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> VerifiedCallerIdentityResponse | None:
    factory = cast(SessionFactory, request.app.state.session_factory)
    service = cast(CallerIdentityService, request.app.state.caller_identity_service)
    with factory() as session:
        identity = service.status(session, user)
        return (
            VerifiedCallerIdentityResponse.model_validate(identity)
            if identity is not None
            else None
        )


@router.post("/webhooks/telnyx/call-events", response_model=WebhookResponse)
async def webhook(request: Request) -> WebhookResponse:
    body = await request.body()
    headers = {key.lower(): value for key, value in request.headers.items()}
    factory = cast(SessionFactory, request.app.state.session_factory)
    service = cast(VoiceService, request.app.state.voice_service)
    with factory() as session:
        return WebhookResponse(
            processed=service.process_webhook(session, body, headers)
        )


@router.get("/me/calls", response_model=CallHistoryResponse)
async def history(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=20, ge=1, le=20),
) -> CallHistoryResponse:
    factory = cast(SessionFactory, request.app.state.session_factory)
    service = cast(VoiceService, request.app.state.voice_service)
    with factory() as session:
        calls = service.history(session, user, limit)
        return CallHistoryResponse(
            calls=[CallResponse.model_validate(call) for call in calls]
        )
