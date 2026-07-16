from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.db import SessionFactory
from app.voice.schemas import (
    CallHistoryResponse,
    CallResponse,
    VoiceEligibilityResponse,
    VoiceTokenRequest,
    VoiceTokenResponse,
    WebhookResponse,
    normalize_dialed_number,
)
from app.voice.service import VoiceService

router = APIRouter(tags=["voice"])


@router.get("/voice/eligibility", response_model=VoiceEligibilityResponse)
async def eligibility(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    phone_number: str = Query(),
) -> VoiceEligibilityResponse:
    number = normalize_dialed_number(phone_number)
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
        access, credential, result = service.token(session, user, payload.to_number)
        return VoiceTokenResponse(
            token=access.token,
            sip_username=credential.sip_username,
            expires_at=access.expires_at,
            call_type=result["call_type"],
            destination=str(result["destination"]),
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
