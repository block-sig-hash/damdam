"""US-36 chunk 16 — the Telnyx usage contract, offline.

**EVERY TEST IN THIS FILE IS A SIMULATION.** Payloads are transcribed from
Telnyx's published OpenAPI source, re-verified 2026-09-10 and recorded in
`docs/implementation/telnyx/API-CONTRACTS.md` §4. Nothing here calls Telnyx and
**D1 remains OPEN**.

The most important thing this file asserts is a refusal. Telnyx's Wireless
Detail Records have **no published record schema** — the OpenAPI source
documents the report envelope and the prose field list contains neither a byte
count nor a record id. So `USAGE_EVENTS` is withheld by default, the report
file is not parsed, and both facts have tests, because the tempting alternative
is to write a parser against a prose bullet list and call it an integration.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.connectivity.contract import (
    Capability,
    CapabilityNotAvailable,
    ConnectivityError,
)
from app.connectivity.telnyx import TelnyxConnectivityAdapter, TelnyxResponse
from app.connectivity.telnyx_contract import ContractViolation
from app.usage.contract import ReportState

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


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


def _sim(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "sim-usage",
        "status": {"value": "enabled"},
        "type": "esim",
        "iccid": "89310410106543789301",
        "tags": [],
        "voice_enabled": False,
        "esim_installation_status": None,
        "actions_in_progress": False,
        "current_billing_period_consumed_data": {"amount": "2049.0", "unit": "MB"},
        "data_limit": {"amount": "5", "unit": "GB"},
    }
    payload.update(overrides)
    return payload


# --- the counter -------------------------------------------------------------


def test_the_counter_converts_to_exact_bytes() -> None:
    """`{amount: "2049.0", unit: "MB"}` is 2,049,000,000 bytes.

    Decimal prefixes, not binary: assuming MiB would inflate the figure by 4.9%
    and quietly exhaust a customer's plan early.
    """
    transport = ScriptedTransport()
    transport.push(200, {"data": _sim()})
    snapshot = _adapter(transport).fetch_usage_counter("sim-usage")
    assert snapshot is not None
    assert snapshot.consumed_bytes == 2_049_000_000
    assert snapshot.limit_bytes == 5_000_000_000
    assert snapshot.observed_at == NOW


def test_the_counter_reports_no_cycle_boundary_because_none_is_documented() -> None:
    """`None` rather than a guess.

    Telnyx exposes no billing-period identifier on the SIM card resource, so
    `ingest_counter` cannot use one to tell a cycle rollover from a supplier
    error — and it says so instead of inventing a boundary from a date.
    """
    transport = ScriptedTransport()
    transport.push(200, {"data": _sim()})
    snapshot = _adapter(transport).fetch_usage_counter("sim-usage")
    assert snapshot is not None
    assert snapshot.cycle_reference is None


def test_a_line_with_no_counter_returns_none_rather_than_zero() -> None:
    """Zero is a measurement. Absence is not.

    Reporting zero consumption for a SIM that reported nothing would look like
    an idle line and would reset a delta computation to the whole cycle.
    """
    payload = _sim()
    del payload["current_billing_period_consumed_data"]
    transport = ScriptedTransport()
    transport.push(200, {"data": payload})
    assert _adapter(transport).fetch_usage_counter("sim-usage") is None


def test_an_undocumented_data_unit_stops_the_adapter() -> None:
    transport = ScriptedTransport()
    transport.push(
        200,
        {
            "data": _sim(
                current_billing_period_consumed_data={"amount": "1", "unit": "TB"}
            )
        },
    )
    with pytest.raises(ContractViolation, match="undocumented data unit"):
        _adapter(transport).fetch_usage_counter("sim-usage")


# --- the report --------------------------------------------------------------


def test_usage_events_are_withheld_because_records_have_no_documented_id() -> None:
    """The reason is recorded, not left for a reader to infer.

    Without a record id, deduplication has to compose a key from fields that
    were never guaranteed unique. That is a decision somebody takes with
    evidence, not a default an adapter makes quietly.
    """
    capabilities = _adapter(ScriptedTransport()).capabilities()
    assert not capabilities.supports(Capability.USAGE_EVENTS)
    reason = capabilities.undocumented[Capability.USAGE_EVENTS.value]
    assert "record id" in reason and "deduplicated" in reason


def test_requesting_a_report_without_the_capability_is_refused() -> None:
    with pytest.raises(CapabilityNotAvailable):
        _adapter(ScriptedTransport()).request_usage_report(
            NOW - timedelta(days=1), NOW
        )


def test_the_report_request_uses_the_corrected_path() -> None:
    """`/wireless/detail_records_reports`.

    Chunk 03 recorded `/wireless/detail/records/reports`, which would have
    404'd on the first real call. The correction is in API-CONTRACTS.md §4.1.
    """
    transport = ScriptedTransport()
    transport.push(201, {"data": {"id": "report-1", "status": "pending"}})
    handle = _adapter(
        transport, frozenset({Capability.DATA, Capability.USAGE_EVENTS})
    ).request_usage_report(NOW - timedelta(days=1), NOW)
    assert handle == "report-1"
    method, url, body = transport.calls[0]
    assert method == "POST"
    assert url.endswith("/wireless/detail_records_reports")
    assert body == {
        "start_time": "2026-09-09T12:00:00.000Z",
        "end_time": "2026-09-10T12:00:00.000Z",
    }


def test_a_pending_report_is_not_an_empty_one() -> None:
    """A report still generating has produced no records, not zero usage."""
    transport = ScriptedTransport()
    transport.push(200, {"data": {"id": "report-1", "status": "pending"}})
    report = _adapter(
        transport, frozenset({Capability.DATA, Capability.USAGE_EVENTS})
    ).fetch_usage_report("report-1")
    assert report.state is ReportState.PENDING
    assert report.events == ()


def test_a_deleted_report_is_terminal() -> None:
    """A poller that waits on an unrecognised status waits forever."""
    transport = ScriptedTransport()
    transport.push(200, {"data": {"id": "report-1", "status": "deleted"}})
    report = _adapter(
        transport, frozenset({Capability.DATA, Capability.USAGE_EVENTS})
    ).fetch_usage_report("report-1")
    assert report.state is ReportState.DELETED


def test_a_missing_report_is_treated_as_deleted_not_pending() -> None:
    transport = ScriptedTransport()
    transport.push(404, {})
    report = _adapter(
        transport, frozenset({Capability.DATA, Capability.USAGE_EVENTS})
    ).fetch_usage_report("gone")
    assert report.state is ReportState.DELETED


def test_an_undocumented_report_status_stops_the_adapter() -> None:
    transport = ScriptedTransport()
    transport.push(200, {"data": {"id": "report-1", "status": "archiving"}})
    with pytest.raises(ContractViolation, match="undocumented WDR report status"):
        _adapter(
            transport, frozenset({Capability.DATA, Capability.USAGE_EVENTS})
        ).fetch_usage_report("report-1")


def test_a_complete_report_returns_its_window_and_no_parsed_records() -> None:
    """The file at `report_url` has no published schema, so it is not parsed.

    Writing a parser against a prose field list — one that names no byte count
    and no record id — and calling it an integration is precisely the invented
    contract `AGENTS.md` forbids. The window is returned so a cursor can know
    what was actually covered.
    """
    transport = ScriptedTransport()
    transport.push(
        200,
        {
            "data": {
                "id": "report-1",
                "status": "complete",
                "start_time": "2026-09-09T12:00:00.000Z",
                "end_time": "2026-09-10T12:00:00.000Z",
                "report_url": "https://example.invalid/report",
            }
        },
    )
    report = _adapter(
        transport, frozenset({Capability.DATA, Capability.USAGE_EVENTS})
    ).fetch_usage_report("report-1")
    assert report.state is ReportState.COMPLETE
    assert report.events == ()
    assert report.covers_from == NOW - timedelta(days=1)
    assert report.covers_to == NOW


def test_a_rejected_report_request_is_reported() -> None:
    transport = ScriptedTransport()
    transport.push(422, {"errors": [{"code": "70002", "title": "invalid data"}]})
    with pytest.raises(ConnectivityError) as caught:
        _adapter(
            transport, frozenset({Capability.DATA, Capability.USAGE_EVENTS})
        ).request_usage_report(NOW - timedelta(days=1), NOW)
    assert caught.value.code == "usage_report_rejected"


def test_a_malformed_report_timestamp_is_a_contract_violation() -> None:
    transport = ScriptedTransport()
    transport.push(
        200,
        {"data": {"id": "r", "status": "complete", "start_time": "yesterday"}},
    )
    with pytest.raises(ContractViolation, match="not ISO 8601"):
        _adapter(
            transport, frozenset({Capability.DATA, Capability.USAGE_EVENTS})
        ).fetch_usage_report("r")
