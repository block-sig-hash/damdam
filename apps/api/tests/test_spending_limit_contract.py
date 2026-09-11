"""US-36 chunk 17 — the Telnyx spending-limit contract, offline.

**EVERY TEST IN THIS FILE IS A SIMULATION.** Payloads are transcribed from
Telnyx's published OpenAPI source, re-verified 2026-09-10 and recorded in
`docs/implementation/telnyx/API-CONTRACTS.md` §4. Nothing calls Telnyx and
**D1 remains OPEN**.

The point of the file is the shape of the one Telnyx call that is *not*
asynchronous, and the capability that gates it. `PATCH /sim_cards/{id}` returns
`200` with the updated SIM card, not a `202` and an action — so pretending it
settles later would invent a step that does not exist.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from app.connectivity.contract import (
    Capability,
    CapabilityNotAvailable,
    ConnectivityError,
)
from app.connectivity.telnyx import TelnyxConnectivityAdapter, TelnyxResponse
from app.connectivity.telnyx_contract import ContractViolation

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
ENFORCING = frozenset(
    {Capability.DATA, Capability.SUSPENSION, Capability.SPENDING_ENFORCEMENT}
)


class ScriptedTransport:
    def __init__(self) -> None:
        self.queue: list[TelnyxResponse] = []
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def push(self, status_code: int, payload: dict[str, Any]) -> None:
        self.queue.append(TelnyxResponse(status_code=status_code, payload=payload))

    def __call__(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None,
        params: dict[str, Any] | None,
    ) -> TelnyxResponse:
        self.calls.append((method, url, body))
        if not self.queue:
            raise AssertionError(f"unscripted call: {method} {url}")
        return self.queue.pop(0)


def _adapter(
    transport: ScriptedTransport, capabilities: frozenset[Capability] | None = None
) -> TelnyxConnectivityAdapter:
    return TelnyxConnectivityAdapter(
        transport, verified_capabilities=capabilities, clock=lambda: NOW
    )


def _sim(limit_mb: str = "1500") -> dict[str, Any]:
    return {
        "id": "sim-limit",
        "status": {"value": "enabled"},
        "type": "esim",
        "iccid": "89310410106543789301",
        "tags": [],
        "voice_enabled": False,
        "esim_installation_status": None,
        "actions_in_progress": False,
        "data_limit": {"amount": limit_mb, "unit": "MB"},
    }


def test_setting_a_limit_without_the_capability_is_refused() -> None:
    """Telnyx does not get `SPENDING_ENFORCEMENT` by default.

    The limit is documented; its network-side enforcement latency is not, and a
    cap with an unquantified overshoot window is not a hard cap.
    """
    with pytest.raises(CapabilityNotAvailable):
        _adapter(ScriptedTransport()).set_data_limit("sim-limit", 1_000_000_000)


def test_a_limit_is_sent_in_the_documented_unit() -> None:
    """`{data_limit: {amount, unit}}`, unit MB, amount a string.

    Sending bytes into a field documented as MB would set a cap 1,000,000 times
    smaller than intended, which reads as a bug in the customer's plan rather
    than in ours.
    """
    transport = ScriptedTransport()
    transport.push(200, {"data": _sim()})
    line = _adapter(transport, ENFORCING).set_data_limit("sim-limit", 1_500_000_000)
    method, url, body = transport.calls[0]
    assert method == "PATCH"
    assert url.endswith("/sim_cards/sim-limit")
    assert body == {"data_limit": {"amount": "1500", "unit": "MB"}}
    assert line.data_limit_bytes == 1_500_000_000


def test_a_limit_that_is_not_a_whole_number_of_megabytes_is_refused() -> None:
    """Rounding it would set a cap nobody chose.

    Silently adjusting a customer's limit is the sort of thing that is only
    noticed when it has been wrong for a month.
    """
    with pytest.raises(ConnectivityError) as caught:
        _adapter(ScriptedTransport(), ENFORCING).set_data_limit("sim-limit", 1_500_001)
    assert caught.value.code == "data_limit_not_expressible"


def test_a_negative_limit_is_refused() -> None:
    with pytest.raises(ConnectivityError) as caught:
        _adapter(ScriptedTransport(), ENFORCING).set_data_limit("sim-limit", -1)
    assert caught.value.code == "negative_data_limit"


def test_the_limit_call_is_synchronous_and_returns_the_line() -> None:
    """It is the one lifecycle-adjacent call that does not return an action.

    Returning a `ProviderAction` here would invent a settlement step, and a
    caller would then poll an action id that never existed.
    """
    transport = ScriptedTransport()
    transport.push(200, {"data": _sim("2000")})
    result = _adapter(transport, ENFORCING).set_data_limit("sim-limit", 2_000_000_000)
    assert not hasattr(result, "settled")
    assert result.provider_reference == "sim-limit"
    assert result.data_limit_bytes == 2_000_000_000


def test_a_rejected_limit_is_reported_with_the_supplier_error_code() -> None:
    transport = ScriptedTransport()
    transport.push(422, {"errors": [{"code": "70002", "title": "invalid data"}]})
    with pytest.raises(ConnectivityError) as caught:
        _adapter(transport, ENFORCING).set_data_limit("sim-limit", 1_000_000)
    assert caught.value.code == "data_limit_rejected"
    assert "70002" in (caught.value.detail or "")


def test_a_response_with_no_sim_card_is_a_contract_violation() -> None:
    transport = ScriptedTransport()
    transport.push(200, {})
    with pytest.raises(ContractViolation, match="no 'data' object"):
        _adapter(transport, ENFORCING).set_data_limit("sim-limit", 1_000_000)
