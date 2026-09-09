from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, cast
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.auth.hto import HTOAuthError, HTOService
from app.auth.models import (
    AdminUser,
    HTOApprovalStatus,
    ManifestOrderStatus,
    Platform,
)
from app.auth.schemas import (
    HTOApprovalResponse,
    HTOOperatorListResponse,
    HTOOperatorResponse,
    HTORejectionRequest,
)
from app.esim.schemas import (
    DeviceCompatibilityLogEntry,
    DeviceCompatibilityLogListResponse,
)
from app.esim.service import DeviceCompatibilityService
from app.manifests.orders import ManifestOrderService
from app.manifests.schemas import (
    AdminManifestOrderListResponse,
    AdminPricingTierListResponse,
    AdminPricingTierResponse,
    PaymentConfirmationResponse,
    PricingTierUpdateRequest,
    PricingTierUpdateResponse,
)
from app.packages.service import PackageAdminService
from app.retirement import RETIRED_RESPONSES, SOS, RetiredFeatureError

router = APIRouter(prefix="/admin", tags=["admin"])
bearer = HTTPBearer(auto_error=False)


class PackageCancelResponse(BaseModel):
    id: UUID
    status: str


def _service(request: Request) -> HTOService:
    return cast(HTOService, request.app.state.hto_service)


def _order_service(request: Request) -> ManifestOrderService:
    return cast(ManifestOrderService, request.app.state.manifest_order_service)


def _package_admin_service(request: Request) -> PackageAdminService:
    return cast(PackageAdminService, request.app.state.package_admin_service)


def current_admin(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> AdminUser:
    if credentials is None:
        raise HTOAuthError("invalid_admin_token")
    try:
        claims = jwt.decode(
            credentials.credentials,
            request.app.state.settings.jwt_secret,
            algorithms=["HS256"],
            audience="admin",
            options={"verify_exp": False},
        )
        if claims.get("type") != "access":
            raise HTOAuthError("invalid_admin_token")
        expires_at = datetime.fromtimestamp(claims["exp"], timezone.utc)
        if expires_at <= _service(request).clock():
            raise HTOAuthError("invalid_admin_token")
        admin_id = UUID(claims["sub"])
    except HTOAuthError:
        raise
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise HTOAuthError("invalid_admin_token") from exc
    with request.app.state.session_factory() as session:
        admin = session.get(AdminUser, admin_id)
        if admin is None:
            raise HTOAuthError("invalid_admin_token")
        session.expunge(admin)
        return cast(AdminUser, admin)


# The operator SOS queue retires with the feature (US-30, chunk 04B). Retrying a
# failed notification was the one remaining way to put retired dispatch back on
# a queue, so it refuses before any authentication: there is nothing behind it
# to protect, and an operator should be told the queue is gone rather than that
# their credentials are wrong.


@router.get("/sos-notifications/failed", status_code=410, responses=RETIRED_RESPONSES)
def failed_sos_notifications() -> None:
    raise RetiredFeatureError(SOS)


@router.post(
    "/sos-notifications/retry-bulk",
    status_code=410,
    responses=RETIRED_RESPONSES,
)
def retry_sos_notifications_bulk() -> None:
    raise RetiredFeatureError(SOS)


@router.post(
    "/sos-notifications/{notification_id}/retry",
    status_code=410,
    responses=RETIRED_RESPONSES,
)
def retry_sos_notification(notification_id: UUID) -> None:
    del notification_id
    raise RetiredFeatureError(SOS)


def _device_compatibility_service(request: Request) -> DeviceCompatibilityService:
    return cast(
        DeviceCompatibilityService, request.app.state.device_compatibility_service
    )


@router.get(
    "/device-compatibility-log",
    response_model=DeviceCompatibilityLogListResponse,
)
def list_device_compatibility_log(
    request: Request,
    admin: Annotated[AdminUser, Depends(current_admin)],
    platform: Platform | None = None,
    esim_supported: bool | None = None,
) -> DeviceCompatibilityLogListResponse:
    del admin
    with request.app.state.session_factory() as session:
        entries = _device_compatibility_service(request).list_checks(
            session, platform, esim_supported
        )
        return DeviceCompatibilityLogListResponse(
            entries=[
                DeviceCompatibilityLogEntry(
                    id=entry.id,
                    device_model=entry.device_model,
                    platform=entry.platform,
                    os_version=entry.os_version,
                    esim_supported=entry.esim_supported,
                    checked_at=entry.checked_at,
                )
                for entry in entries
            ]
        )


@router.get("/hto-operators", response_model=HTOOperatorListResponse)
def list_hto_operators(
    request: Request,
    admin: Annotated[AdminUser, Depends(current_admin)],
    status: HTOApprovalStatus | None = None,
) -> HTOOperatorListResponse:
    del admin
    with request.app.state.session_factory() as session:
        organizations = _service(request).list_organizations(session, status)
    return HTOOperatorListResponse(
        operators=[HTOOperatorResponse.model_validate(item) for item in organizations]
    )


@router.post("/hto-operators/{operator_id}/approve", response_model=HTOApprovalResponse)
def approve_hto_operator(
    operator_id: UUID,
    request: Request,
    admin: Annotated[AdminUser, Depends(current_admin)],
) -> HTOApprovalResponse:
    with request.app.state.session_factory() as session:
        organization = _service(request).approve(session, operator_id, admin.id)
    return HTOApprovalResponse(approval_status=organization.approval_status)


@router.post("/hto-operators/{operator_id}/reject", response_model=HTOApprovalResponse)
def reject_hto_operator(
    operator_id: UUID,
    payload: HTORejectionRequest,
    request: Request,
    admin: Annotated[AdminUser, Depends(current_admin)],
) -> HTOApprovalResponse:
    with request.app.state.session_factory() as session:
        organization = _service(request).reject(
            session, operator_id, admin.id, payload.reason
        )
    return HTOApprovalResponse(approval_status=organization.approval_status)


@router.get("/manifest-orders", response_model=AdminManifestOrderListResponse)
def list_manifest_orders(
    request: Request,
    admin: Annotated[AdminUser, Depends(current_admin)],
    status: ManifestOrderStatus = ManifestOrderStatus.AWAITING_PAYMENT,
    search: str | None = None,
) -> AdminManifestOrderListResponse:
    del admin
    with request.app.state.session_factory() as session:
        orders = _order_service(request).list_admin_orders(session, status, search)
    return AdminManifestOrderListResponse(orders=orders)


@router.get("/manifest-orders/{order_id}/invoice")
def download_manifest_invoice(
    order_id: UUID,
    request: Request,
    admin: Annotated[AdminUser, Depends(current_admin)],
) -> Response:
    del admin
    with request.app.state.session_factory() as session:
        pdf = _order_service(request).get_admin_invoice(session, order_id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="damdam-invoice-{order_id}.pdf"'
        },
    )


@router.post(
    "/manifest-orders/{order_id}/confirm-payment",
    response_model=PaymentConfirmationResponse,
)
def confirm_manifest_order_payment(
    order_id: UUID,
    request: Request,
    admin: Annotated[AdminUser, Depends(current_admin)],
) -> PaymentConfirmationResponse:
    with request.app.state.session_factory() as session:
        order = _order_service(request).confirm_payment(session, order_id, admin)
    return PaymentConfirmationResponse(status=order.status)


@router.get("/pricing-tiers", response_model=AdminPricingTierListResponse)
def list_admin_pricing_tiers(
    request: Request,
    admin: Annotated[AdminUser, Depends(current_admin)],
) -> AdminPricingTierListResponse:
    del admin
    with request.app.state.session_factory() as session:
        tiers = _order_service(request).list_admin_pricing_tiers(session)
    return AdminPricingTierListResponse(
        tiers=[
            AdminPricingTierResponse(
                id=tier.id,
                name=tier.name,
                ngn_price=float(tier.ngn_price),
                is_group_tier=tier.is_group_tier,
            )
            for tier in tiers
        ]
    )


@router.patch(
    "/pricing-tiers/{tier_id}",
    response_model=PricingTierUpdateResponse,
)
def update_admin_pricing_tier(
    tier_id: UUID,
    payload: PricingTierUpdateRequest,
    request: Request,
    admin: Annotated[AdminUser, Depends(current_admin)],
) -> PricingTierUpdateResponse:
    with request.app.state.session_factory() as session:
        tier, change = _order_service(request).update_tier_price(
            session, tier_id, Decimal(str(payload.ngn_price)), admin
        )
    percent_change = (
        float((change.new_ngn_price - change.old_ngn_price) / change.old_ngn_price)
        * 100
        if change.old_ngn_price
        else 0.0
    )
    return PricingTierUpdateResponse(
        id=tier.id,
        name=tier.name,
        old_ngn_price=float(change.old_ngn_price),
        new_ngn_price=float(change.new_ngn_price),
        percent_change=percent_change,
        changed_at=change.changed_at,
    )


@router.post("/packages/{package_id}/cancel", response_model=PackageCancelResponse)
def cancel_package(
    package_id: UUID,
    request: Request,
    admin: Annotated[AdminUser, Depends(current_admin)],
) -> PackageCancelResponse:
    with request.app.state.session_factory() as session:
        package = _package_admin_service(request).cancel(session, package_id, admin)
        return PackageCancelResponse(id=package.id, status=package.status.value)
