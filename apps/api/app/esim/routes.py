from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.auth.dependencies import get_current_organization, get_current_user
from app.auth.models import Organization, User
from app.esim.models import EsimProfile
from app.esim.schemas import (
    DeviceCompatibilityCreate,
    DeviceCompatibilityResponse,
    EsimDownloadResponse,
    EsimIssueResponse,
    EsimProfileResponse,
    HtoPilgrimListResponse,
)
from app.esim.service import (
    DeviceCompatibilityService,
    EsimProfileService,
    HtoPilgrimService,
)

router = APIRouter(tags=["esim"])


def _profile_response(profile: EsimProfile) -> EsimProfileResponse:
    return EsimProfileResponse(
        esim_profile_id=profile.id,
        iccid=profile.iccid,
        qr_code_url=profile.qr_code_url,
        status=profile.status.value,
        downloaded_at=profile.downloaded_at,
        activated_at=profile.activated_at,
    )


@router.post("/packages/{package_id}/esim/issue", response_model=EsimIssueResponse)
def issue_esim(
    package_id: UUID,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> EsimIssueResponse:
    service = cast(EsimProfileService, request.app.state.esim_profile_service)
    with request.app.state.session_factory() as session:
        profile = service.issue(session, user, package_id)
        return EsimIssueResponse(
            esim_profile_id=profile.id,
            iccid=profile.iccid,
            activation_code_lpa=profile.activation_code_lpa,
            qr_code_url=profile.qr_code_url,
            status=profile.status.value,
        )


@router.get("/packages/{package_id}/esim", response_model=EsimProfileResponse)
def get_esim(
    package_id: UUID,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> EsimProfileResponse:
    service = cast(EsimProfileService, request.app.state.esim_profile_service)
    with request.app.state.session_factory() as session:
        return _profile_response(service.get(session, user, package_id))


@router.post(
    "/packages/{package_id}/esim/mark-downloaded",
    response_model=EsimDownloadResponse,
)
def mark_esim_downloaded(
    package_id: UUID,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> EsimDownloadResponse:
    service = cast(EsimProfileService, request.app.state.esim_profile_service)
    with request.app.state.session_factory() as session:
        profile = service.mark_downloaded(session, user, package_id)
        return EsimDownloadResponse(status=profile.status.value)


@router.post(
    "/packages/{package_id}/esim/mark-activated",
    response_model=EsimDownloadResponse,
)
def mark_esim_activated(
    package_id: UUID,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> EsimDownloadResponse:
    service = cast(EsimProfileService, request.app.state.esim_profile_service)
    with request.app.state.session_factory() as session:
        profile = service.mark_activated(session, user, package_id)
        return EsimDownloadResponse(status=profile.status.value)


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
