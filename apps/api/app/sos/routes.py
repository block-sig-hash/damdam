from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.auth.dependencies import get_current_organization, get_current_user
from app.auth.models import Organization, User
from app.db import SessionFactory
from app.sos.models import SOSStatus
from app.sos.notifications import PushSubscriptionService
from app.sos.schemas import (
    HtoSOSAlertsResponse,
    PushSubscriptionCreate,
    SOSCreate,
    SOSCreateResponse,
    SOSStatusResponse,
)
from app.sos.service import SOSService

router = APIRouter(tags=["SOS"])


def _service(request: Request) -> SOSService:
    return cast(SOSService, request.app.state.sos_service)


def _push_subscriptions(request: Request) -> PushSubscriptionService:
    return cast(
        PushSubscriptionService, request.app.state.push_subscription_service
    )


@router.post("/sos", response_model=SOSCreateResponse)
async def create_sos(
    payload: SOSCreate,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> SOSCreateResponse:
    with cast(SessionFactory, request.app.state.session_factory)() as session:
        alert = _service(request).create(session, user, payload)
        return SOSCreateResponse(id=alert.id, status=alert.status)


@router.post("/sos/{alert_id}/cancel", response_model=SOSStatusResponse)
async def cancel_sos(
    alert_id: UUID, request: Request, user: Annotated[User, Depends(get_current_user)]
) -> SOSStatusResponse:
    with cast(SessionFactory, request.app.state.session_factory)() as session:
        return SOSStatusResponse(
            status=_service(request).cancel(session, user, alert_id).status
        )


@router.get("/hto/sos-alerts", response_model=HtoSOSAlertsResponse)
async def list_sos(
    request: Request,
    organization: Annotated[Organization, Depends(get_current_organization)],
    status: Annotated[SOSStatus | None, Query()] = SOSStatus.ACTIVE,
) -> HtoSOSAlertsResponse:
    with cast(SessionFactory, request.app.state.session_factory)() as session:
        return HtoSOSAlertsResponse(
            alerts=_service(request).list_for_hto(session, organization, status)
        )


@router.post("/hto/sos-alerts/{alert_id}/resolve", response_model=SOSStatusResponse)
async def resolve_sos(
    alert_id: UUID,
    request: Request,
    organization: Annotated[Organization, Depends(get_current_organization)],
) -> SOSStatusResponse:
    with cast(SessionFactory, request.app.state.session_factory)() as session:
        return SOSStatusResponse(
            status=_service(request).resolve(session, organization, alert_id).status
        )


@router.post("/hto/push-subscriptions", status_code=204)
async def create_push_subscription(
    payload: PushSubscriptionCreate,
    request: Request,
    organization: Annotated[Organization, Depends(get_current_organization)],
) -> None:
    _push_subscriptions(request).subscribe(organization.id, payload.fcm_token)
