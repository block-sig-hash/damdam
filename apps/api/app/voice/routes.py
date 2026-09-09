from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.db import SessionFactory
from app.retirement import (
    APP_VOICE,
    RETIRED_RESPONSES,
    VERIFIED_CLI,
    RetiredFeatureError,
)
from app.voice.nigerian_numbers import normalize_nigerian_number
from app.voice.schemas import (
    CallHistoryResponse,
    CallResponse,
    VoiceEligibilityResponse,
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


# App calling and verified caller ID retire here (US-30, chunk 04D).
#
# WebRTC/SIP credentials are not the launch calling mechanism -- the native
# dialer on the carrier eSIM is -- and external verified caller ID is deferred
# under D2 with a carrier-assigned number as the outbound identity. The
# `voice_credentials`, `verified_caller_identities` and `caller_id_consents`
# tables and their rows are retained; only the behavior is withdrawn.


@router.post("/voice/token", status_code=410, responses=RETIRED_RESPONSES)
async def token() -> None:
    raise RetiredFeatureError(APP_VOICE)


@router.post("/voice/cli/verify", status_code=410, responses=RETIRED_RESPONSES)
async def start_cli_verification() -> None:
    raise RetiredFeatureError(VERIFIED_CLI)


@router.post(
    "/voice/cli/{identity_id}/confirm",
    status_code=410,
    responses=RETIRED_RESPONSES,
)
async def confirm_cli_verification(identity_id: UUID) -> None:
    del identity_id
    raise RetiredFeatureError(VERIFIED_CLI)


@router.post(
    "/voice/cli/{identity_id}/consent",
    status_code=410,
    responses=RETIRED_RESPONSES,
)
async def capture_cli_consent(identity_id: UUID) -> None:
    del identity_id
    raise RetiredFeatureError(VERIFIED_CLI)


@router.post("/voice/cli/revoke", status_code=410, responses=RETIRED_RESPONSES)
async def revoke_cli() -> None:
    raise RetiredFeatureError(VERIFIED_CLI)


@router.post("/voice/cli/lost-sim", status_code=410, responses=RETIRED_RESPONSES)
async def report_lost_sim() -> None:
    raise RetiredFeatureError(VERIFIED_CLI)


@router.get("/voice/cli/status", status_code=410, responses=RETIRED_RESPONSES)
async def cli_status() -> None:
    raise RetiredFeatureError(VERIFIED_CLI)


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
