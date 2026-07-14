from datetime import datetime, timezone
from typing import Annotated, cast
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.hto import HTOAuthError, HTOService
from app.auth.models import AdminUser, HTOApprovalStatus, ManifestOrderStatus
from app.auth.schemas import (
    HTOApprovalResponse,
    HTOOperatorListResponse,
    HTOOperatorResponse,
)
from app.manifests.orders import ManifestOrderService
from app.manifests.schemas import (
    AdminManifestOrderListResponse,
    PaymentConfirmationResponse,
)

router = APIRouter(prefix="/admin", tags=["admin"])
bearer = HTTPBearer(auto_error=False)


def _service(request: Request) -> HTOService:
    return cast(HTOService, request.app.state.hto_service)


def _order_service(request: Request) -> ManifestOrderService:
    return cast(ManifestOrderService, request.app.state.manifest_order_service)


def current_admin(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer)
    ],
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
        operators=[
            HTOOperatorResponse.model_validate(item) for item in organizations
        ]
    )


@router.post(
    "/hto-operators/{operator_id}/approve", response_model=HTOApprovalResponse
)
def approve_hto_operator(
    operator_id: UUID,
    request: Request,
    admin: Annotated[AdminUser, Depends(current_admin)],
) -> HTOApprovalResponse:
    with request.app.state.session_factory() as session:
        organization = _service(request).approve(session, operator_id, admin.id)
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
