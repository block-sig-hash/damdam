from typing import Annotated, cast
from uuid import UUID

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.hto import HTOAuthError
from app.auth.models import (
    HTOApprovalStatus,
    Organization,
    OrganizationType,
    User,
    UserStatus,
)
from app.auth.pin import PINError, PINService
from app.auth.tokens import InvalidRefreshTokenError, TokenService, decode_with_clock
from app.db import SessionFactory

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise PINError("invalid_access_token")
    token_service = cast(TokenService, request.app.state.otp_service.tokens)
    pin_service = cast(PINService, request.app.state.pin_service)
    try:
        identity = token_service.decode_access_identity(
            credentials.credentials, pin_service.clock()
        )
    except InvalidRefreshTokenError as exc:
        raise PINError("invalid_access_token") from exc

    factory = cast(SessionFactory, request.app.state.session_factory)
    with factory() as session:
        user = session.get(User, identity.user_id)
        if (
            user is None
            or user.status != UserStatus.ACTIVE
            or user.auth_version != identity.auth_version
        ):
            raise PINError("invalid_access_token")
        session.expunge(user)
        return user


def get_current_organization(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Organization:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTOAuthError("invalid_operator_token")
    try:
        claims = decode_with_clock(
            credentials.credentials,
            request.app.state.settings.jwt_secret,
            "hto_dashboard",
            request.app.state.clock(),
        )
        if claims.get("type") != "access":
            raise HTOAuthError("invalid_operator_token")
        organization_id = UUID(claims["sub"])
    except HTOAuthError:
        raise
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise HTOAuthError("invalid_operator_token") from exc

    factory = cast(SessionFactory, request.app.state.session_factory)
    with factory() as session:
        organization = session.get(Organization, organization_id)
        if (
            organization is None
            or organization.org_type != OrganizationType.HTO_OPERATOR
            or not organization.email_verified
            or organization.approval_status != HTOApprovalStatus.APPROVED
        ):
            raise HTOAuthError("invalid_operator_token")
        session.expunge(organization)
        return organization
