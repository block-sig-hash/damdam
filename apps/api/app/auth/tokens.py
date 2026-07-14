import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
from sqlmodel import Session, select

from app.auth.models import RefreshToken, User, UserStatus
from app.config import Settings


class InvalidRefreshTokenError(Exception):
    pass


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
            claims = jwt.decode(
                token,
                self.settings.jwt_secret,
                algorithms=["HS256"],
                audience="pilgrim",
            )
            if claims.get("type") != "refresh":
                raise InvalidRefreshTokenError
            token_id = UUID(claims["jti"])
            user_id = UUID(claims["sub"])
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise InvalidRefreshTokenError from exc

        stored = session.exec(
            select(RefreshToken).where(
                RefreshToken.id == token_id,
                RefreshToken.token_hash == self._hash(token),
            )
        ).first()
        if stored is None or stored.revoked_at is not None:
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
            claims = jwt.decode(
                token,
                self.settings.jwt_secret,
                algorithms=["HS256"],
                audience="pilgrim",
                # exp is checked manually below against the injected
                # clock, not wall-clock time, so tests (and any future
                # clock-skewed deployment) can validate expiry
                # deterministically. iat must be disabled for the same
                # reason: PyJWT's default iat check compares the
                # token's iat against real wall-clock time regardless
                # of what `now` this call receives, which rejects a
                # token minted at a mocked-forward clock as "not yet
                # valid" even though it's entirely self-consistent.
                options={"verify_exp": False, "verify_iat": False},
            )
            if claims.get("type") != "access":
                raise InvalidRefreshTokenError
            expires_at = datetime.fromtimestamp(float(claims["exp"]), tz=timezone.utc)
            if expires_at <= now:
                raise InvalidRefreshTokenError
            return UUID(claims["sub"])
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise InvalidRefreshTokenError from exc
