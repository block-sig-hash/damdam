import base64
import binascii
import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from decimal import ROUND_UP, Decimal
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select
from sqlmodel.sql.expression import SelectOfScalar

from app.auth.models import User
from app.config import Settings
from app.otp.service import RedisClient
from app.packages.models import Package, PackageStatus
from app.voice.models import (
    CallLog,
    CallProvider,
    CallType,
    VerifiedCallerIdentity,
    VerifiedCallerIdentityStatus,
    VoiceCredential,
)
from app.voice.providers import VoiceAccessToken, VoiceProvider, VoiceProviderError


class VoiceError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class VoiceService:
    def __init__(
        self,
        settings: Settings,
        provider: VoiceProvider,
        clock: Callable[[], datetime],
        redis_client: RedisClient | None = None,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.clock = clock
        self.redis = redis_client

    def eligibility(
        self, session: Session, user: User, to_number: str
    ) -> dict[str, object]:
        target = session.exec(
            select(User).where(User.phone_number == to_number)
        ).first()
        balance = self._remaining_balance(session, user.id)
        if target is not None:
            return {
                "allowed": True,
                "call_type": CallType.APP_TO_APP,
                "destination": None,
                "reason": None,
                "pstn_minutes_remaining": float(balance),
            }
        reason = None
        if self._active_caller_identity(session, user.id) is None:
            reason = "cli_not_verified"
        elif balance <= 0:
            reason = "pstn_balance_exhausted"
        return {
            "allowed": reason is None,
            "call_type": CallType.PSTN,
            "destination": to_number if reason is None else None,
            "reason": reason,
            "pstn_minutes_remaining": float(balance),
        }

    def token(
        self,
        session: Session,
        user: User,
        to_number: str,
        idempotency_key: str | None = None,
    ) -> tuple[VoiceAccessToken, VoiceCredential, dict[str, object]]:
        eligibility = self.eligibility(session, user, to_number)
        reason = eligibility["reason"]
        if reason:
            raise VoiceError(str(reason))
        if eligibility["call_type"] == CallType.APP_TO_APP:
            target = session.exec(
                select(User).where(User.phone_number == to_number)
            ).first()
            if target is None:
                raise VoiceError("voice_unavailable")
            eligibility["destination"] = self._credential(session, target).sip_username
        elif self.redis is not None:
            # Bridges the REST /voice/token request to the later, webhook-
            # driven call.initiated event so a retried token request and its
            # eventual Telnyx call share one idempotency_key on the CallLog
            # (data-model.md §6.40) -- best-effort; a miss just leaves the
            # column null, it never blocks the call.
            self.redis.set(
                f"voice:pending_call:{user.id}",
                idempotency_key or "",
                ex=self.settings.cli_pending_idempotency_ttl_seconds,
            )
        credential = self._credential(session, user)
        try:
            token = self.provider.issue_token(credential.telnyx_telephony_credential_id)
        except VoiceProviderError as exc:
            raise VoiceError("voice_unavailable") from exc
        return token, credential, eligibility

    def history(self, session: Session, user: User, limit: int) -> list[CallLog]:
        return list(
            session.exec(
                select(CallLog)
                .where(CallLog.user_id == user.id)
                .order_by(col(CallLog.started_at).desc())
                .limit(min(limit, 20))
            ).all()
        )

    def process_webhook(
        self, session: Session, body: bytes, headers: Mapping[str, str]
    ) -> bool:
        self._verify_signature(body, headers)
        try:
            envelope = json.loads(body)
            data = envelope["data"]
            event_type = str(data["event_type"])
            payload = data["payload"]
            if not isinstance(payload, dict):
                raise TypeError
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise VoiceError("invalid_webhook_payload") from exc

        if event_type == "call.initiated":
            return self._handle_initiated(session, payload)
        if event_type == "call.answered":
            return self._handle_answered(payload)
        if event_type == "call.hangup":
            return self._handle_hangup(session, payload)
        return False

    def _handle_initiated(self, session: Session, payload: dict[str, Any]) -> bool:
        # Only the client/WebRTC leg has a SIP username as its source. Provider-
        # generated PSTN legs carry client_state and must not recursively dial.
        if payload.get("client_state"):
            return False
        username = str(payload.get("from", "")).split("@", 1)[0].removeprefix("sip:")
        credential = session.exec(
            select(VoiceCredential).where(VoiceCredential.sip_username == username)
        ).first()
        if credential is None:
            return False
        user = session.get(User, credential.user_id)
        if user is None:
            return False
        to_number = str(payload.get("to", ""))
        target_credential = session.exec(
            select(VoiceCredential).where(
                VoiceCredential.sip_username == self._sip_username(to_number)
            )
        ).first()
        if target_credential is not None:
            return False  # Telnyx routes the registered SIP destination directly.
        target = session.exec(
            select(User).where(User.phone_number == to_number)
        ).first()
        if target is not None:
            return False
        balance = self._remaining_balance(session, user.id)
        identity = self._active_caller_identity(session, user.id)
        if identity is None or balance <= 0:
            self._log_pstn_rejection(
                session,
                user_id=user.id,
                call_control_id=str(payload.get("call_control_id", "")),
                to_number=to_number,
                failure_code="cli_not_verified" if identity is None else (
                    "insufficient_balance"
                ),
            )
            return False
        idempotency_key = None
        if self.redis is not None:
            idempotency_key = self.redis.get(f"voice:pending_call:{user.id}") or None
            self.redis.delete(f"voice:pending_call:{user.id}")
        try:
            self.provider.initiate_call(
                webrtc_call_control_id=str(payload["call_control_id"]),
                user_id=str(user.id),
                caller_id=identity.phone_number,
                to_number=to_number,
                time_limit_seconds=int(balance * 60),
                verified_caller_identity_id=str(identity.id),
                idempotency_key=idempotency_key,
            )
        except (KeyError, VoiceProviderError) as exc:
            raise VoiceError("voice_unavailable") from exc
        return True

    def _log_pstn_rejection(
        self,
        session: Session,
        *,
        user_id: UUID,
        call_control_id: str,
        to_number: str,
        failure_code: str,
    ) -> None:
        if not call_control_id:
            return
        log = CallLog(
            user_id=user_id,
            telnyx_call_leg_id=call_control_id,
            call_type=CallType.PSTN,
            to_number=to_number,
            duration_seconds=0,
            pstn_minutes_charged=Decimal("0.00"),
            started_at=self.clock(),
            failure_code=failure_code,
            failure_description="Call was not placed; see failure_code.",
        )
        session.add(log)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()

    def _handle_answered(self, payload: dict[str, Any]) -> bool:
        state = self._client_state(payload.get("client_state"))
        if state is None:
            return False
        try:
            self.provider.bridge_call(
                str(payload["call_control_id"]),
                str(state["webrtc_call_control_id"]),
            )
        except (KeyError, VoiceProviderError) as exc:
            raise VoiceError("voice_unavailable") from exc
        return True

    def _handle_hangup(self, session: Session, payload: dict[str, Any]) -> bool:
        state = self._client_state(payload.get("client_state"))
        if state is None:
            return self._handle_app_to_app_hangup(session, payload)
        try:
            user_id = UUID(str(state["user_id"]))
            call_leg_id = str(payload["call_leg_id"])
            started_at = self._datetime(payload["start_time"])
            ended_at = self._datetime(payload.get("end_time") or self.clock())
            to_number = str(payload["to"])
        except (KeyError, TypeError, ValueError) as exc:
            raise VoiceError("invalid_webhook_payload") from exc
        duration_seconds = max(0, int((ended_at - started_at).total_seconds()))
        requested_charge = (Decimal(duration_seconds) / Decimal(60)).quantize(
            Decimal("0.01"), rounding=ROUND_UP
        )
        raw_identity_id = state.get("verified_caller_identity_id")
        identity_id = UUID(str(raw_identity_id)) if raw_identity_id else None
        raw_idempotency_key = state.get("idempotency_key")
        idempotency_key = str(raw_idempotency_key) if raw_idempotency_key else None

        # The unique call-leg insert is the idempotency boundary. On Postgres,
        # the selected package row is locked until commit, serializing rapid
        # hangups near zero and ensuring the second charge observes the first.
        log = CallLog(
            user_id=user_id,
            telnyx_call_leg_id=call_leg_id,
            call_type=CallType.PSTN,
            to_number=to_number,
            duration_seconds=duration_seconds,
            pstn_minutes_charged=Decimal("0.00"),
            started_at=started_at,
            ended_at=ended_at,
            verified_caller_identity_id=identity_id,
            idempotency_key=idempotency_key,
            requested_provider=CallProvider.TELNYX,
        )
        session.add(log)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            return False

        package = None
        billing_user = session.get(User, user_id)
        if billing_user is not None:
            package = session.exec(
                self._active_package_query(billing_user)
                .where(Package.pstn_minutes_remaining > 0)
                .order_by(col(Package.purchased_at).desc())
                .with_for_update()
            ).first()
        charged = Decimal("0.00")
        if package is not None:
            charged = min(Decimal(package.pstn_minutes_remaining), requested_charge)
            package.pstn_minutes_remaining = max(
                Decimal("0.00"), Decimal(package.pstn_minutes_remaining) - charged
            )
            session.add(package)
        log.pstn_minutes_charged = charged
        session.add(log)
        session.commit()
        return True

    def _handle_app_to_app_hangup(
        self, session: Session, payload: dict[str, Any]
    ) -> bool:
        from_username = self._sip_username(payload.get("from"))
        to_username = self._sip_username(payload.get("to"))
        caller = session.exec(
            select(VoiceCredential).where(VoiceCredential.sip_username == from_username)
        ).first()
        target = session.exec(
            select(VoiceCredential).where(VoiceCredential.sip_username == to_username)
        ).first()
        if caller is None or target is None:
            return False
        target_user = session.get(User, target.user_id)
        if target_user is None:
            return False
        try:
            started_at = self._datetime(payload["start_time"])
            ended_at = self._datetime(payload.get("end_time") or self.clock())
            call_leg_id = str(payload["call_leg_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise VoiceError("invalid_webhook_payload") from exc
        log = CallLog(
            user_id=caller.user_id,
            telnyx_call_leg_id=call_leg_id,
            call_type=CallType.APP_TO_APP,
            to_number=target_user.phone_number,
            duration_seconds=max(0, int((ended_at - started_at).total_seconds())),
            pstn_minutes_charged=Decimal("0.00"),
            started_at=started_at,
            ended_at=ended_at,
        )
        session.add(log)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return False
        return True

    def _active_caller_identity(
        self, session: Session, user_id: UUID
    ) -> VerifiedCallerIdentity | None:
        return session.exec(
            select(VerifiedCallerIdentity).where(
                VerifiedCallerIdentity.user_id == user_id,
                VerifiedCallerIdentity.status == VerifiedCallerIdentityStatus.ACTIVE,
            )
        ).first()

    def _credential(self, session: Session, user: User) -> VoiceCredential:
        existing = session.exec(
            select(VoiceCredential).where(VoiceCredential.user_id == user.id)
        ).first()
        if existing is not None:
            return existing
        try:
            provisioned = self.provider.create_credential(str(user.id))
        except VoiceProviderError as exc:
            raise VoiceError("voice_unavailable") from exc
        credential = VoiceCredential(
            user_id=user.id,
            telnyx_telephony_credential_id=provisioned.credential_id,
            sip_username=provisioned.sip_username,
            created_at=self.clock(),
        )
        session.add(credential)
        session.commit()
        session.refresh(credential)
        return credential

    def _active_package_query(self, user: User) -> SelectOfScalar[Package]:
        # Scoped by destination_country, not just user_id: a user can now
        # hold an ACTIVE package per destination at once (data-model.md
        # §6.32), and a call should only ever bill against the package
        # for the destination the user's account currently indicates --
        # picking "most recently purchased" across destinations would
        # silently charge minutes against an unrelated trip's balance.
        return select(Package).where(
            Package.user_id == user.id,
            Package.destination_country == user.destination_country,
            Package.status == PackageStatus.ACTIVE,
        )

    def _remaining_balance(self, session: Session, user_id: UUID) -> Decimal:
        user = session.get(User, user_id)
        if user is None:
            return Decimal("0.00")
        package = session.exec(
            self._active_package_query(user).order_by(col(Package.purchased_at).desc())
        ).first()
        return Decimal(package.pstn_minutes_remaining) if package else Decimal("0.00")

    def _verify_signature(self, body: bytes, headers: Mapping[str, str]) -> None:
        timestamp = headers.get("telnyx-timestamp", "")
        signature = headers.get("telnyx-signature-ed25519", "")
        try:
            sent_at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
            if (
                abs((self.clock() - sent_at).total_seconds())
                > self.settings.telnyx_webhook_tolerance_seconds
            ):
                raise ValueError
            public_key = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(self.settings.telnyx_public_key, validate=True)
            )
            public_key.verify(
                base64.b64decode(signature, validate=True),
                timestamp.encode() + b"|" + body,
            )
        except (ValueError, TypeError, binascii.Error, InvalidSignature) as exc:
            raise VoiceError("invalid_webhook_signature") from exc

    @staticmethod
    def _client_state(value: object) -> dict[str, object] | None:
        if not value:
            return None
        try:
            decoded = json.loads(base64.b64decode(str(value), validate=True))
            return decoded if isinstance(decoded, dict) else None
        except (ValueError, TypeError, binascii.Error, json.JSONDecodeError):
            return None

    @staticmethod
    def _datetime(value: object) -> datetime:
        if isinstance(value, datetime):
            result = value
        else:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)

    @staticmethod
    def _sip_username(value: object) -> str:
        return str(value or "").split("@", 1)[0].removeprefix("sip:")
