import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import jwt
from sqlmodel import Session, select

from app.auth.models import RefreshToken, User, UserStatus
from app.config import Settings


class InvalidRefreshTokenError(Exception):
    pass


def decode_with_clock(
    token: str, secret: str, audience: str, now: datetime
) -> dict[str, Any]:
    """Verify signed claims and all NumericDates using the caller's clock."""
    claims: dict[str, Any] = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        audience=audience,
        options={
            "verify_exp": False,
            "verify_iat": False,
            "verify_nbf": False,
            "require": ["exp"],
        },
    )
    timestamp = now.timestamp()
    for name in ("exp", "iat", "nbf"):
        if name not in claims:
            continue
        try:
            value = claims[name]
            if isinstance(value, bool):
                raise ValueError("boolean NumericDate")
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError("nonfinite NumericDate")
        except (TypeError, ValueError, OverflowError) as exc:
            raise jwt.InvalidTokenError(f"invalid {name}") from exc
        if name == "exp" and numeric <= timestamp:
            raise jwt.ExpiredSignatureError("expired token")
        if name != "exp" and numeric > timestamp:
            raise jwt.ImmatureSignatureError(f"future {name}")
    return claims


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str


class TokenService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def issue(self, session: Session, user: User, now: datetime) -> TokenPair:
        access_jti = uuid4()
        refresh_jti = uuid4()
        access_expiry = now + timedelta(minutes=self.settings.jwt_access_ttl_minutes)
        refresh_expiry = now + timedelta(days=self.settings.jwt_refresh_ttl_days)
        access = jwt.encode(
            {
                "sub": str(user.id),
                "aud": "pilgrim",
                "type": "access",
                "jti": str(access_jti),
                "iat": now,
                "exp": access_expiry,
            },
            self.settings.jwt_secret,
            algorithm="HS256",
        )
        refresh = jwt.encode(
            {
                "sub": str(user.id),
                "aud": "pilgrim",
                "type": "refresh",
                "jti": str(refresh_jti),
                "iat": now,
                "exp": refresh_expiry,
            },
            self.settings.jwt_secret,
            algorithm="HS256",
        )
        session.add(
            RefreshToken(
                id=refresh_jti,
                user_id=user.id,
                token_hash=self._hash(refresh),
                expires_at=refresh_expiry,
            )
        )
        return TokenPair(access_token=access, refresh_token=refresh)

    def rotate(self, session: Session, token: str, now: datetime) -> TokenPair:
        try:
            claims = decode_with_clock(token, self.settings.jwt_secret, "pilgrim", now)
            if claims.get("type") != "refresh":
                raise InvalidRefreshTokenError
            token_id = UUID(claims["jti"])
            user_id = UUID(claims["sub"])
        except InvalidRefreshTokenError:
            raise
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise InvalidRefreshTokenError from exc

        stored = session.exec(
            select(RefreshToken)
            .where(
                RefreshToken.id == token_id,
                RefreshToken.token_hash == self._hash(token),
            )
            .with_for_update()
        ).first()
        if stored is None or stored.revoked_at is not None or stored.user_id != user_id:
            raise InvalidRefreshTokenError
        expires_at = stored.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            raise InvalidRefreshTokenError
        user = session.get(User, user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            raise InvalidRefreshTokenError

        stored.revoked_at = now
        pair = self.issue(session, user, now)
        session.commit()
        return pair

    def decode_access(self, token: str, now: datetime) -> UUID:
        try:
            claims = decode_with_clock(token, self.settings.jwt_secret, "pilgrim", now)
            if claims.get("type") != "access":
                raise InvalidRefreshTokenError
            return UUID(claims["sub"])
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise InvalidRefreshTokenError from exc
