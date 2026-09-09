import base64
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient
from sqlmodel import select

from app.auth.models import PricingTier, User
from app.auth.routes import request_otp, verify_otp
from app.auth.schemas import OTPRequest, OTPVerifyRequest
from app.main import create_app
from app.packages.models import Package, PackageSource, PackageStatus
from app.voice.models import (
    CallLog,
    IdentityVerificationStatus,
    PhoneVerificationProviderName,
    PhoneVerificationStatus,
    VerifiedCallerIdentity,
    VerifiedCallerIdentityStatus,
    VoiceCredential,
)
from app.voice.providers import ProvisionedVoiceCredential, VoiceAccessToken


@dataclass
class FakeVoiceProvider:
    now: datetime

    def __post_init__(self) -> None:
        self.credentials: list[str] = []
        self.tokens: list[str] = []
        self.initiated: list[dict[str, object]] = []
        self.bridged: list[tuple[str, str]] = []

    def create_credential(self, user_id: str) -> ProvisionedVoiceCredential:
        self.credentials.append(user_id)
        suffix = len(self.credentials)
        return ProvisionedVoiceCredential(f"cred-{suffix}", f"gencred{suffix}")

    def issue_token(self, credential_id: str) -> VoiceAccessToken:
        self.tokens.append(credential_id)
        return VoiceAccessToken("telnyx-jwt", self.now + timedelta(minutes=15))

    def initiate_call(self, **kwargs: object) -> None:
        self.initiated.append(kwargs)

    def bridge_call(self, call_control_id: str, peer_call_control_id: str) -> None:
        self.bridged.append((call_control_id, peer_call_control_id))


def _api_and_signer(
    settings, redis_client, providers, scheduler, session_factory, clock
):
    private_key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(
        private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()
    configured = settings.model_copy(update={"telnyx_public_key": public_key})
    voice = FakeVoiceProvider(clock())
    api = create_app(
        settings=configured,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
        voice_provider=voice,
    )
    return api, voice, private_key


def _authenticated(api, phone_number: str = "08012345678") -> tuple[TestClient, UUID]:
    request = SimpleNamespace(app=api)
    request_otp(OTPRequest(phone_number=phone_number), request)
    auth = verify_otp(
        OTPVerifyRequest(phone_number=phone_number, otp="123456", platform="android"),
        request,
    )
    return (
        TestClient(
            api,
            headers={"Authorization": f"Bearer {auth.access_token}"},
            raise_server_exceptions=False,
        ),
        auth.user.id,
    )


def _provision_credential(
    session_factory, voice, user_id: UUID, clock
) -> str:
    """Seed the SIP credential /voice/token used to provision (US-30, 04D).

    The endpoint is retired, but the call-event handlers that read these rows
    are retained for chunk 15, so the tests provision directly instead.
    """
    provisioned = voice.create_credential(str(user_id))
    with session_factory() as session:
        session.add(
            VoiceCredential(
                user_id=user_id,
                telnyx_telephony_credential_id=provisioned.credential_id,
                sip_username=provisioned.sip_username,
                created_at=clock(),
            )
        )
        session.commit()
    return provisioned.sip_username


def _active_package(session_factory, user_id: UUID, minutes: str) -> None:
    with session_factory() as session:
        tier = PricingTier(
            name=f"Voice-{user_id}",
            usd_reference_price=Decimal("100"),
            data_gb=5,
            pstn_minutes=10,
            wholesale_usd_price=Decimal("80"),
            ngn_price=Decimal("100000"),
        )
        session.add(tier)
        session.flush()
        session.add(
            Package(
                user_id=user_id,
                pricing_tier_id=tier.id,
                source=PackageSource.RETAIL,
                status=PackageStatus.ACTIVE,
                data_gb_total=5,
                data_gb_remaining=Decimal("5"),
                pstn_minutes_total=10,
                pstn_minutes_remaining=Decimal(minutes),
                purchased_at=datetime.now(timezone.utc),
            )
        )
        session.commit()


def _activate_caller_identity(
    session_factory, user_id: UUID, phone_number: str = "+2348012345678"
) -> None:
    with session_factory() as session:
        now = datetime.now(timezone.utc)
        session.add(
            VerifiedCallerIdentity(
                user_id=user_id,
                phone_number=phone_number,
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


def _signed_headers(private_key, body: bytes, now: datetime) -> dict[str, str]:
    timestamp = str(int(now.timestamp()))
    signature = private_key.sign(timestamp.encode() + b"|" + body)
    return {
        "telnyx-timestamp": timestamp,
        "telnyx-signature-ed25519": base64.b64encode(signature).decode(),
        "content-type": "application/json",
    }


def _hangup(user_id: UUID, call_leg_id: str, seconds: int) -> bytes:
    started = datetime(2026, 7, 13, tzinfo=timezone.utc)
    state = base64.b64encode(
        json.dumps(
            {"user_id": str(user_id), "webrtc_call_control_id": "webrtc-leg"}
        ).encode()
    ).decode()
    return json.dumps(
        {
            "data": {
                "event_type": "call.hangup",
                "payload": {
                    "call_leg_id": call_leg_id,
                    "client_state": state,
                    "to": "+2348099999999",
                    "start_time": started.isoformat(),
                    "end_time": (started + timedelta(seconds=seconds)).isoformat(),
                },
            }
        },
        separators=(",", ":"),
    ).encode()


def _app_hangup(from_username: str, to_username: str) -> bytes:
    started = datetime(2026, 7, 13, tzinfo=timezone.utc)
    return json.dumps(
        {
            "data": {
                "event_type": "call.hangup",
                "payload": {
                    "call_leg_id": "app-leg-1",
                    "from": f"sip:{from_username}@sip.telnyx.com",
                    "to": f"{to_username}@sip.telnyx.com",
                    "start_time": started.isoformat(),
                    "end_time": (started + timedelta(seconds=45)).isoformat(),
                },
            }
        },
        separators=(",", ":"),
    ).encode()


def test_app_to_app_is_free_for_unverified_user_with_zero_balance(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-14.1/8: unverified users remain eligible for free DamDam calls."""
    api, voice, _ = _api_and_signer(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    caller, _ = _authenticated(api)
    _, callee_id = _authenticated(api, "08098765432")

    response = caller.get(
        "/v1/voice/eligibility", params={"phone_number": "08098765432"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "allowed": True,
        "call_type": "app_to_app",
        "destination": None,
        "reason": None,
        "pstn_minutes_remaining": 0.0,
    }
    assert callee_id is not None
    assert voice.credentials == []


def test_unsigned_stale_and_malformed_telnyx_webhooks_are_rejected(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-14.7: billing never trusts unsigned, stale, or malformed callbacks."""
    api, _, signer = _api_and_signer(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client = TestClient(api, raise_server_exceptions=False)
    body = b'{"data":{"event_type":"call.hangup","payload":{}}}'
    assert (
        client.post("/v1/webhooks/telnyx/call-events", content=body).status_code == 401
    )
    stale = _signed_headers(signer, body, clock() - timedelta(minutes=6))
    assert (
        client.post(
            "/v1/webhooks/telnyx/call-events", content=body, headers=stale
        ).status_code
        == 401
    )
    malformed = b"not-json"
    headers = _signed_headers(signer, malformed, clock())
    response = client.post(
        "/v1/webhooks/telnyx/call-events", content=malformed, headers=headers
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_webhook_payload"


def test_webhook_resigned_with_wrong_key_is_rejected(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-14.7: a well-formed, freshly-timestamped payload signed by a key
    other than the one configured for this Telnyx account must not pass
    verification just because it is syntactically valid base64/Ed25519."""
    api, _, _signer = _api_and_signer(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client = TestClient(api, raise_server_exceptions=False)
    attacker_key = Ed25519PrivateKey.generate()
    body = _hangup(uuid4(), "leg-forged", 60)
    headers = _signed_headers(attacker_key, body, clock())

    response = client.post(
        "/v1/webhooks/telnyx/call-events", content=body, headers=headers
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_webhook_signature"


def test_unverified_credentialed_user_pstn_dial_is_blocked_at_webhook_layer(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-14.1/4/7: a user can hold a VoiceCredential (provisioned as the
    callee of someone else's app-to-app call) without ever being CLI
    verified. If a call.initiated event later arrives claiming to originate
    from that user's SIP identity toward a PSTN number, the re-check inside
    _handle_initiated must block the dial — not just the /voice/token
    endpoint — so an unverified phone_number is never handed to the
    provider as a caller_id."""
    api, voice, signer = _api_and_signer(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    caller, _ = _authenticated(api, "08012345678")
    _, unverified_id = _authenticated(api, "08098765432")
    with session_factory() as session:
        unverified = session.get(User, unverified_id)
        assert unverified is not None
        unverified.verified_cli = False
        session.add(unverified)
        session.commit()

    sip_username = _provision_credential(
        session_factory, voice, unverified_id, clock
    )

    initiated = json.dumps(
        {
            "data": {
                "event_type": "call.initiated",
                "payload": {
                    "from": f"sip:{sip_username}@sip.telnyx.com",
                    "to": "+2348011119999",
                    "call_control_id": "unverified-attempt",
                },
            }
        },
        separators=(",", ":"),
    ).encode()

    response = caller.post(
        "/v1/webhooks/telnyx/call-events",
        content=initiated,
        headers=_signed_headers(signer, initiated, clock()),
    )

    assert response.json() == {"processed": False}
    assert voice.initiated == []


def test_pstn_rejection_at_webhook_layer_writes_audit_trail_call_log(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """A rejected PSTN dial attempt must leave an auditable CallLog record,
    not just a silent {"processed": False} -- this is the actual gap the
    CLI-hardening pass fixes (previously nothing was written on rejection
    at the webhook layer, only at the /voice/token layer)."""
    api, voice, signer = _api_and_signer(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    caller, caller_id = _authenticated(api, "08012345678")
    # A VoiceCredential is normally provisioned lazily on /voice/token; add
    # it directly here so the webhook's `from` lookup resolves to this user
    # without going through a token request first.
    with session_factory() as session:
        session.add(
            VoiceCredential(
                user_id=caller_id,
                telnyx_telephony_credential_id="cred-caller",
                sip_username="callercred",
                created_at=clock(),
            )
        )
        session.commit()

    not_verified = json.dumps(
        {
            "data": {
                "event_type": "call.initiated",
                "payload": {
                    "from": "sip:callercred@sip.telnyx.com",
                    "to": "+2348011119999",
                    "call_control_id": "rejected-not-verified",
                },
            }
        },
        separators=(",", ":"),
    ).encode()
    response = caller.post(
        "/v1/webhooks/telnyx/call-events",
        content=not_verified,
        headers=_signed_headers(signer, not_verified, clock()),
    )
    assert response.json() == {"processed": False}
    assert voice.initiated == []
    with session_factory() as session:
        log = session.exec(
            select(CallLog).where(CallLog.telnyx_call_leg_id == "rejected-not-verified")
        ).one()
        assert log.failure_code == "cli_not_verified"
        assert log.pstn_minutes_charged == Decimal("0.00")
        assert log.to_number == "+2348011119999"

    # Now activate the CLI but leave the balance at zero -- rejection
    # switches to the other branch, still auditable.
    _activate_caller_identity(session_factory, caller_id, "+2348012345678")
    insufficient_balance = json.dumps(
        {
            "data": {
                "event_type": "call.initiated",
                "payload": {
                    "from": "sip:callercred@sip.telnyx.com",
                    "to": "+2348011119999",
                    "call_control_id": "rejected-no-balance",
                },
            }
        },
        separators=(",", ":"),
    ).encode()
    response = caller.post(
        "/v1/webhooks/telnyx/call-events",
        content=insufficient_balance,
        headers=_signed_headers(signer, insufficient_balance, clock()),
    )
    assert response.json() == {"processed": False}
    assert voice.initiated == []
    with session_factory() as session:
        log = session.exec(
            select(CallLog).where(CallLog.telnyx_call_leg_id == "rejected-no-balance")
        ).one()
        assert log.failure_code == "insufficient_balance"


def test_app_to_app_hangup_writes_free_history_without_balance(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-14.8/9: a signed direct SIP hangup is recorded as free history."""
    api, voice, signer = _api_and_signer(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    caller, caller_id = _authenticated(api)
    _, callee_id = _authenticated(api, "08098765432")
    # Both legs were provisioned by the retired /voice/token path; seed them
    # in the order it used -- the callee during eligibility, then the caller --
    # so the SIP usernames in the fixtures below still identify the same users.
    _provision_credential(session_factory, voice, callee_id, clock)
    _provision_credential(session_factory, voice, caller_id, clock)
    initiated = json.dumps(
        {
            "data": {
                "event_type": "call.initiated",
                "payload": {
                    "from": "sip:gencred2@sip.telnyx.com",
                    "to": "sip:gencred1@sip.telnyx.com",
                    "call_control_id": "app-control",
                },
            }
        },
        separators=(",", ":"),
    ).encode()
    response = caller.post(
        "/v1/webhooks/telnyx/call-events",
        content=initiated,
        headers=_signed_headers(signer, initiated, clock()),
    )
    assert response.json() == {"processed": False}
    assert voice.initiated == []

    body = _app_hangup("gencred2", "gencred1")
    response = caller.post(
        "/v1/webhooks/telnyx/call-events",
        content=body,
        headers=_signed_headers(signer, body, clock()),
    )
    assert response.json() == {"processed": True}
    item = caller.get("/v1/me/calls").json()["calls"][0]
    assert item["call_type"] == "app_to_app"
    assert item["pstn_minutes_charged"] == 0.0
    assert item["to_number"] == "+2348098765432"


def test_signed_call_control_events_set_verified_cli_and_bridge(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-14.3/4: PSTN leg uses verified CLI and bridges to the WebRTC leg."""
    api, voice, signer = _api_and_signer(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)
    _active_package(session_factory, user_id, "2.00")
    _activate_caller_identity(session_factory, user_id)
    _provision_credential(session_factory, voice, user_id, clock)
    initiated = json.dumps(
        {
            "data": {
                "event_type": "call.initiated",
                "payload": {
                    "from": "sip:gencred1@sip.telnyx.com",
                    "to": "+2348099999999",
                    "call_control_id": "webrtc-control",
                },
            }
        },
        separators=(",", ":"),
    ).encode()
    response = client.post(
        "/v1/webhooks/telnyx/call-events",
        content=initiated,
        headers=_signed_headers(signer, initiated, clock()),
    )
    assert response.json() == {"processed": True}
    with session_factory() as session:
        identity = session.exec(
            select(VerifiedCallerIdentity).where(
                VerifiedCallerIdentity.user_id == user_id
            )
        ).one()
    assert voice.initiated == [
        {
            "webrtc_call_control_id": "webrtc-control",
            "user_id": str(user_id),
            "caller_id": "+2348012345678",
            "to_number": "+2348099999999",
            "time_limit_seconds": 120,
            "verified_caller_identity_id": str(identity.id),
            "idempotency_key": None,
        }
    ]

    state = base64.b64encode(
        json.dumps(
            {"user_id": str(user_id), "webrtc_call_control_id": "webrtc-control"}
        ).encode()
    ).decode()
    answered = json.dumps(
        {
            "data": {
                "event_type": "call.answered",
                "payload": {
                    "call_control_id": "pstn-control",
                    "client_state": state,
                },
            }
        },
        separators=(",", ":"),
    ).encode()
    response = client.post(
        "/v1/webhooks/telnyx/call-events",
        content=answered,
        headers=_signed_headers(signer, answered, clock()),
    )
    assert response.json() == {"processed": True}
    assert voice.bridged == [("pstn-control", "webrtc-control")]


def test_hangup_is_idempotent_deducts_duration_and_history_is_limited(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-14.7/9: signed hangup bills once and history defaults to last 20."""
    api, _, signer = _api_and_signer(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)
    _active_package(session_factory, user_id, "3.00")
    body = _hangup(user_id, "leg-idempotent", 90)
    headers = _signed_headers(signer, body, clock())

    first = client.post(
        "/v1/webhooks/telnyx/call-events", content=body, headers=headers
    )
    duplicate = client.post(
        "/v1/webhooks/telnyx/call-events", content=body, headers=headers
    )

    assert first.json() == {"processed": True}
    assert duplicate.json() == {"processed": False}
    with session_factory() as session:
        package = session.exec(select(Package).where(Package.user_id == user_id)).one()
        logs = session.exec(select(CallLog)).all()
        assert package.pstn_minutes_remaining == Decimal("1.50")
        assert len(logs) == 1
        assert logs[0].pstn_minutes_charged == Decimal("1.50")
    history = client.get("/v1/me/calls")
    assert history.status_code == 200
    assert history.json()["calls"][0]["duration_seconds"] == 90


def test_rapid_hangups_at_zero_are_capped_without_negative_balance(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-14.7: rapid distinct calls serialize at zero; no charge goes negative."""
    api, _, signer = _api_and_signer(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)
    _active_package(session_factory, user_id, "0.50")
    _activate_caller_identity(session_factory, user_id)

    for leg in ("rapid-leg-1", "rapid-leg-2"):
        body = _hangup(user_id, leg, 60)
        response = client.post(
            "/v1/webhooks/telnyx/call-events",
            content=body,
            headers=_signed_headers(signer, body, clock()),
        )
        assert response.json() == {"processed": True}

    with session_factory() as session:
        package = session.exec(select(Package).where(Package.user_id == user_id)).one()
        charges = sorted(
            log.pstn_minutes_charged for log in session.exec(select(CallLog)).all()
        )
        assert package.pstn_minutes_remaining == Decimal("0.00")
        assert charges == [Decimal("0.00"), Decimal("0.50")]
    eligibility = client.get(
        "/v1/voice/eligibility", params={"phone_number": "08099999999"}
    )
    assert eligibility.json()["allowed"] is False
    assert eligibility.json()["reason"] == "pstn_balance_exhausted"


def test_pstn_billing_hits_the_package_matching_the_users_destination_not_the_newest(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """A user can now hold an ACTIVE package per destination at once
    (data-model.md §6.32). A call must bill against the package matching
    the user's own destination_country, not whichever package happens to
    have been purchased most recently -- the KE package here is bought
    *after* the SA one specifically to prove this isn't just picking the
    newest row."""
    api, _, signer = _api_and_signer(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)
    with session_factory() as session:
        sa_tier = PricingTier(
            name=f"SA-{user_id}",
            usd_reference_price=Decimal("100"),
            data_gb=5,
            pstn_minutes=10,
            wholesale_usd_price=Decimal("80"),
            ngn_price=Decimal("100000"),
        )
        ke_tier = PricingTier(
            name=f"KE-{user_id}",
            usd_reference_price=Decimal("100"),
            data_gb=5,
            pstn_minutes=10,
            wholesale_usd_price=Decimal("80"),
            ngn_price=Decimal("100000"),
        )
        session.add(sa_tier)
        session.add(ke_tier)
        session.flush()
        session.add(
            Package(
                user_id=user_id,
                pricing_tier_id=sa_tier.id,
                source=PackageSource.RETAIL,
                status=PackageStatus.ACTIVE,
                data_gb_total=5,
                data_gb_remaining=Decimal("5"),
                pstn_minutes_total=10,
                pstn_minutes_remaining=Decimal("3.00"),
                purchased_at=clock() - timedelta(days=1),
                destination_country="SA",
            )
        )
        session.add(
            Package(
                user_id=user_id,
                pricing_tier_id=ke_tier.id,
                source=PackageSource.RETAIL,
                status=PackageStatus.ACTIVE,
                data_gb_total=5,
                data_gb_remaining=Decimal("5"),
                pstn_minutes_total=10,
                pstn_minutes_remaining=Decimal("9.00"),
                purchased_at=clock(),  # purchased *after* the SA package
                destination_country="KE",
            )
        )
        session.commit()

    body = _hangup(user_id, "leg-destination-scoped", 90)
    response = client.post(
        "/v1/webhooks/telnyx/call-events",
        content=body,
        headers=_signed_headers(signer, body, clock()),
    )

    assert response.json() == {"processed": True}
    with session_factory() as session:
        sa_package = session.exec(
            select(Package).where(Package.destination_country == "SA")
        ).one()
        ke_package = session.exec(
            select(Package).where(Package.destination_country == "KE")
        ).one()
        # 90 seconds = 1.50 minutes charged against the SA package's 3.00
        # remaining -- the user's own destination_country defaults to SA
        # (app/auth/models.py), so this is the correct package.
        assert sa_package.pstn_minutes_remaining == Decimal("1.50")
        # The KE package -- more recently purchased, and would have been
        # picked by the old "most recent ACTIVE package" logic -- is
        # completely untouched.
        assert ke_package.pstn_minutes_remaining == Decimal("9.00")
