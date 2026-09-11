"""US-35 chunk 15 — the documented Telnyx contract, and our adapter against it.

**EVERY TEST IN THIS FILE IS A SIMULATION.** They exercise our own request
construction, response parsing and status mapping against payloads transcribed
from Telnyx's published OpenAPI source and prose documentation, re-verified
2026-09-10. They do not call Telnyx. A green run here is not evidence of Telnyx
coverage, pricing, VoLTE readiness or handset behaviour, and **D1 remains OPEN**
regardless of the result.

Sources for every shape asserted here are recorded in
`docs/implementation/telnyx/API-CONTRACTS.md`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.connectivity.contract import (
    AdapterCapabilities,
    AdapterChannel,
    Capability,
    CapabilityNotAvailable,
    ConnectivityError,
    ConnectivityOutcomeUnknown,
    ProviderLineState,
)
from app.connectivity.telnyx import (
    TelnyxConnectivityAdapter,
    TelnyxResponse,
    TelnyxTransportTimeout,
    build_transport,
)
from app.connectivity.telnyx_contract import (
    ACTIVATION_CODE_PATH,
    ActivationCode,
    ContractViolation,
    DataAmount,
    ESimPurchaseRequest,
    ESimPurchaseResponse,
    SimCard,
    SimCardAction,
    SimCardActionStatus,
    SimCardStatus,
    operation_tag,
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
OPERATION = UUID("11111111-1111-4111-8111-111111111111")


class ScriptedTransport:
    """Queues responses and records what was actually sent.

    Recording matters as much as responding: the tests that prove a purchase is
    never retried and that reconciliation does not filter by status are
    assertions about the *request*, and nothing else can see it.
    """

    def __init__(self) -> None:
        self.queue: list[TelnyxResponse | TelnyxTransportTimeout] = []
        self.calls: list[
            tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]
        ] = []

    def push(self, status_code: int, payload: dict[str, Any]) -> None:
        self.queue.append(TelnyxResponse(status_code=status_code, payload=payload))

    def push_timeout(self) -> None:
        self.queue.append(TelnyxTransportTimeout("read timed out"))

    def __call__(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None,
        params: dict[str, Any] | None,
    ) -> TelnyxResponse:
        self.calls.append((method, url, body, params))
        if not self.queue:
            raise AssertionError(f"unscripted call: {method} {url}")
        response = self.queue.pop(0)
        if isinstance(response, TelnyxTransportTimeout):
            raise response
        return response


def sim_payload(**overrides: Any) -> dict[str, Any]:
    """A `SimpleSIMCard`, field for field from the published schema."""
    payload: dict[str, Any] = {
        "id": "6a09cdc3-8948-47f0-aa62-74ac943d6c58",
        "record_type": "sim_card",
        "status": {"value": "standby"},
        "type": "esim",
        "iccid": "89310410106543789301",
        "imsi": "081932214823362973",
        "msisdn": "+13109976224",
        "sim_card_group_id": "1a5c1e9c-0f4a-4e0e-9a1a-1b2c3d4e5f60",
        "tags": [operation_tag(OPERATION)],
        "current_billing_period_consumed_data": {"amount": "2049.0", "unit": "MB"},
        "actions_in_progress": False,
        "esim_installation_status": "released",
        "eid": None,
        "voice_enabled": False,
    }
    payload.update(overrides)
    return payload


def adapter(transport: ScriptedTransport, **kwargs: Any) -> TelnyxConnectivityAdapter:
    return TelnyxConnectivityAdapter(
        transport, clock=lambda: NOW, **kwargs
    )


# --- the request we send -----------------------------------------------------


def test_the_purchase_body_carries_no_idempotency_key() -> None:
    """Because Telnyx documents none.

    Inventing a plausible header is the failure the whole transcription exists
    to prevent: it would look like the double-purchase problem was solved when
    nothing had changed.
    """
    body = ESimPurchaseRequest(amount=2, operation_reference=OPERATION).to_body()
    assert set(body) == {"amount", "tags"}
    assert "idempotency_key" not in body
    assert body["tags"] == [f"damdam-op-{OPERATION}"]


def test_the_operation_tag_is_the_only_correlation_handle() -> None:
    transport = ScriptedTransport()
    transport.push(202, {"data": [sim_payload()], "errors": []})
    adapter(transport).provision(OPERATION, 1, {})
    _, url, body, _ = transport.calls[0]
    assert url.endswith("/actions/purchase/esims")
    assert body is not None
    assert body["tags"] == [f"damdam-op-{OPERATION}"]


def test_whitelabel_name_requires_the_whitelabel_product() -> None:
    with pytest.raises(ContractViolation):
        ESimPurchaseRequest(
            amount=1, operation_reference=OPERATION, whitelabel_name="DamDam"
        )


def test_a_status_outside_the_purchase_enum_is_refused() -> None:
    """The documented enum on purchase is enabled|disabled|standby.

    `registering` is a real SIM status and is *not* a valid initial status, and
    sending one is the kind of thing that produces a 422 nobody can explain
    three months later.
    """
    with pytest.raises(ContractViolation):
        ESimPurchaseRequest(
            amount=1,
            operation_reference=OPERATION,
            status=SimCardStatus.REGISTERING,
        )


# --- what we accept back -----------------------------------------------------


def test_an_undocumented_status_is_a_contract_violation() -> None:
    with pytest.raises(ContractViolation, match="undocumented SIM card status"):
        SimCard.from_payload(sim_payload(status={"value": "quantum"}))


def test_status_parses_as_both_an_object_and_a_bare_string() -> None:
    """Telnyx returns both shapes; guessing one breaks on the other."""
    assert SimCard.from_payload(sim_payload(status="enabled")).status is (
        SimCardStatus.ENABLED
    )
    assert SimCard.from_payload(
        sim_payload(status={"value": "enabled"})
    ).status is SimCardStatus.ENABLED


def test_the_prose_only_statuses_still_parse() -> None:
    """`unauthorized_imei`, `blocked` and `abolished` are absent from the
    OpenAPI enum and present in the prose lifecycle page.

    Two official sources disagree. Accepting only the OpenAPI set would make a
    real supplier response parse as a contract violation and stop a line's
    recovery dead.
    """
    for status in ("unauthorized_imei", "blocked", "abolished"):
        assert SimCard.from_payload(sim_payload(status=status)).status.value == status


def test_a_missing_id_is_refused() -> None:
    payload = sim_payload()
    del payload["id"]
    with pytest.raises(ContractViolation, match="no 'id'"):
        SimCard.from_payload(payload)


def test_tags_must_be_strings() -> None:
    with pytest.raises(ContractViolation, match="array of strings"):
        SimCard.from_payload(sim_payload(tags=[{"name": "x"}]))


def test_an_undocumented_installation_status_is_refused() -> None:
    """The documented enum is released|disabled and nothing else.

    A new value would mean Telnyx has started reporting something about
    installation that we have not read about, and reading it as "not released"
    would silently withhold a profile the customer paid for.
    """
    with pytest.raises(ContractViolation, match="esim_installation_status"):
        SimCard.from_payload(sim_payload(esim_installation_status="installed"))


def test_consumed_data_converts_to_exact_bytes() -> None:
    """Decimal, decimal prefixes, rounded down.

    `float("2048.1") * 1_000_000` is 2048099999.9999998. Binary prefixes would
    inflate the number by 4.9%. Rounding up would charge for bytes nobody sent.
    """
    amount = DataAmount.from_payload({"amount": "2048.1", "unit": "MB"})
    assert amount is not None
    assert amount.bytes == 2_048_100_000
    gigabytes = DataAmount.from_payload({"amount": "1.5", "unit": "GB"})
    assert gigabytes is not None
    assert gigabytes.bytes == 1_500_000_000


def test_an_undocumented_data_unit_is_refused() -> None:
    with pytest.raises(ContractViolation, match="undocumented data unit"):
        DataAmount.from_payload({"amount": "1", "unit": "MiB"})


def test_a_partial_purchase_keeps_both_halves() -> None:
    """The 202 body carries `data` and `errors` together.

    Reading only `data` turns an order for ten lines that produced three into a
    fulfilled order and seven people waiting for a line nobody will buy.
    """
    parsed = ESimPurchaseResponse.from_payload(
        {
            "data": [sim_payload()],
            "errors": [{"code": "70001", "title": "There aren't enough SIM cards"}],
        }
    )
    assert len(parsed.sim_cards) == 1
    assert parsed.errors[0].code == "70001"
    assert parsed.errors[0].is_capacity is True
    assert parsed.errors[0].is_terminal is False


def test_an_action_reports_its_documented_statuses() -> None:
    action = SimCardAction.from_payload(
        {
            "id": "action-1",
            "sim_card_id": "sim-1",
            "action_type": "set_standby",
            "status": {"value": "in-progress"},
        }
    )
    assert action.status is SimCardActionStatus.IN_PROGRESS
    assert action.is_settled is False
    assert action.succeeded is False  # not settled, so certainly not succeeded


def test_an_interrupted_action_is_settled_and_failed() -> None:
    """`interrupted` is in the response enum and not in the filter enum.

    An interrupted action cannot be found by filtering for it, so it is
    reachable only by id — and treating it as still running would leave the
    line's open action forever, blocking every later change to that line.
    """
    action = SimCardAction.from_payload(
        {
            "id": "action-2",
            "status": {"value": "interrupted", "reason": "the data limit was exceeded"},
        }
    )
    assert action.is_settled is True
    assert action.succeeded is False
    assert action.reason == "the data limit was exceeded"


def test_the_activation_code_never_prints_itself() -> None:
    code = ActivationCode(value="LPA:1$smdp.example$SECRET")
    assert "SECRET" not in repr(code)
    assert "SECRET" not in str(code)
    assert "SECRET" not in f"{code}"


# --- status mapping ----------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("enabled", ProviderLineState.ACTIVE),
        ("disabled", ProviderLineState.SUSPENDED),
        ("standby", ProviderLineState.SUSPENDED),
        ("enabling", ProviderLineState.TRANSITIONING),
        ("setting_standby", ProviderLineState.TRANSITIONING),
        ("data_limit_exceeded", ProviderLineState.RESTRICTED),
        ("unauthorized_imei", ProviderLineState.RESTRICTED),
        ("blocked", ProviderLineState.RESTRICTED),
        ("abolished", ProviderLineState.TERMINATED),
    ],
)
def test_every_documented_status_maps_somewhere(
    status: str, expected: ProviderLineState
) -> None:
    """Including the ones that are nobody's fault.

    `data_limit_exceeded` maps to RESTRICTED rather than SUSPENDED because we
    did not do it: treating a carrier's own cap as our suspension makes a
    resume request look like it should work when only raising the limit will.
    """
    transport = ScriptedTransport()
    transport.push(200, {"data": sim_payload(status={"value": status})})
    line = adapter(transport).fetch_line("sim-1")
    assert line is not None
    assert line.state is expected
    assert line.provider_status == status


def test_released_is_reported_as_released_not_installed() -> None:
    transport = ScriptedTransport()
    transport.push(200, {"data": sim_payload(esim_installation_status="released")})
    line = adapter(transport).fetch_line("sim-1")
    assert line is not None
    assert line.installation_released is True
    # There is no `installed` on the type at all, which is the point: nothing
    # downstream can read a release as an installation because there is nothing
    # to read.
    assert not hasattr(line, "installed")


# --- the expensive failure ---------------------------------------------------


def test_a_lost_purchase_response_is_unknown_and_sent_once() -> None:
    transport = ScriptedTransport()
    transport.push_timeout()
    with pytest.raises(ConnectivityOutcomeUnknown, match="do not purchase again"):
        adapter(transport).provision(OPERATION, 1, {})
    assert len(transport.calls) == 1


def test_a_5xx_purchase_is_unknown_not_rejected() -> None:
    transport = ScriptedTransport()
    transport.push(503, {"errors": [{"code": "10009", "title": "unavailable"}]})
    with pytest.raises(ConnectivityOutcomeUnknown):
        adapter(transport).provision(OPERATION, 1, {})


def test_a_4xx_purchase_is_a_definite_refusal() -> None:
    """A refusal is safe to treat as final. An absence of response never is."""
    transport = ScriptedTransport()
    transport.push(422, {"errors": [{"code": "70002", "title": "invalid data"}]})
    with pytest.raises(ConnectivityError) as caught:
        adapter(transport).provision(OPERATION, 1, {})
    assert caught.value.code == "purchase_rejected"
    assert "70002" in (caught.value.detail or "")


def test_reconciliation_does_not_filter_by_status() -> None:
    """The documented `filter[status]` enum omits every transitional state.

    A SIM mid-registration would be invisible to a status-filtered lookup, and
    invisible reads as "never landed", which reads as "safe to retry". That is
    the double purchase, arrived at by a query parameter.
    """
    transport = ScriptedTransport()
    transport.push(200, {"data": [sim_payload()]})
    adapter(transport, lookup_is_trusted=True).reconcile(OPERATION, 1)
    _, url, _, params = transport.calls[0]
    assert url.endswith("/sim_cards")
    assert params is not None
    assert "filter[status]" not in params
    assert params["filter[tags][]"] == f"damdam-op-{OPERATION}"


def test_an_empty_lookup_is_not_an_answer_while_consistency_is_undocumented() -> None:
    """The single most dangerous branch in the integration.

    Telnyx does not document whether a just-created eSIM is immediately visible
    to a tag filter. Until somebody proves it against a live account, an empty
    result cannot be distinguished from a purchase that landed and is not yet
    visible — and acting on it authorises a second purchase.
    """
    transport = ScriptedTransport()
    transport.push(200, {"data": []})
    assert adapter(transport).reconcile(OPERATION, 1) is None


def test_a_trusted_empty_lookup_reports_that_nothing_landed() -> None:
    transport = ScriptedTransport()
    transport.push(200, {"data": []})
    result = adapter(transport, lookup_is_trusted=True).reconcile(OPERATION, 1)
    assert result is not None
    assert result.accepted is False


def test_a_lookup_returning_someone_elses_line_is_not_an_answer() -> None:
    transport = ScriptedTransport()
    transport.push(200, {"data": [sim_payload(tags=["some-other-tag"])]})
    assert adapter(transport, lookup_is_trusted=True).reconcile(OPERATION, 1) is None


def test_over_delivery_stops_for_a_human() -> None:
    """More lines than requested means a duplicate already happened.

    Adopting them would make the books say we bought what we meant to.
    """
    transport = ScriptedTransport()
    transport.push(
        200,
        {"data": [sim_payload(id="sim-a"), sim_payload(id="sim-b")]},
    )
    assert adapter(transport, lookup_is_trusted=True).reconcile(OPERATION, 1) is None


def test_a_failed_lookup_is_not_evidence_of_anything() -> None:
    transport = ScriptedTransport()
    transport.push_timeout()
    assert adapter(transport).reconcile(OPERATION, 1) is None


# --- capabilities ------------------------------------------------------------


def test_voice_is_withheld_by_default_with_a_recorded_reason() -> None:
    """VoLTE is beta and its request/response schemas are unpublished.

    Calling `enable_voice` on the strength of the endpoint's *name* is exactly
    the "do not implement against assumed field shapes" case the contract
    record warns about.
    """
    capabilities = adapter(ScriptedTransport()).capabilities()
    assert not capabilities.supports(Capability.NATIVE_VOICE)
    assert "beta" in capabilities.undocumented[Capability.NATIVE_VOICE.value]


def test_asking_for_an_unverified_capability_raises() -> None:
    with pytest.raises(CapabilityNotAvailable):
        adapter(ScriptedTransport()).enable_voice("sim-1")


def test_spending_enforcement_is_withheld_because_latency_is_undocumented() -> None:
    """`data_limit` exists; how fast it bites does not.

    A cap with an unquantified overshoot window is not a hard cap, and chunk 17
    reads this capability to decide whether a prepaid promise can be made.
    """
    capabilities = adapter(ScriptedTransport()).capabilities()
    assert not capabilities.supports(Capability.SPENDING_ENFORCEMENT)
    reason = capabilities.undocumented[Capability.SPENDING_ENFORCEMENT.value]
    assert "latency" in reason and "voice" in reason


def test_a_verified_capability_is_exercised() -> None:
    transport = ScriptedTransport()
    transport.push(
        202,
        {
            "data": {
                "id": "action-9",
                "sim_card_id": "sim-1",
                "action_type": "enable_voice",
                "status": {"value": "in-progress"},
            }
        },
    )
    voice_adapter = adapter(
        transport,
        verified_capabilities=frozenset({Capability.DATA, Capability.NATIVE_VOICE}),
        evidence_reference="telnyx-voice-confirmation-2026-xx",
    )
    action = voice_adapter.enable_voice("sim-1")
    assert action.settled is False
    assert action.succeeded is None


# --- irreversible and gated operations ---------------------------------------


def test_deleting_a_line_is_refused() -> None:
    """Telnyx documents deletion as irreversible and the profile as gone.

    That needs a person, not a worker retry.
    """
    with pytest.raises(ConnectivityError, match="irreversible"):
        adapter(ScriptedTransport()).set_state("sim-1", ProviderLineState.TERMINATED)


def test_the_live_transport_refuses_to_exist_without_authorization() -> None:
    """D1 is open: there is no account, and turning this on is a deliberate act."""
    with pytest.raises(ConnectivityError, match="TELNYX_LIVE_ENABLED"):
        build_transport("key", live_enabled=False)
    with pytest.raises(ConnectivityError, match="no Telnyx API key"):
        build_transport("", live_enabled=True)


def test_a_failed_activation_code_fetch_names_the_sim_not_the_code() -> None:
    transport = ScriptedTransport()
    transport.push(404, {"errors": [{"code": "10005", "title": "not found"}]})
    with pytest.raises(ConnectivityError) as caught:
        adapter(transport).fetch_activation_credential("sim-1")
    assert "sim-1" in str(caught.value)
    assert "LPA" not in str(caught.value)


def test_the_activation_code_is_read_from_the_documented_endpoint() -> None:
    transport = ScriptedTransport()
    transport.push(200, {"data": {"activation_code": "LPA:1$smdp.example$ABC"}})
    credential = adapter(transport).fetch_activation_credential("sim-1")
    assert credential.secret == "LPA:1$smdp.example$ABC"
    assert credential.one_time_use is True
    _, url, _, _ = transport.calls[0]
    assert url.endswith(ACTIVATION_CODE_PATH.format(id="sim-1"))
    assert "ABC" not in repr(credential)


def test_a_lost_lifecycle_response_is_unknown_not_resent() -> None:
    """Re-sending races a request that may already be in flight, and Telnyx
    refuses a transition while another is in progress."""
    transport = ScriptedTransport()
    transport.push_timeout()
    with pytest.raises(ConnectivityOutcomeUnknown, match="before requesting it again"):
        adapter(transport).set_state("sim-1", ProviderLineState.SUSPENDED)
    assert len(transport.calls) == 1


def test_suspension_uses_standby_so_the_line_can_come_back() -> None:
    transport = ScriptedTransport()
    transport.push(
        202,
        {
            "data": {
                "id": "a1",
                "sim_card_id": "sim-1",
                "action_type": "set_standby",
                "status": {"value": "in-progress"},
            }
        },
    )
    adapter(transport).set_state("sim-1", ProviderLineState.SUSPENDED)
    _, url, _, _ = transport.calls[0]
    assert url.endswith("/sim_cards/sim-1/actions/set_standby")


def test_an_unknown_sim_is_none_rather_than_an_error() -> None:
    transport = ScriptedTransport()
    transport.push(404, {})
    assert adapter(transport).fetch_line(str(uuid4())) is None


# --- the calling amendment: carrier and internet stay apart ------------------


def test_telnyx_is_a_carrier_channel_adapter() -> None:
    """Its WebRTC product is a different integration behind a different adapter.

    `VOICE-EXPANSION.md` assigns outbound internet calling to V02/V03 and keeps
    chunks 15–17 on carrier lifecycle, usage and control.
    """
    capabilities = adapter(ScriptedTransport()).capabilities()
    assert capabilities.channel is AdapterChannel.CARRIER
    assert not capabilities.supports(Capability.INTERNET_VOICE)


def test_a_carrier_adapter_cannot_advertise_internet_calling() -> None:
    """Refused at construction, not merely discouraged in a comment.

    The amendment: *"Evidence for WebRTC never closes carrier gates."* An
    adapter able to claim both would let a browser calling test stand in for
    proof that a handset can dial from its own dialer on a visited network.
    """
    with pytest.raises(ConnectivityError) as caught:
        AdapterCapabilities(
            supported=frozenset({Capability.DATA, Capability.INTERNET_VOICE}),
            channel=AdapterChannel.CARRIER,
        )
    assert caught.value.code == "channel_capability_mismatch"


def test_an_internet_adapter_cannot_advertise_native_voice() -> None:
    with pytest.raises(ConnectivityError) as caught:
        AdapterCapabilities(
            supported=frozenset({Capability.NATIVE_VOICE}),
            channel=AdapterChannel.INTERNET,
        )
    assert caught.value.code == "channel_capability_mismatch"


def test_channel_neutral_capabilities_are_allowed_on_both() -> None:
    """Data, top-up, suspension and usage belong to neither channel alone.

    Over-restricting would be its own defect: an internet-calling adapter that
    could not advertise usage reporting would have no way to say it meters
    calls.
    """
    for channel in (AdapterChannel.CARRIER, AdapterChannel.INTERNET):
        capabilities = AdapterCapabilities(
            supported=frozenset(
                {Capability.TOPUP, Capability.SUSPENSION, Capability.USAGE_EVENTS}
            ),
            channel=channel,
        )
        assert capabilities.supports(Capability.TOPUP)
