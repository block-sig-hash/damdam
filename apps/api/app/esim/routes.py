from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.auth.dependencies import get_current_organization, get_current_user
from app.auth.models import Organization, User
from app.esim.schemas import (
    DeviceCompatibilityCreate,
    DeviceCompatibilityResponse,
    HtoPilgrimListResponse,
)
from app.esim.service import DeviceCompatibilityService, HtoPilgrimService

router = APIRouter(tags=["esim"])


@router.post(
    "/me/device-compatibility",
    response_model=DeviceCompatibilityResponse,
    status_code=201,
)
def log_device_compatibility(
    payload: DeviceCompatibilityCreate,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> DeviceCompatibilityResponse:
    service = cast(
        DeviceCompatibilityService, request.app.state.device_compatibility_service
    )
    with request.app.state.session_factory() as session:
        service.log_check(session, user, payload)
    return DeviceCompatibilityResponse()


@router.get("/hto/pilgrims", response_model=HtoPilgrimListResponse)
def list_hto_pilgrims(
    request: Request,
    organization: Annotated[Organization, Depends(get_current_organization)],
    manifest_id: Annotated[UUID | None, Query()] = None,
) -> HtoPilgrimListResponse:
    service = cast(HtoPilgrimService, request.app.state.hto_pilgrim_service)
    with request.app.state.session_factory() as session:
        pilgrims = service.list_pilgrims(session, organization, manifest_id)
    return HtoPilgrimListResponse(pilgrims=pilgrims)
