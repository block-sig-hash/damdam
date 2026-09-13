"""Destination policy — the refusals that must happen before any SDK call.

V01's contract (`docs/implementation/voice/API-CONTRACTS.md` §2) established the
one fact this module exists for: Telnyx routes country-matched **emergency**
calls normally rather than parking them, so the backend's parked-call decision
point never sees them. A destination that the server would refuse must therefore
be refused *before* the client is told to dial, not when the webhook arrives —
by then the call is already connecting and already costing money.

That makes this the only part of the calling engine whose correctness cannot be
recovered later by a downstream check, which is why it is a pure module with no
database and no provider.
"""

import pytest

from app.calling.policy import (
    DestinationDecision,
    DestinationRefused,
    classify_destination,
    normalize_destination,
)
from app.catalog.tariffs import DestinationKind


class TestNormalization:
    def test_accepts_e164(self) -> None:
        assert normalize_destination("+2348031234567") == "+2348031234567"

    def test_strips_formatting(self) -> None:
        assert normalize_destination(" +234 (803) 123-4567 ") == "+2348031234567"

    @pytest.mark.parametrize(
        "raw",
        [
            "08031234567",  # national format: no origin country to expand it from
            "2348031234567",  # no leading +
            "+0123456789",  # country code cannot start with 0
            "+234",  # too short to be a subscriber number
            "+2348031234567890123",  # longer than E.164 allows
            "",
            "+234803123456a",
        ],
    )
    def test_rejects_anything_not_e164(self, raw: str) -> None:
        # An internet call has no SIM and therefore no home country to infer a
        # national number from. Guessing one would silently dial a different
        # country's subscriber.
        with pytest.raises(DestinationRefused) as excinfo:
            normalize_destination(raw)
        assert excinfo.value.code == "destination_not_e164"


class TestEmergencyRefusal:
    @pytest.mark.parametrize(
        "number",
        ["+234112", "+2341122", "+234199", "+112", "+911", "+999", "+2340112"],
    )
    def test_emergency_and_short_codes_are_refused(self, number: str) -> None:
        with pytest.raises(DestinationRefused) as excinfo:
            classify_destination(number, supported_countries=frozenset({"NG"}))
        assert excinfo.value.code == "destination_emergency_or_special"

    def test_refusal_names_the_provider_bypass_as_the_reason(self) -> None:
        with pytest.raises(DestinationRefused) as excinfo:
            classify_destination("+234112", supported_countries=frozenset({"NG"}))
        # The message is the operator's explanation for why a client-side check
        # is not sufficient here.
        assert "bypass" in (excinfo.value.detail or "")


class TestPremiumAndUnsupported:
    @pytest.mark.parametrize("number", ["+2347001234567", "+2349001234567"])
    def test_nigerian_premium_ranges_are_refused(self, number: str) -> None:
        with pytest.raises(DestinationRefused) as excinfo:
            classify_destination(number, supported_countries=frozenset({"NG"}))
        assert excinfo.value.code == "destination_premium"

    def test_unsupported_country_is_refused(self) -> None:
        with pytest.raises(DestinationRefused) as excinfo:
            classify_destination("+15551234567", supported_countries=frozenset({"NG"}))
        assert excinfo.value.code == "destination_country_not_supported"

    def test_unknown_country_code_is_refused_rather_than_guessed(self) -> None:
        # "Unknown means unavailable" (VOICE-EXPANSION.md). A number whose
        # country we cannot resolve cannot be priced, so it cannot be sold.
        with pytest.raises(DestinationRefused) as excinfo:
            classify_destination("+9991234567", supported_countries=frozenset({"NG"}))
        assert excinfo.value.code == "destination_country_unknown"


class TestClassification:
    def test_nigerian_mobile(self) -> None:
        decision = classify_destination(
            "+2348031234567", supported_countries=frozenset({"NG"})
        )
        assert decision == DestinationDecision(
            e164="+2348031234567",
            country="NG",
            kind=DestinationKind.MOBILE,
        )

    def test_nigerian_landline(self) -> None:
        decision = classify_destination(
            "+23412345678", supported_countries=frozenset({"NG"})
        )
        assert decision.kind is DestinationKind.LANDLINE
        assert decision.country == "NG"

    def test_classification_normalizes_first(self) -> None:
        decision = classify_destination(
            " +234-803-123-4567 ", supported_countries=frozenset({"NG"})
        )
        assert decision.e164 == "+2348031234567"
