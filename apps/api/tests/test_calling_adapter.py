"""The Telnyx calling adapter — signature handling and outcome classification.

Two things are tested here and one deliberately is not.

**Tested:** that an event is authenticated over the raw body before it is parsed,
that a stale or wrongly signed event is refused, and that a lost response is
reported as *unknown* rather than as a failure. That last one is the difference
between reconciling one call and dialling a second.

**Not tested, and cannot be:** whether Telnyx actually behaves this way.
`AGENTS.md` is explicit that a mock passing itself is not evidence of external
compatibility. These are tests of our adapter's logic against a stubbed
transport; blockers B1-B5 remain open and no account call has been made.
"""

import base64
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.calling.contract import (
    CallingCapability,
    CallingError,
    CallOutcomeUnknown,
    RouteDisabled,
)
from app.calling.lifecycle import redacted
from app.calling.telnyx import (
    DisabledCallingAdapter,
    TelnyxCallingAdapter,
    _decode_client_state,
)
from app.config import Settings

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def signing_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture
def public_key_b64(signing_key) -> str:
    raw = signing_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(raw).decode()


@pytest.fixture
def settings(public_key_b64) -> Settings:
    return Settings(
        app_env="test",
        database_url="sqlite://",
        redis_url="redis://unused",
        jwt_secret="test-secret-at-least-32-characters-long",
        otp_provider_primary="termii",
        otp_provider_secondary="twilio",
        telnyx_api_key="test-key",
        telnyx_connection_id="conn-1",
        telnyx_public_key=public_key_b64,
        telnyx_webhook_tolerance_seconds=300,
        calling_live_routes_enabled=True,
        calling_containment_evidence_reference="docs/.../B1-account-test.md",
        calling_outbound_identity_e164="+2347000000001",
        calling_supported_destination_countries=["NG"],
    )


@pytest.fixture
def adapter(settings) -> TelnyxCallingAdapter:
    return TelnyxCallingAdapter(settings, clock=Clock())


def _signed(signing_key, body: dict, *, at: datetime = NOW) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    timestamp = str(int(at.timestamp()))
    signature = signing_key.sign(timestamp.encode() + b"|" + raw)
    return raw, {
        "telnyx-timestamp": timestamp,
        "telnyx-signature-ed25519": base64.b64encode(signature).decode(),
    }


def _envelope(event_id: str = "evt-1", event_type: str = "call.initiated") -> dict:
    return {
        "data": {
            "id": event_id,
            "event_type": event_type,
            "occurred_at": "2026-09-12T12:00:00Z",
            "payload": {
                "call_control_id": "ctrl-1",
                "call_leg_id": "leg-1",
                "call_session_id": "session-1",
                "connection_id": "conn-1",
                "to": "+2348031234567",
                "client_state": base64.b64encode(
                    json.dumps({"attempt_id": "abc"}).encode()
                ).decode(),
            },
        }
    }


class TestEventAuthentication:
    def test_a_valid_signature_is_parsed(self, adapter, signing_key):
        body, headers = _signed(signing_key, _envelope())

        event = adapter.parse_event(body, headers)

        assert event.event_id == "evt-1"
        assert event.event_type == "call.initiated"
        assert event.leg.control_id == "ctrl-1"
        assert event.claimed_destination == "+2348031234567"
        assert event.client_state == {"attempt_id": "abc"}

    def test_a_wrong_signature_is_refused(self, adapter, signing_key):
        body, headers = _signed(signing_key, _envelope())
        headers["telnyx-signature-ed25519"] = base64.b64encode(b"x" * 64).decode()

        with pytest.raises(CallingError) as excinfo:
            adapter.parse_event(body, headers)
        assert excinfo.value.code == "invalid_webhook_signature"

    def test_a_modified_body_is_refused(self, adapter, signing_key):
        body, headers = _signed(signing_key, _envelope())

        with pytest.raises(CallingError):
            adapter.parse_event(body + b" ", headers)

    def test_a_stale_timestamp_is_refused(self, adapter, signing_key):
        body, headers = _signed(
            signing_key, _envelope(), at=NOW - timedelta(hours=1)
        )

        with pytest.raises(CallingError) as excinfo:
            adapter.parse_event(body, headers)
        assert excinfo.value.code == "invalid_webhook_signature"

    def test_an_unconfigured_public_key_rejects_rather_than_accepts(
        self, settings, signing_key
    ):
        settings = settings.model_copy(update={"telnyx_public_key": ""})
        adapter = TelnyxCallingAdapter(settings, clock=Clock())
        body, headers = _signed(signing_key, _envelope())

        with pytest.raises(CallingError) as excinfo:
            adapter.parse_event(body, headers)
        # A verifier that passes when it has nothing to verify against is worse
        # than no verifier, because it looks like one.
        assert excinfo.value.code == "webhook_verification_unconfigured"

    def test_a_replay_inside_the_window_still_verifies(self, adapter, signing_key):
        """Documents why the durable inbox exists.

        The signature is valid and the timestamp is fresh on a replay, so this
        layer cannot tell the difference. `call_events`' unique provider event id
        is what makes the event single-use (V01 review finding 3).
        """
        body, headers = _signed(signing_key, _envelope())

        first = adapter.parse_event(body, headers)
        second = adapter.parse_event(body, headers)

        assert first.event_id == second.event_id


class TestClientStateIsTolerant:
    @pytest.mark.parametrize(
        "value", [None, "", "not-base64!!", base64.b64encode(b"[]").decode(), 42]
    )
    def test_rubbish_decodes_to_nothing_rather_than_raising(self, value):
        # A correlation hint with no integrity of its own. A corrupt one is a
        # missed hint, not an error, and it never authorizes anything.
        assert _decode_client_state(value) == {}


class TestOutcomeClassification:
    def _transport(self, adapter, monkeypatch, behaviour):
        monkeypatch.setattr(httpx, "request", behaviour)

    def test_a_timeout_is_unknown_not_a_failure(self, adapter, monkeypatch):
        def timeout(*args, **kwargs):
            raise httpx.ReadTimeout("too slow")

        monkeypatch.setattr(httpx, "request", timeout)

        with pytest.raises(CallOutcomeUnknown):
            adapter.create_destination_leg(
                operation_reference=__import__("uuid").uuid4(),
                destination="+2348031234567",
                identity="+2347000000001",
                time_limit_seconds=600,
                correlation="abc",
            )

    def test_a_server_error_is_unknown(self, adapter, monkeypatch):
        # A gateway that failed *after* accepting the call has still created the
        # leg. Treating 5xx as a refusal is how the retry dials twice.
        monkeypatch.setattr(
            httpx,
            "request",
            lambda *a, **k: httpx.Response(502, request=httpx.Request("POST", "http://x")),
        )

        with pytest.raises(CallOutcomeUnknown):
            adapter.create_destination_leg(
                operation_reference=__import__("uuid").uuid4(),
                destination="+2348031234567",
                identity="+2347000000001",
                time_limit_seconds=600,
                correlation="abc",
            )

    def test_a_client_error_is_a_definite_refusal(self, adapter, monkeypatch):
        monkeypatch.setattr(
            httpx,
            "request",
            lambda *a, **k: httpx.Response(422, request=httpx.Request("POST", "http://x")),
        )

        with pytest.raises(CallingError) as excinfo:
            adapter.create_destination_leg(
                operation_reference=__import__("uuid").uuid4(),
                destination="+2348031234567",
                identity="+2347000000001",
                time_limit_seconds=600,
                correlation="abc",
            )
        assert excinfo.value.code == "provider_rejected"

    def test_the_time_limit_is_clamped_to_the_documented_maximum(
        self, adapter, monkeypatch
    ):
        sent: dict = {}

        def capture(method, url, **kwargs):
            sent.update(kwargs.get("json") or {})
            return httpx.Response(
                200,
                json={"data": {"call_control_id": "ctrl-9"}},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx, "request", capture)
        adapter.create_destination_leg(
            operation_reference=__import__("uuid").uuid4(),
            destination="+2348031234567",
            identity="+2347000000001",
            time_limit_seconds=999999,
            correlation="abc",
        )

        assert sent["time_limit_secs"] == 14400

    def test_reconciliation_admits_it_cannot_answer(self, adapter):
        # Telnyx documents no lookup by `command_id`. `None` routes the
        # operation to held-for-review, which is a human deciding rather than a
        # worker dialling again.
        assert adapter.reconcile_operation(__import__("uuid").uuid4()) is None


class TestCapabilities:
    def test_emergency_containment_is_never_claimed(self, adapter):
        capabilities = adapter.capabilities()
        assert not capabilities.supports(CallingCapability.EMERGENCY_CONTAINMENT)
        # And it says why, rather than being silently absent.
        reason = capabilities.undocumented[
            CallingCapability.EMERGENCY_CONTAINMENT.value
        ]
        assert "B1" in reason

    def test_capability_claims_carry_their_evidence_date(self, adapter):
        capabilities = adapter.capabilities()
        assert capabilities.verified_at == datetime(2026, 9, 9, tzinfo=timezone.utc)
        assert "CAPABILITY-MATRIX" in (capabilities.evidence_reference or "")

    def test_requiring_an_unverified_capability_raises(self, adapter):
        with pytest.raises(CallingError):
            adapter.capabilities().require(
                CallingCapability.EMERGENCY_CONTAINMENT
            )


class TestRouteGating:
    def test_missing_containment_evidence_disables_the_route(self, settings):
        # `Settings` refuses this combination at startup; this covers an adapter
        # constructed directly, which a worker or a test could still do.
        weakened = settings.model_copy(
            update={"calling_containment_evidence_reference": ""}
        )
        adapter = TelnyxCallingAdapter(weakened, clock=Clock())

        assert adapter.live is False
        with pytest.raises(RouteDisabled):
            adapter.create_destination_leg(
                operation_reference=__import__("uuid").uuid4(),
                destination="+2348031234567",
                identity="+2347000000001",
                time_limit_seconds=600,
                correlation="abc",
            )

    def test_hangup_still_works_on_a_disabled_route(self, settings, monkeypatch):
        """Disabling new calling must not disable termination."""
        weakened = settings.model_copy(
            update={"calling_live_routes_enabled": False}
        )
        adapter = TelnyxCallingAdapter(weakened, clock=Clock())
        calls: list[str] = []

        def capture(method, url, **kwargs):
            calls.append(url)
            return httpx.Response(200, json={}, request=httpx.Request("POST", url))

        monkeypatch.setattr(httpx, "request", capture)
        adapter.hangup(
            operation_reference=__import__("uuid").uuid4(), control_id="ctrl-1"
        )

        assert calls and "hangup" in calls[0]


class TestDisabledAdapter:
    def test_it_advertises_nothing_and_refuses_everything(self):
        adapter = DisabledCallingAdapter()
        assert adapter.capabilities().supported == frozenset()
        with pytest.raises(RouteDisabled):
            adapter.parse_event(b"{}", {})


class TestRedaction:
    def test_credential_shaped_fields_never_reach_a_log(self):
        payload = {"token": "jwt-value", "sip_password": "hunter2", "to": "+234803"}
        assert redacted(payload) == {
            "token": "<redacted>",
            "sip_password": "<redacted>",
            "to": "+234803",
        }
