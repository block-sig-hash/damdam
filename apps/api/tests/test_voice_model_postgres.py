import base64
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.models import PricingTier, User
from app.config import Settings
from app.packages.models import Package, PackageSource, PackageStatus
from app.voice.models import (
    CallLog,
    IdentityVerificationStatus,
    PhoneVerificationProviderName,
    PhoneVerificationStatus,
    VerifiedCallerIdentity,
    VerifiedCallerIdentityStatus,
)
from app.voice.service import VoiceService


class UnusedProvider:
    def create_credential(self, user_id: str):  # pragma: no cover
        raise AssertionError(user_id)

    def issue_token(self, credential_id: str):  # pragma: no cover
        raise AssertionError(credential_id)

    def initiate_call(self, **kwargs):  # pragma: no cover
        raise AssertionError(kwargs)

    def bridge_call(
        self, call_control_id: str, peer_call_control_id: str
    ):  # pragma: no cover
        raise AssertionError((call_control_id, peer_call_control_id))


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL balance-lock race test runs in CI",
)
def test_concurrent_hangups_lock_balance_at_exactly_zero() -> None:
    """AC-14.7: concurrent call-end billing cannot make balance negative."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    suffix = uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    private_key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(
        private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()
    settings = Settings(
        jwt_secret="postgres-voice-test-secret-at-least-32-characters",
        telnyx_public_key=public_key,
    )
    service = VoiceService(settings, UnusedProvider(), lambda: now)
    with Session(engine) as session:
        user = User(phone_number=f"+23480{suffix}", platform="android")
        tier = PricingTier(
            name=f"Voice-race-{suffix}",
            usd_reference_price=Decimal("100"),
            data_gb=5,
            pstn_minutes=1,
            wholesale_usd_price=Decimal("80"),
            ngn_price=Decimal("100000"),
        )
        session.add_all([user, tier])
        session.flush()
        session.add(
            Package(
                user_id=user.id,
                pricing_tier_id=tier.id,
                source=PackageSource.RETAIL,
                status=PackageStatus.ACTIVE,
                data_gb_total=5,
                data_gb_remaining=Decimal("5"),
                pstn_minutes_total=1,
                pstn_minutes_remaining=Decimal("0.50"),
                purchased_at=now,
            )
        )
        session.add(
            VerifiedCallerIdentity(
                user_id=user.id,
                phone_number=user.phone_number,
                detected_country="NG",
                phone_verification_provider=PhoneVerificationProviderName.TELNYX,
                phone_verification_status=PhoneVerificationStatus.VERIFIED,
                phone_verified_at=now,
                identity_verification_status=IdentityVerificationStatus.NOT_REQUIRED,
                status=VerifiedCallerIdentityStatus.ACTIVE,
                consent_version="v1",
                consent_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
        user_id = user.id

    timestamp = str(int(now.timestamp()))

    def event(leg: str) -> tuple[bytes, dict[str, str]]:
        state = base64.b64encode(
            json.dumps(
                {"user_id": str(user_id), "webrtc_call_control_id": "webrtc"}
            ).encode()
        ).decode()
        body = json.dumps(
            {
                "data": {
                    "event_type": "call.hangup",
                    "payload": {
                        "call_leg_id": f"{suffix}-{leg}",
                        "client_state": state,
                        "to": "+2348099999999",
                        "start_time": now.isoformat(),
                        "end_time": (now + timedelta(seconds=60)).isoformat(),
                    },
                }
            },
            separators=(",", ":"),
        ).encode()
        signature = base64.b64encode(
            private_key.sign(timestamp.encode() + b"|" + body)
        ).decode()
        return body, {
            "telnyx-timestamp": timestamp,
            "telnyx-signature-ed25519": signature,
        }

    barrier = Barrier(2)

    def process(leg: str) -> bool:
        body, headers = event(leg)
        with Session(engine) as session:
            barrier.wait()
            return service.process_webhook(session, body, headers)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(process, ("one", "two")))

    assert results == [True, True]
    with Session(engine) as session:
        package = session.exec(select(Package).where(Package.user_id == user_id)).one()
        charges = sorted(
            log.pstn_minutes_charged
            for log in session.exec(
                select(CallLog).where(CallLog.user_id == user_id)
            ).all()
        )
        user = session.get(User, user_id)
        assert user is not None
        eligibility = service.eligibility(session, user, "+2348099999999")
        assert package.pstn_minutes_remaining == Decimal("0.00")
        assert charges == [Decimal("0.00"), Decimal("0.50")]
        assert eligibility["reason"] == "pstn_balance_exhausted"
