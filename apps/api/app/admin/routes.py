from datetime import datetime, timezone
from typing import Annotated, cast
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.hto import HTOAuthError, HTOService
from app.auth.models import AdminUser, HTOApprovalStatus
from app.auth.schemas import (
    HTOApprovalResponse,
    HTOOperatorListResponse,
    HTOOperatorResponse,
)

router = APIRouter(prefix="/admin", tags=["admin"])
bearer = HTTPBearer(auto_error=False)


def _service(request: Request) -> HTOService:
    return cast(HTOService, request.app.state.hto_service)


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
        operators = _service(request).list_operators(session, status)
    return HTOOperatorListResponse(
        operators=[HTOOperatorResponse.model_validate(item) for item in operators]
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
        operator = _service(request).approve(session, operator_id, admin.id)
    return HTOApprovalResponse(approval_status=operator.approval_status)
