"""Second-factor enrollment, step-up and revocation (US-29, AC-29.5).

The rules that matter, and the incident each one prevents:

- **Beginning enrollment grants nothing.** A `PENDING` credential authorizes no
  privileged action, so "start enrolling" cannot itself be the bypass.
- **A code is spent when it is used.** TOTP codes stay arithmetically valid for
  their whole step; without a spent-counter a code seen over a shoulder or in a
  screenshot is reusable for the rest of that window.
- **Wrong codes cost something.** Six digits is a million guesses, which is not
  many; the same attempt limit and lockout the PIN service uses applies here.
- **Re-enrolling invalidates everything the old credential could do** -- its
  secret, its recovery codes and every elevation it granted. A replaced
  authenticator that still works is a key you no longer know exists.
- **Revocation is a row update, not an expiry.** Nothing is cached and no
  authority rides in a token, so a membership revoked in one transaction is
  refused on the next request rather than at the next token refresh.
"""

import base64
import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from urllib.parse import quote, urlencode
from uuid import UUID

from sqlmodel import Session, col, select, update

from app.auth.models import User, utc_now
from app.mfa.models import (
    MfaRecoveryCode,
    MfaStatus,
    OrganizationElevation,
    UserMfaCredential,
)
from app.mfa.totp import verify

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to the checker
    from app.organizations.service import MembershipService

SECRET_BYTES = 20
RECOVERY_CODE_COUNT = 10
RECOVERY_CODE_BYTES = 10


class MfaError(Exception):
    def __init__(self, code: str, retry_after: int | None = None) -> None:
        self.code = code
        self.retry_after = retry_after
        super().__init__(code)


@dataclass(frozen=True)
class Enrollment:
    """Returned once, to be shown once. The raw secret is never re-readable."""

    credential: UserMfaCredential
    secret_bytes: bytes
    secret_base32: str
    otpauth_uri: str


@dataclass(frozen=True)
class ConfirmedEnrollment:
    credential: UserMfaCredential
    recovery_codes: list[str]


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class MfaService:
    ATTEMPT_LIMIT = 5
    LOCKOUT_SECONDS = 30 * 60
    #: How long one proof lasts. Short enough that a walked-away-from browser
    #: is not a standing administrator, long enough to finish a batch of
    #: membership changes without re-typing a code for each one.
    ELEVATION_TTL = timedelta(minutes=15)

    def __init__(
        self,
        clock: Callable[[], datetime] = utc_now,
        issuer: str = "DamDam",
    ) -> None:
        self.clock = clock
        self.issuer = issuer

    # --- lookups ----------------------------------------------------------

    @staticmethod
    def _hash(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    def credential(
        self,
        session: Session,
        user_id: UUID,
        status: MfaStatus | None = None,
        *,
        for_update: bool = False,
    ) -> UserMfaCredential | None:
        statement = select(UserMfaCredential).where(
            UserMfaCredential.user_id == user_id,
            UserMfaCredential.status != MfaStatus.DISABLED,
        )
        if status is not None:
            statement = statement.where(UserMfaCredential.status == status)
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        return session.exec(statement).first()

    def is_active(self, session: Session, user: User) -> bool:
        return self.credential(session, user.id, MfaStatus.ACTIVE) is not None

    # --- enrollment -------------------------------------------------------

    def begin_enrollment(self, session: Session, user: User) -> Enrollment:
        """Replace any previous credential outright.

        Not "add another": a stale authenticator that still verifies is a
        credential nobody is auditing. Disabling the old row also cascades to
        its recovery codes and elevations below.
        """
        now = self.clock()
        # Serialize first enrollment and replacement for one account. The
        # partial unique index remains the database backstop, while this lock
        # gives both concurrent requests a controlled result instead of a 500.
        session.exec(
            select(User).where(User.id == user.id).with_for_update()
        ).one()
        existing = self.credential(session, user.id, for_update=True)
        if existing is not None:
            if existing.status is MfaStatus.ACTIVE:
                # A bearer token is only the first factor. Letting it replace
                # an active authenticator turns session theft into permanent
                # account takeover. Disable with the existing factor first.
                raise MfaError("mfa_already_enrolled")
            self._disable(session, existing, now)

        secret = secrets.token_bytes(SECRET_BYTES)
        credential = UserMfaCredential(
            user_id=user.id,
            secret=secret,
            status=MfaStatus.PENDING,
            created_at=now,
        )
        session.add(credential)
        session.flush()
        return Enrollment(
            credential=credential,
            secret_bytes=secret,
            secret_base32=self._base32(secret),
            otpauth_uri=self._otpauth_uri(user, secret),
        )

    @staticmethod
    def _base32(secret: bytes) -> str:
        # Authenticator apps expect unpadded base32; the "=" padding is
        # rejected by several of them.
        return base64.b32encode(secret).decode().rstrip("=")

    def _otpauth_uri(self, user: User, secret: bytes) -> str:
        label = f"{self.issuer}:{user.id}"
        query = urlencode(
            {
                "secret": self._base32(secret),
                "issuer": self.issuer,
                "algorithm": "SHA1",
                "digits": "6",
                "period": "30",
            }
        )
        return f"otpauth://totp/{quote(label)}?{query}"

    def confirm_enrollment(
        self, session: Session, user: User, code: str
    ) -> ConfirmedEnrollment:
        credential = self.credential(
            session, user.id, MfaStatus.PENDING, for_update=True
        )
        if credential is None:
            raise MfaError("mfa_not_enrolled")
        now = self.clock()
        self._assert_unlocked(credential, now)

        counter = verify(credential.secret, code, now)
        if counter is None:
            self._record_failure(session, credential, now)
            raise MfaError("mfa_code_invalid")

        credential.status = MfaStatus.ACTIVE
        credential.confirmed_at = now
        credential.last_used_counter = counter
        credential.failed_attempts = 0
        credential.locked_until = None
        session.add(credential)
        session.flush()

        plaintext = [
            secrets.token_hex(RECOVERY_CODE_BYTES)
            for _ in range(RECOVERY_CODE_COUNT)
        ]
        for value in plaintext:
            session.add(
                MfaRecoveryCode(
                    credential_id=credential.id,
                    code_hash=self._hash(value),
                    created_at=now,
                )
            )
        session.flush()
        return ConfirmedEnrollment(credential=credential, recovery_codes=plaintext)

    def disable(self, session: Session, user: User, code: str) -> None:
        """Turning the second factor off requires the second factor.

        Otherwise a stolen session removes it, and "administrator MFA is
        required" holds only until somebody with the session says otherwise.
        """
        credential = self.credential(
            session, user.id, MfaStatus.ACTIVE, for_update=True
        )
        if credential is None:
            raise MfaError("mfa_not_enrolled")
        now = self.clock()
        self._assert_unlocked(credential, now)
        counter = verify(credential.secret, code, now)
        if counter is None or (
            credential.last_used_counter is not None
            and counter <= credential.last_used_counter
        ):
            self._record_failure(session, credential, now)
            raise MfaError("mfa_code_invalid")
        self._disable(session, credential, now)

    def disable_with_recovery_code(
        self, session: Session, user: User, code: str
    ) -> None:
        """Disable a lost authenticator with one single-use fallback code."""
        credential = self.credential(
            session, user.id, MfaStatus.ACTIVE, for_update=True
        )
        if credential is None:
            raise MfaError("mfa_not_enrolled")
        now = self.clock()
        self._assert_unlocked(credential, now)
        row = session.exec(
            select(MfaRecoveryCode)
            .where(
                MfaRecoveryCode.credential_id == credential.id,
                MfaRecoveryCode.code_hash == self._hash(code),
                col(MfaRecoveryCode.used_at).is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if row is None:
            self._record_failure(session, credential, now)
            raise MfaError("mfa_code_invalid")
        row.used_at = now
        session.add(row)
        self._disable(session, credential, now)

    def _disable(
        self, session: Session, credential: UserMfaCredential, now: datetime
    ) -> None:
        credential.status = MfaStatus.DISABLED
        credential.disabled_at = now
        session.add(credential)
        # Every elevation this credential granted dies with it, in the same
        # transaction. An elevation outliving its credential is precisely the
        # "revocation takes effect eventually" AC-29.5 forbids.
        session.execute(
            update(OrganizationElevation)
            .where(
                col(OrganizationElevation.credential_id) == credential.id,
                col(OrganizationElevation.revoked_at).is_(None),
            )
            .values(revoked_at=now)
        )
        session.execute(
            update(MfaRecoveryCode)
            .where(
                col(MfaRecoveryCode.credential_id) == credential.id,
                col(MfaRecoveryCode.used_at).is_(None),
            )
            .values(used_at=now)
        )
        session.flush()

    # --- attempt limiting -------------------------------------------------

    def _assert_unlocked(
        self, credential: UserMfaCredential, now: datetime
    ) -> None:
        if credential.locked_until is None:
            return
        locked_until = _aware(credential.locked_until)
        if now < locked_until:
            raise MfaError("mfa_locked", int((locked_until - now).total_seconds()))

    def _record_failure(
        self, session: Session, credential: UserMfaCredential, now: datetime
    ) -> None:
        if credential.locked_until is not None and now >= _aware(
            credential.locked_until
        ):
            credential.failed_attempts = 0
            credential.locked_until = None
        credential.failed_attempts += 1
        if credential.failed_attempts >= self.ATTEMPT_LIMIT:
            credential.locked_until = now + timedelta(seconds=self.LOCKOUT_SECONDS)
        session.add(credential)
        session.flush()

    # --- step-up ----------------------------------------------------------

    def active_elevation(
        self, session: Session, user_id: UUID, organization_id: UUID
    ) -> OrganizationElevation | None:
        now = self.clock()
        user = session.get(User, user_id)
        if user is None:
            return None
        rows = session.exec(
            select(OrganizationElevation).where(
                OrganizationElevation.user_id == user_id,
                OrganizationElevation.organization_id == organization_id,
                OrganizationElevation.auth_version == user.auth_version,
                col(OrganizationElevation.revoked_at).is_(None),
            )
        ).all()
        for row in rows:
            # Exclusive at the boundary, the same rule chunk 06 applies to
            # identity tokens: dead *at* expires_at, not after it.
            if now < _aware(row.expires_at):
                return row
        return None

    def _elevate(
        self,
        session: Session,
        user: User,
        organization_id: UUID,
        credential: UserMfaCredential,
        now: datetime,
    ) -> OrganizationElevation:
        elevation = OrganizationElevation(
            user_id=user.id,
            organization_id=organization_id,
            credential_id=credential.id,
            auth_version=user.auth_version,
            expires_at=now + self.ELEVATION_TTL,
            created_at=now,
        )
        session.add(elevation)
        session.flush()
        return elevation

    def elevate(
        self,
        session: Session,
        user: User,
        organization_id: UUID,
        code: str,
        memberships: "MembershipService | None" = None,
    ) -> OrganizationElevation:
        credential = self.credential(
            session, user.id, MfaStatus.ACTIVE, for_update=True
        )
        if credential is None:
            raise MfaError("mfa_not_enrolled")
        now = self.clock()
        self._assert_unlocked(credential, now)

        if memberships is not None:
            # Proving a second factor for a tenant you do not belong to must
            # not mint an elevation that a later membership would silently
            # activate.
            from app.organizations.service import MembershipError

            try:
                memberships.require_membership(session, organization_id, user.id)
            except MembershipError as exc:
                raise MfaError(exc.code) from exc

        counter = verify(credential.secret, code, now)
        if counter is None:
            self._record_failure(session, credential, now)
            raise MfaError("mfa_code_invalid")
        if (
            credential.last_used_counter is not None
            and counter <= credential.last_used_counter
        ):
            # Deliberately distinct from an invalid code, and deliberately not
            # counted as a failed attempt: the holder typed a real code, they
            # just typed it twice, and locking them out for it turns a
            # double-click into a thirty-minute outage.
            raise MfaError("mfa_code_replayed")

        credential.last_used_counter = counter
        credential.failed_attempts = 0
        credential.locked_until = None
        session.add(credential)
        return self._elevate(session, user, organization_id, credential, now)

    def elevate_with_recovery_code(
        self,
        session: Session,
        user: User,
        organization_id: UUID,
        code: str,
    ) -> OrganizationElevation:
        credential = self.credential(
            session, user.id, MfaStatus.ACTIVE, for_update=True
        )
        if credential is None:
            raise MfaError("mfa_not_enrolled")
        now = self.clock()
        self._assert_unlocked(credential, now)

        # Scoped to this credential, so one account's recovery code is not a
        # code anywhere else -- the hash is unique, but matching it globally
        # would make a leaked list usable against whoever it belongs to.
        row = session.exec(
            select(MfaRecoveryCode)
            .where(
                MfaRecoveryCode.credential_id == credential.id,
                MfaRecoveryCode.code_hash == self._hash(code),
                col(MfaRecoveryCode.used_at).is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if row is None:
            self._record_failure(session, credential, now)
            raise MfaError("mfa_code_invalid")

        row.used_at = now
        session.add(row)
        credential.failed_attempts = 0
        credential.locked_until = None
        session.add(credential)
        session.flush()
        return self._elevate(session, user, organization_id, credential, now)

    # --- revocation -------------------------------------------------------

    def revoke_elevations(
        self,
        session: Session,
        user_id: UUID,
        organization_id: UUID,
        now: datetime | None = None,
    ) -> None:
        """Drop every live proof this person holds for this tenant.

        Called whenever their authority changes -- revoked, promoted or demoted
        -- because an elevation granted under one role must not carry over into
        another.
        """
        session.execute(
            update(OrganizationElevation)
            .where(
                col(OrganizationElevation.user_id) == user_id,
                col(OrganizationElevation.organization_id) == organization_id,
                col(OrganizationElevation.revoked_at).is_(None),
            )
            .values(revoked_at=now or self.clock())
        )
        session.flush()

    # --- the gate the permission check calls ------------------------------

    def assert_stepped_up(
        self, session: Session, user_id: UUID, organization_id: UUID
    ) -> None:
        credential = self.credential(session, user_id, MfaStatus.ACTIVE)
        if credential is None:
            # "Required" has to mean refused when absent. Reporting this
            # separately from `mfa_required` is what lets a client send someone
            # to enrollment rather than to a code prompt they cannot satisfy.
            raise MfaError("mfa_enrollment_required")
        if self.active_elevation(session, user_id, organization_id) is None:
            raise MfaError("mfa_required")
