from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile, status

from app.auth.dependencies import get_current_organization
from app.auth.models import Organization
from app.manifests.orders import ManifestOrderService
from app.manifests.schemas import (
    FamilyGroupRequest,
    FamilyGroupResponse,
    ManifestConfirmResponse,
    ManifestCreateRequest,
    ManifestCreateResponse,
    ManifestListResponse,
    ManifestOrderDetailResponse,
    ManifestOrderListResponse,
    ManifestOrderRequest,
    ManifestOrderResponse,
    ManifestSummary,
    ManifestUploadResponse,
    PricingTierListResponse,
    UnorderedPilgrimListResponse,
)
from app.manifests.service import ManifestService

router = APIRouter(prefix="/hto/manifests", tags=["HTO manifests"])
pricing_router = APIRouter(prefix="/hto/pricing-tiers", tags=["HTO manifests"])


def _service(request: Request) -> ManifestService:
    return cast(ManifestService, request.app.state.manifest_service)


def _order_service(request: Request) -> ManifestOrderService:
    return cast(ManifestOrderService, request.app.state.manifest_order_service)


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


@pricing_router.get("", response_model=PricingTierListResponse)
def list_pricing_tiers(
    request: Request,
    organization: Annotated[Organization, Depends(get_current_organization)],
) -> PricingTierListResponse:
    del organization
    with request.app.state.session_factory() as session:
        tiers = _order_service(request).list_pricing(session)
    return PricingTierListResponse(tiers=tiers)


@router.get(
    "/{manifest_id}/unordered-pilgrims",
    response_model=UnorderedPilgrimListResponse,
)
def list_unordered_pilgrims(
    manifest_id: UUID,
    request: Request,
    organization: Annotated[Organization, Depends(get_current_organization)],
) -> UnorderedPilgrimListResponse:
    with request.app.state.session_factory() as session:
        pilgrims = _order_service(request).list_unordered(
            session, organization.id, manifest_id
        )
    return UnorderedPilgrimListResponse(pilgrims=pilgrims)


@router.post("/{manifest_id}/group", response_model=FamilyGroupResponse)
def create_family_group(
    manifest_id: UUID,
    payload: FamilyGroupRequest,
    request: Request,
    organization: Annotated[Organization, Depends(get_current_organization)],
) -> FamilyGroupResponse:
    with request.app.state.session_factory() as session:
        group_id = _order_service(request).create_group(
            session,
            organization.id,
            manifest_id,
            payload.manifest_pilgrim_ids,
            payload.group_size,
        )
    return FamilyGroupResponse(family_group_id=group_id)


@router.put(
    "/{manifest_id}/group/{group_id}", response_model=FamilyGroupResponse
)
def update_family_group(
    manifest_id: UUID,
    group_id: UUID,
    payload: FamilyGroupRequest,
    request: Request,
    organization: Annotated[Organization, Depends(get_current_organization)],
) -> FamilyGroupResponse:
    with request.app.state.session_factory() as session:
        updated_id = _order_service(request).update_group(
            session,
            organization.id,
            manifest_id,
            group_id,
            payload.manifest_pilgrim_ids,
            payload.group_size,
        )
    return FamilyGroupResponse(family_group_id=updated_id)


@router.delete("/{manifest_id}/group/{group_id}", status_code=204)
def delete_family_group(
    manifest_id: UUID,
    group_id: UUID,
    request: Request,
    organization: Annotated[Organization, Depends(get_current_organization)],
) -> Response:
    with request.app.state.session_factory() as session:
        _order_service(request).delete_group(
            session, organization.id, manifest_id, group_id
        )
    return Response(status_code=204)


@router.post("/{manifest_id}/order", response_model=ManifestOrderResponse)
def place_manifest_order(
    manifest_id: UUID,
    payload: ManifestOrderRequest,
    request: Request,
    organization: Annotated[Organization, Depends(get_current_organization)],
) -> ManifestOrderResponse:
    with request.app.state.session_factory() as session:
        return _order_service(request).place_order(
            session,
            organization.id,
            manifest_id,
            payload.pricing_tier_id,
            payload.manifest_pilgrim_ids,
        )


@router.get("/{manifest_id}/orders", response_model=ManifestOrderListResponse)
def list_manifest_orders(
    manifest_id: UUID,
    request: Request,
    organization: Annotated[Organization, Depends(get_current_organization)],
) -> ManifestOrderListResponse:
    with request.app.state.session_factory() as session:
        orders = _order_service(request).list_orders(
            session, organization.id, manifest_id
        )
    return ManifestOrderListResponse(orders=orders)


@router.get(
    "/{manifest_id}/order/{order_id}", response_model=ManifestOrderDetailResponse
)
def get_manifest_order(
    manifest_id: UUID,
    order_id: UUID,
    request: Request,
    organization: Annotated[Organization, Depends(get_current_organization)],
) -> ManifestOrderDetailResponse:
    with request.app.state.session_factory() as session:
        return _order_service(request).get_order(
            session, organization.id, manifest_id, order_id
        )


@router.get("/{manifest_id}/order/{order_id}/invoice")
def download_manifest_invoice(
    manifest_id: UUID,
    order_id: UUID,
    request: Request,
    organization: Annotated[Organization, Depends(get_current_organization)],
) -> Response:
    with request.app.state.session_factory() as session:
        pdf = _order_service(request).get_invoice(
            session, organization.id, manifest_id, order_id
        )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="damdam-invoice-{order_id}.pdf"'
        },
    )
