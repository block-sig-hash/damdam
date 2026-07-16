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
from app.voice.models import CallLog, VoiceCredential
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
    caller, caller_id = _authenticated(api)
    _, callee_id = _authenticated(api, "08098765432")
    with session_factory() as session:
        user = session.get(User, caller_id)
        assert user is not None
        user.verified_cli = False
        session.add(user)
        session.commit()

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


def test_pstn_token_requires_verified_cli_and_positive_balance(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-14.1/4/7: PSTN is gated by CLI ownership and remaining minutes."""
    api, voice, _ = _api_and_signer(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)
    with session_factory() as session:
        user = session.get(User, user_id)
        assert user is not None
        user.verified_cli = False
        session.add(user)
        session.commit()
    assert (
        client.post("/v1/voice/token", json={"to_number": "08099999999"}).status_code
        == 403
    )
    with session_factory() as session:
        user = session.get(User, user_id)
        assert user is not None
        user.verified_cli = True
        session.add(user)
        session.commit()
    assert (
        client.post("/v1/voice/token", json={"to_number": "08099999999"}).status_code
        == 409
    )
    _active_package(session_factory, user_id, "2.00")

    response = client.post("/v1/voice/token", json={"to_number": "08099999999"})

    assert response.status_code == 200
    assert response.json()["call_type"] == "pstn"
    assert response.json()["destination"] == "+2348099999999"
    assert response.json()["token"] == "telnyx-jwt"
    assert voice.tokens == ["cred-1"]


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

    # Provisions the callee's (unverified user's) VoiceCredential as a side
    # effect of the caller's free app-to-app token request.
    token_response = caller.post(
        "/v1/voice/token", json={"to_number": "08098765432"}
    )
    assert token_response.status_code == 200
    with session_factory() as session:
        credential = session.exec(
            select(VoiceCredential).where(VoiceCredential.user_id == unverified_id)
        ).first()
        assert credential is not None
        sip_username = credential.sip_username

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


def test_app_to_app_hangup_writes_free_history_without_balance(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-14.8/9: a signed direct SIP hangup is recorded as free history."""
    api, voice, signer = _api_and_signer(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    caller, _ = _authenticated(api)
    _, _ = _authenticated(api, "08098765432")
    token = caller.post("/v1/voice/token", json={"to_number": "08098765432"})
    assert token.status_code == 200
    # Target is provisioned during eligibility; caller during token issuance.
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
    assert (
        client.post("/v1/voice/token", json={"to_number": "08099999999"}).status_code
        == 200
    )
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
    assert voice.initiated == [
        {
            "webrtc_call_control_id": "webrtc-control",
            "user_id": str(user_id),
            "caller_id": "+2348012345678",
            "to_number": "+2348099999999",
            "time_limit_seconds": 120,
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
