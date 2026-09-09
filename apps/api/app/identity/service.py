"""Identity linking and account recovery (US-29).

Three rules govern everything here:

1. **A token proves one thing, once, for a bounded time.** Single-use, expiring
   and purpose-bound, all enforced in the database rather than by control flow.
2. **An unverified claim grants nothing and blocks nobody.** Ownership must be
   proved before an identifier means anything, and a squatter must not be able
   to lock the real owner out.
3. **Probing must not be informative.** Recovery answers identically whether or
   not the identifier exists, and does the work only when it does.
"""

import hashlib
import math
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from sqlalchemy import CursorResult, update
from sqlmodel import Session, col, select

from app.auth.models import Locale, RefreshToken, User, utc_now
from app.identity.delivery import DeliveryRequest, DeliveryTransport
from app.identity.models import (
    AccountIdentifier,
    IdentifierKind,
    IdentityToken,
    IdentityTokenPurpose,
)

TOKEN_BYTES = 32


class IdentityError(Exception):
    def __init__(self, code: str, retry_after: int | None = None) -> None:
        self.code = code
        self.retry_after = retry_after
        super().__init__(code)


def normalize(kind: IdentifierKind, value: str) -> str:
    """Normalise before storing *and* before looking up.

    The unique index compares stored values, so if these two ever diverge the
    index stops protecting the invariant it exists for.
    """
    cleaned = value.strip()
    if kind is IdentifierKind.EMAIL:
        return cleaned.lower()
    return cleaned


class IdentityService:
    def __init__(
        self,
        transport: DeliveryTransport,
        clock: Callable[[], datetime] = utc_now,
        token_ttl: timedelta = timedelta(hours=1),
        redis: Any | None = None,
        send_cooldown_seconds: int = 60,
        sends_per_hour: int = 5,
    ) -> None:
        self.transport = transport
        self.clock = clock
        self.token_ttl = token_ttl
        self.redis = redis
        self.send_cooldown_seconds = send_cooldown_seconds
        self.sends_per_hour = sends_per_hour

    # --- abuse control ----------------------------------------------------

    def _check_send_limit(
        self, kind: IdentifierKind, value: str, purpose: IdentityTokenPurpose
    ) -> None:
        """Throttle per identifier, before deciding whether it exists.

        This runs on every request, known address or not. If it only applied to
        real accounts, the throttle would answer the question the uniform
        response is there to hide -- and without it, a uniform "we sent it"
        reply is a way to post mail to a stranger repeatedly.
        """
        if self.redis is None:
            return
        now = self.clock().timestamp()
        # Scoped by purpose as well as identifier: verification and recovery
        # are different flows chosen by the caller, so separate budgets leak
        # nothing, and sharing one would stop someone linking an address and
        # then recovering with it.
        key = f"identity:sends:{purpose.value}:{kind.value}:{value}"
        self.redis.zremrangebyscore(key, "-inf", now - 3600)
        recent = self.redis.zrevrange(key, 0, 0, withscores=True)
        if recent:
            elapsed = now - float(recent[0][1])
            if elapsed < self.send_cooldown_seconds:
                raise IdentityError(
                    "identity_send_throttled",
                    math.ceil(self.send_cooldown_seconds - elapsed),
                )
        if self.redis.zcard(key) >= self.sends_per_hour:
            oldest = self.redis.zrange(key, 0, 0, withscores=True)
            raise IdentityError(
                "identity_send_throttled",
                math.ceil(3600 - (now - float(oldest[0][1]))),
            )
        self.redis.zadd(key, {f"{now}:{secrets.token_hex(4)}": now})
        self.redis.expire(key, 3600)

    # --- tokens -----------------------------------------------------------

    @staticmethod
    def _hash(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    def _issue_token(
        self,
        session: Session,
        user: User,
        purpose: IdentityTokenPurpose,
        identifier: AccountIdentifier | None,
    ) -> str:
        raw = secrets.token_urlsafe(TOKEN_BYTES)
        session.add(
            IdentityToken(
                user_id=user.id,
                identifier_id=identifier.id if identifier else None,
                purpose=purpose,
                token_hash=self._hash(raw),
                expires_at=self.clock() + self.token_ttl,
            )
        )
        session.flush()
        return raw

    def _consume(
        self,
        session: Session,
        raw: str,
        purpose: IdentityTokenPurpose,
        now: datetime | None = None,
    ) -> IdentityToken:
        """Claim a token atomically, or fail.

        The UPDATE ... WHERE consumed_at IS NULL is what makes this safe under
        concurrency: two simultaneous requests both match the row, but only one
        UPDATE reports a row changed. Reading first and writing second would let
        both callers pass.
        """
        moment = now or self.clock()
        token = session.exec(
            select(IdentityToken).where(IdentityToken.token_hash == self._hash(raw))
        ).first()
        # A wrong purpose is reported as invalid, not as "wrong purpose": the
        # distinction would tell a holder what they are holding.
        if token is None or token.purpose is not purpose:
            raise IdentityError("identity_token_invalid")
        if token.consumed_at is not None:
            raise IdentityError("identity_token_invalid")
        # Expiry is exclusive: a token is dead *at* expires_at, not after it.
        expires_at = token.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if moment >= expires_at:
            raise IdentityError("identity_token_expired")

        claimed = cast(
            CursorResult[Any],
            session.execute(
                update(IdentityToken)
                .where(
                    col(IdentityToken.id) == token.id,
                    col(IdentityToken.consumed_at).is_(None),
                )
                .values(consumed_at=moment)
            ),
        )
        if claimed.rowcount != 1:
            raise IdentityError("identity_token_invalid")
        session.refresh(token)
        return token

    # --- linking ----------------------------------------------------------

    def start_identifier_verification(
        self,
        session: Session,
        user: User,
        kind: IdentifierKind,
        value: str,
        locale: Locale = Locale.EN,
    ) -> AccountIdentifier:
        """Claim an identifier and send proof-of-ownership out of band.

        Creating the claim is deliberately permissive -- anyone may *claim* any
        address. It confers nothing until confirmed, and the partial unique
        index means a claim on an already-verified identifier can never be
        confirmed.
        """
        normalized = normalize(kind, value)
        self._check_send_limit(
            kind, normalized, IdentityTokenPurpose.VERIFY_IDENTIFIER
        )
        identifier = session.exec(
            select(AccountIdentifier).where(
                AccountIdentifier.user_id == user.id,
                AccountIdentifier.kind == kind,
                AccountIdentifier.value == normalized,
            )
        ).first()
        if identifier is None:
            identifier = AccountIdentifier(
                user_id=user.id, kind=kind, value=normalized
            )
            session.add(identifier)
            session.flush()

        raw = self._issue_token(
            session, user, IdentityTokenPurpose.VERIFY_IDENTIFIER, identifier
        )
        self.transport.send(
            DeliveryRequest(
                kind=kind,
                value=normalized,
                purpose=IdentityTokenPurpose.VERIFY_IDENTIFIER,
                token=raw,
                locale=locale,
            )
        )
        return identifier

    def confirm_identifier(
        self, session: Session, raw: str, now: datetime | None = None
    ) -> AccountIdentifier:
        token = self._consume(
            session, raw, IdentityTokenPurpose.VERIFY_IDENTIFIER, now
        )
        identifier = (
            session.get(AccountIdentifier, token.identifier_id)
            if token.identifier_id
            else None
        )
        if identifier is None:
            raise IdentityError("identity_token_invalid")

        already = session.exec(
            select(AccountIdentifier).where(
                AccountIdentifier.kind == identifier.kind,
                AccountIdentifier.value == identifier.value,
                col(AccountIdentifier.verified_at).is_not(None),
            )
        ).first()
        if already is not None and already.user_id != identifier.user_id:
            raise IdentityError("identifier_already_verified")

        identifier.verified_at = now or self.clock()
        if not session.exec(
            select(AccountIdentifier).where(
                AccountIdentifier.user_id == identifier.user_id,
                col(AccountIdentifier.is_primary).is_(True),
            )
        ).first():
            identifier.is_primary = True
        session.add(identifier)
        session.flush()
        return identifier

    def adopt_legacy_phone(self, session: Session, user: User) -> AccountIdentifier:
        """Give an account that predates this chunk a verified identifier.

        Its phone number was already proved by OTP at signup, so it is recorded
        as verified rather than asking established users to re-prove something
        they have been using to log in. Idempotent, so a backfill can be re-run.
        """
        normalized = normalize(IdentifierKind.PHONE, user.phone_number)
        existing = session.exec(
            select(AccountIdentifier).where(
                AccountIdentifier.user_id == user.id,
                AccountIdentifier.kind == IdentifierKind.PHONE,
                AccountIdentifier.value == normalized,
            )
        ).first()
        if existing is not None:
            return existing
        identifier = AccountIdentifier(
            user_id=user.id,
            kind=IdentifierKind.PHONE,
            value=normalized,
            verified_at=self.clock(),
            is_primary=True,
        )
        session.add(identifier)
        session.flush()
        return identifier

    # --- recovery ---------------------------------------------------------

    def request_recovery(
        self,
        session: Session,
        kind: IdentifierKind,
        value: str,
        locale: Locale = Locale.EN,
    ) -> None:
        """Always returns None, whether or not the identifier exists.

        The caller cannot distinguish the cases, and neither can an attacker
        timing the endpoint at human resolution. Only a *verified* identifier
        produces a message: an unverified claim must never be a way in.
        """
        normalized = normalize(kind, value)
        # Throttle first, so the limit applies identically whether or not the
        # address is known.
        self._check_send_limit(
            kind, normalized, IdentityTokenPurpose.RECOVER_ACCOUNT
        )
        identifier = session.exec(
            select(AccountIdentifier).where(
                AccountIdentifier.kind == kind,
                AccountIdentifier.value == normalized,
                col(AccountIdentifier.verified_at).is_not(None),
            )
        ).first()
        if identifier is None:
            return None
        user = session.get(User, identifier.user_id)
        if user is None:
            return None

        raw = self._issue_token(
            session, user, IdentityTokenPurpose.RECOVER_ACCOUNT, identifier
        )
        self.transport.send(
            DeliveryRequest(
                kind=kind,
                value=normalized,
                purpose=IdentityTokenPurpose.RECOVER_ACCOUNT,
                token=raw,
                locale=locale,
            )
        )
        return None

    def complete_recovery(
        self, session: Session, raw: str, now: datetime | None = None
    ) -> User:
        """Consume a recovery token and revoke every existing session.

        Revocation is the point: recovery is what someone does when they have
        lost control of the account, so whoever else was holding a session must
        lose it in the same transaction.
        """
        moment = now or self.clock()
        token = self._consume(session, raw, IdentityTokenPurpose.RECOVER_ACCOUNT, now)
        user = session.get(User, token.user_id)
        if user is None:
            raise IdentityError("identity_token_invalid")

        session.execute(
            update(RefreshToken)
            .where(
                col(RefreshToken.user_id) == user.id,
                col(RefreshToken.revoked_at).is_(None),
            )
            .values(revoked_at=moment)
        )
        # Any other outstanding recovery token is invalidated too, so an older
        # link in a mailbox cannot be replayed after this one has been used.
        session.execute(
            update(IdentityToken)
            .where(
                col(IdentityToken.user_id) == user.id,
                col(IdentityToken.purpose) == IdentityTokenPurpose.RECOVER_ACCOUNT,
                col(IdentityToken.consumed_at).is_(None),
            )
            .values(consumed_at=moment)
        )
        session.flush()
        return user
