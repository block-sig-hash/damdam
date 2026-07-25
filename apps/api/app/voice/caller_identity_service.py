from collections.abc import Callable
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.auth.models import User
from app.config import Settings
from app.otp.service import RedisClient
from app.voice.models import (
    CallerIdConsent,
    CallerIdRevocationReason,
    IdentityVerificationStatus,
    PhoneVerificationProviderName,
    PhoneVerificationStatus,
    VerifiedCallerIdentity,
    VerifiedCallerIdentityStatus,
)
from app.voice.nigerian_numbers import InvalidNigerianNumberError, normalize_nigerian_number
from app.voice.verified_numbers import (
    PhoneVerificationProvider,
    PhoneVerificationProviderError,
)


class CallerIdentityError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CallerIdentityService:
    """AC-14.1/AC-14.10/AC-14.11 -- CLI verification decoupled from account
    login OTP (data-model.md §6.40). Owns the VerifiedCallerIdentity state
    machine; VoiceService only ever reads the resulting `active` row."""

    def __init__(
        self,
        settings: Settings,
        phone_provider: PhoneVerificationProvider,
        redis_client: RedisClient,
        clock: Callable[[], datetime],
    ) -> None:
        self.settings = settings
        self.phone_provider = phone_provider
        self.redis = redis_client
        self.clock = clock

    def start_verification(
        self, session: Session, user: User, raw_phone_number: str
    ) -> VerifiedCallerIdentity:
        try:
            phone_number = normalize_nigerian_number(raw_phone_number)
        except InvalidNigerianNumberError as exc:
            raise CallerIdentityError("invalid_phone_number") from exc

        self._enforce_rate_limit(user.id)

        try:
            attempt = self.phone_provider.start_verification(phone_number)
        except PhoneVerificationProviderError as exc:
            raise CallerIdentityError("phone_verification_unavailable") from exc

        now = self.clock()
        identity = VerifiedCallerIdentity(
            user_id=user.id,
            phone_number=phone_number,
            detected_country="NG",
            phone_verification_provider=PhoneVerificationProviderName.TELNYX,
            phone_verification_reference=attempt.reference,
            phone_verification_status=PhoneVerificationStatus.PENDING,
            status=VerifiedCallerIdentityStatus.PHONE_VERIFICATION_PENDING,
            created_at=now,
            updated_at=now,
        )
        session.add(identity)
        session.commit()
        session.refresh(identity)
        return identity

    def confirm_verification(
        self, session: Session, user: User, identity_id: UUID, code: str
    ) -> VerifiedCallerIdentity:
        identity = self._owned_identity(session, user, identity_id)
        if (
            identity.status != VerifiedCallerIdentityStatus.PHONE_VERIFICATION_PENDING
            or identity.phone_verification_reference is None
        ):
            raise CallerIdentityError("invalid_state")

        try:
            verified = self.phone_provider.confirm_verification(
                identity.phone_verification_reference, code
            )
        except PhoneVerificationProviderError as exc:
            raise CallerIdentityError("phone_verification_unavailable") from exc
        if not verified:
            raise CallerIdentityError("verification_code_invalid")

        now = self.clock()
        identity.phone_verification_status = PhoneVerificationStatus.VERIFIED
        identity.phone_verified_at = now
        identity.status = (
            VerifiedCallerIdentityStatus.IDENTITY_VERIFICATION_PENDING
            if self.settings.nin_verification_enabled
            else VerifiedCallerIdentityStatus.CONSENT_REQUIRED
        )
        if not self.settings.nin_verification_enabled:
            identity.identity_verification_status = IdentityVerificationStatus.NOT_REQUIRED
        identity.updated_at = now
        session.add(identity)
        session.commit()
        session.refresh(identity)
        return identity

    def capture_consent(
        self,
        session: Session,
        user: User,
        identity_id: UUID,
        consent_version: str,
        ip_address: str | None,
        device_session_id: str | None,
    ) -> VerifiedCallerIdentity:
        identity = self._owned_identity(session, user, identity_id)
        if identity.status != VerifiedCallerIdentityStatus.CONSENT_REQUIRED:
            raise CallerIdentityError("invalid_state")

        now = self.clock()
        previous_active = session.exec(
            select(VerifiedCallerIdentity).where(
                VerifiedCallerIdentity.user_id == user.id,
                VerifiedCallerIdentity.status == VerifiedCallerIdentityStatus.ACTIVE,
                col(VerifiedCallerIdentity.id) != identity_id,
            )
        ).first()
        if previous_active is not None:
            self._revoke(
                session, previous_active, CallerIdRevocationReason.USER_REVOKED, now
            )
            # Must be flushed before the new row's own status flips to
            # `active` below -- otherwise the unit-of-work may order the two
            # writes so both rows are momentarily `active` at once, tripping
            # ux_verified_caller_identities_active_user spuriously.
            session.flush()

        consent = CallerIdConsent(
            user_id=user.id,
            verified_caller_identity_id=identity.id,
            consent_version=consent_version,
            consented_at=now,
            ip_address=ip_address,
            device_session_id=device_session_id,
        )
        session.add(consent)
        identity.consent_version = consent_version
        identity.consent_at = now
        identity.status = VerifiedCallerIdentityStatus.ACTIVE
        identity.updated_at = now
        session.add(identity)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise CallerIdentityError("number_already_verified_elsewhere") from exc
        session.refresh(identity)
        return identity

    def revoke(
        self, session: Session, user: User, reason: CallerIdRevocationReason
    ) -> None:
        active = self._active_identity(session, user.id)
        if active is None:
            raise CallerIdentityError("no_active_caller_id")
        self._revoke(session, active, reason, self.clock())
        session.commit()

    def status(self, session: Session, user: User) -> VerifiedCallerIdentity | None:
        active = self._active_identity(session, user.id)
        if active is not None:
            return active
        return session.exec(
            select(VerifiedCallerIdentity)
            .where(VerifiedCallerIdentity.user_id == user.id)
            .order_by(col(VerifiedCallerIdentity.created_at).desc())
        ).first()

    def _revoke(
        self,
        session: Session,
        identity: VerifiedCallerIdentity,
        reason: CallerIdRevocationReason,
        now: datetime,
    ) -> None:
        consent = session.exec(
            select(CallerIdConsent)
            .where(
                CallerIdConsent.verified_caller_identity_id == identity.id,
                col(CallerIdConsent.revoked_at).is_(None),
            )
            .order_by(col(CallerIdConsent.consented_at).desc())
        ).first()
        if consent is not None:
            consent.revoked_at = now
            consent.revocation_reason = reason.value
            session.add(consent)
        identity.status = VerifiedCallerIdentityStatus.REVOKED
        identity.updated_at = now
        session.add(identity)

    def _active_identity(
        self, session: Session, user_id: UUID
    ) -> VerifiedCallerIdentity | None:
        return session.exec(
            select(VerifiedCallerIdentity).where(
                VerifiedCallerIdentity.user_id == user_id,
                VerifiedCallerIdentity.status == VerifiedCallerIdentityStatus.ACTIVE,
            )
        ).first()

    def _owned_identity(
        self, session: Session, user: User, identity_id: UUID
    ) -> VerifiedCallerIdentity:
        identity = session.get(VerifiedCallerIdentity, identity_id)
        if identity is None or identity.user_id != user.id:
            raise CallerIdentityError("caller_identity_not_found")
        return identity

    def _enforce_rate_limit(self, user_id: UUID) -> None:
        key = f"cli_verify:attempts:{user_id}"
        window = self.settings.cli_verification_rate_limit_window_seconds
        now_ts = self.clock().timestamp()
        self.redis.zremrangebyscore(key, 0, now_ts - window)
        if self.redis.zcard(key) >= self.settings.cli_verification_max_attempts_per_window:
            raise CallerIdentityError("cli_verification_rate_limited")
        self.redis.zadd(key, {str(uuid4()): now_ts})
        self.redis.expire(key, window)
