from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.db import SessionFactory
from app.payments.schemas import (
    PackageStatusResponse,
    PurchaseRequest,
    PurchaseResponse,
    WebhookResponse,
)
from app.payments.service import PaymentService
from app.retirement import (
    ARRIVAL_GEOFENCE,
    RETIRED_RESPONSES,
    RetiredFeatureError,
)

router = APIRouter(tags=["payments"])


@router.post("/packages/purchase", response_model=PurchaseResponse)
async def purchase(
    payload: PurchaseRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> PurchaseResponse:
    factory = cast(SessionFactory, request.app.state.session_factory)
    service = cast(PaymentService, request.app.state.payment_service)
    with factory() as session:
        result = service.initialize(
            session, user, payload.pricing_tier_id, payload.group_size
        )
    return PurchaseResponse(
        package_id=result.package_id,
        processor=result.checkout.processor,
        processor_reference=result.checkout.processor_reference,
        checkout_url=result.checkout.checkout_url,
    )


@router.get("/packages/{package_id}/status", response_model=PackageStatusResponse)
async def package_status(
    package_id: UUID,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> PackageStatusResponse:
    factory = cast(SessionFactory, request.app.state.session_factory)
    service = cast(PaymentService, request.app.state.payment_service)
    with factory() as session:
        package = service.package_status(session, user, package_id)
        return PackageStatusResponse(
            status=package.status.value,
            data_gb_total=package.data_gb_total,
            data_gb_remaining=float(package.data_gb_remaining),
            pstn_minutes_total=package.pstn_minutes_total,
            pstn_minutes_remaining=float(package.pstn_minutes_remaining),
        )


# Arrival geofencing retires with the Hajj framing (US-30, chunk 04). The
# `destination_geofences` table and its rows are retained; only the behavior is
# withdrawn.


@router.get(
    "/packages/{package_id}/geofence",
    status_code=410,
    responses=RETIRED_RESPONSES,
)
async def package_geofence(package_id: UUID) -> None:
    del package_id
    raise RetiredFeatureError(ARRIVAL_GEOFENCE)


@router.post("/webhooks/{processor}", response_model=WebhookResponse)
async def webhook(processor: str, request: Request) -> WebhookResponse:
    factory = cast(SessionFactory, request.app.state.session_factory)
    service = cast(PaymentService, request.app.state.payment_service)
    body = await request.body()
    headers = {key.lower(): value for key, value in request.headers.items()}
    with factory() as session:
        processed = service.process_webhook(session, processor, body, headers)
    return WebhookResponse(processed=processed)
