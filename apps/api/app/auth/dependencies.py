from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.models import User, UserStatus
from app.auth.pin import PINError, PINService
from app.auth.tokens import InvalidRefreshTokenError, TokenService
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
        user_id = token_service.decode_access(
            credentials.credentials, pin_service.clock()
        )
    except InvalidRefreshTokenError as exc:
        raise PINError("invalid_access_token") from exc

    factory = cast(SessionFactory, request.app.state.session_factory)
    with factory() as session:
        user = session.get(User, user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            raise PINError("invalid_access_token")
        session.expunge(user)
        return user
