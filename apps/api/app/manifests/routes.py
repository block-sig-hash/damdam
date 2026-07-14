from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile, status

from app.auth.dependencies import get_current_organization
from app.auth.models import Organization
from app.manifests.schemas import (
    ManifestConfirmResponse,
    ManifestCreateRequest,
    ManifestCreateResponse,
    ManifestListResponse,
    ManifestSummary,
    ManifestUploadResponse,
)
from app.manifests.service import ManifestService

router = APIRouter(prefix="/hto/manifests", tags=["HTO manifests"])


def _service(request: Request) -> ManifestService:
    return cast(ManifestService, request.app.state.manifest_service)


@router.post(
    "", response_model=ManifestCreateResponse, status_code=status.HTTP_201_CREATED
)
def create_manifest(
    payload: ManifestCreateRequest,
    request: Request,
    organization: Annotated[Organization, Depends(get_current_organization)],
) -> ManifestCreateResponse:
    with request.app.state.session_factory() as session:
        manifest = _service(request).create(session, organization.id, payload.name)
    return ManifestCreateResponse(manifest_id=manifest.id)


@router.post("/{manifest_id}/upload", response_model=ManifestUploadResponse)
async def upload_manifest(
    manifest_id: UUID,
    request: Request,
    organization: Annotated[Organization, Depends(get_current_organization)],
    file: Annotated[UploadFile, File()],
) -> ManifestUploadResponse:
    contents = await file.read()
    with request.app.state.session_factory() as session:
        return _service(request).upload(
            session, organization.id, manifest_id, file.filename, contents
        )


@router.post("/{manifest_id}/confirm", response_model=ManifestConfirmResponse)
def confirm_manifest(
    manifest_id: UUID,
    request: Request,
    organization: Annotated[Organization, Depends(get_current_organization)],
) -> ManifestConfirmResponse:
    with request.app.state.session_factory() as session:
        manifest = _service(request).confirm(session, organization.id, manifest_id)
    return ManifestConfirmResponse(pilgrim_count=manifest.valid_rows)


@router.get("", response_model=ManifestListResponse)
def list_manifests(
    request: Request,
    organization: Annotated[Organization, Depends(get_current_organization)],
) -> ManifestListResponse:
    with request.app.state.session_factory() as session:
        manifests = _service(request).list_manifests(session, organization.id)
    return ManifestListResponse(
        manifests=[
            ManifestSummary.model_validate(item, from_attributes=True)
            for item in manifests
        ]
    )
