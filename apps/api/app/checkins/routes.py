import hashlib
import hmac
import json
from datetime import timezone
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.checkins.schemas import (
    CheckInCreate,
    CheckInCreateResponse,
    CheckInHistoryResponse,
    CheckInResponse,
    MetaWebhookResponse,
)
from app.checkins.service import (
    CheckInError,
    CheckInNotificationService,
    CheckInService,
)
from app.config import Settings
from app.db import SessionFactory

router = APIRouter(tags=["check-ins"])


@router.post("/checkins", response_model=CheckInCreateResponse)
async def create_checkin(
    payload: CheckInCreate,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> CheckInCreateResponse:
    factory = cast(SessionFactory, request.app.state.session_factory)
    service = cast(CheckInService, request.app.state.checkin_service)
    with factory() as session:
        checkin = service.create(session, user, payload)
        received_at = checkin.received_at
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)
        return CheckInCreateResponse(id=checkin.id, received_at=received_at)


@router.get("/me/checkins", response_model=CheckInHistoryResponse)
async def history(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=10, ge=1, le=10),
) -> CheckInHistoryResponse:
    factory = cast(SessionFactory, request.app.state.session_factory)
    service = cast(CheckInService, request.app.state.checkin_service)
    with factory() as session:
        rows = service.history(session, user, limit)
        return CheckInHistoryResponse(
            checkins=[CheckInResponse.model_validate(row) for row in rows]
        )


@router.get("/webhooks/meta/whatsapp", response_class=PlainTextResponse)
def verify_meta_webhook(
    request: Request,
    mode: str = Query(alias="hub.mode"),
    token: str = Query(alias="hub.verify_token"),
    challenge: str = Query(alias="hub.challenge"),
) -> str:
    settings = cast(Settings, request.app.state.settings)
    if (
        mode != "subscribe"
        or not settings.whatsapp_webhook_verify_token
        or not hmac.compare_digest(token, settings.whatsapp_webhook_verify_token)
    ):
        raise CheckInError("invalid_webhook_signature")
    return challenge


@router.post("/webhooks/meta/whatsapp", response_model=MetaWebhookResponse)
async def meta_webhook(request: Request) -> MetaWebhookResponse:
    body = await request.body()
    settings = cast(Settings, request.app.state.settings)
    provided = request.headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(
        settings.whatsapp_app_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    if (
        not settings.whatsapp_app_secret
        or not provided
        or not hmac.compare_digest(provided, expected)
    ):
        raise CheckInError("invalid_webhook_signature")
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise CheckInError("invalid_webhook_payload") from exc
    factory = cast(SessionFactory, request.app.state.session_factory)
    service = cast(
        CheckInNotificationService, request.app.state.checkin_notification_service
    )
    with factory() as session:
        processed = service.process_meta_statuses(session, payload)
        return MetaWebhookResponse(processed=processed)
