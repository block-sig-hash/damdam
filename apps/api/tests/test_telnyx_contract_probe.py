"""US-35 / chunk 03 — Telnyx contract harness tests.

**EVERY TEST IN THIS FILE IS A SIMULATION.**

They exercise our own request construction, response parsing and reconciliation
decisions against fixtures reconstructed from Telnyx's published OpenAPI
schemas. They do not call Telnyx, and a green run here is not evidence of
Telnyx coverage, pricing, VoLTE production readiness or device behaviour.
Decision gate D1 remains OPEN regardless of this file's result.

Sources for every shape asserted here are recorded in
`docs/implementation/telnyx/API-CONTRACTS.md`, fetched 2026-09-08.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from tools.telnyx_probe.contracts import (
    FILTERABLE_STATUSES,
    SYSTEM_IMPOSED_STATUSES,
    TRANSITIONAL_STATUSES,
    ContractViolation,
    ESimPurchaseRequest,
    ESimPurchaseResponse,
    SimCard,
    SimCardStatus,
    WirelessErrorCode,
    operation_tag,
)
from tools.telnyx_probe.probe import load_fixture, main
from tools.telnyx_probe.reconcile import ReconciliationOutcome, reconcile_purchase

FIXTURES = Path(__file__).parent.parent / "tools" / "telnyx_probe" / "fixtures"
OPERATION = UUID("11111111-1111-4111-8111-111111111111")


def _card(tag: str, sim_id: str = "00000000-0000-4000-8000-00000000000f") -> SimCard:
    return SimCard.from_payload(
        {"id": sim_id, "status": "standby", "type": "esim", "tags": [tag]}
    )


class TestFixturesAreLabelledSimulations:
    """Guard rail: no fixture may masquerade as recorded supplier evidence."""

    @pytest.mark.parametrize(
        "path", sorted(FIXTURES.glob("*.json")), ids=lambda p: p.name
    )
    def test_every_fixture_declares_it_is_simulated(self, path: Path) -> None:
        payload = json.loads(path.read_text())
        assert payload["_fixture"] == "SIMULATED"
        assert payload["_source"].startswith("https://")
        assert payload["_fetched"] == "2026-09-08"

    def test_loader_rejects_an_unlabelled_fixture(self, tmp_path: Path) -> None:
        rogue = tmp_path / "rogue.json"
        rogue.write_text(json.dumps({"data": []}))
        with pytest.raises(ContractViolation, match="SIMULATED"):
            load_fixture(str(rogue))

    def test_no_fixture_contains_a_plausible_real_iccid(self) -> None:
        """Real ICCIDs begin with the 89 telecom major industry identifier."""
        for path in FIXTURES.glob("*.json"):
            for card in json.loads(path.read_text()).get("data", []):
                iccid = card.get("iccid")
                if iccid:
                    assert not iccid.startswith("89"), path.name


class TestPurchaseRequestMatchesTheDocumentedSchema:
    def test_body_carries_only_documented_fields(self) -> None:
        body = ESimPurchaseRequest(amount=3, operation_reference=OPERATION).to_body()
        assert set(body) <= {
            "amount",
            "tags",
            "sim_card_group_id",
            "product",
            "whitelabel_name",
            "status",
        }

    def test_there_is_no_idempotency_key(self) -> None:
        """Telnyx documents none; the harness must not invent one."""
        body = ESimPurchaseRequest(amount=1, operation_reference=OPERATION).to_body()
        assert not [k for k in body if "idempot" in k.lower()]

    def test_the_operation_reference_becomes_a_correlation_tag(self) -> None:
        request = ESimPurchaseRequest(amount=1, operation_reference=OPERATION)
        assert request.correlation_tag == f"damdam-op-{OPERATION}"
        assert request.to_body()["tags"] == [request.correlation_tag]

    def test_extra_tags_never_displace_the_correlation_tag(self) -> None:
        request = ESimPurchaseRequest(
            amount=1, operation_reference=OPERATION, extra_tags=("enterprise",)
        )
        assert request.to_body()["tags"][0] == request.correlation_tag
        assert "enterprise" in request.to_body()["tags"]

    def test_amount_below_the_documented_minimum_is_refused(self) -> None:
        with pytest.raises(ContractViolation, match="at least 1"):
            ESimPurchaseRequest(amount=0, operation_reference=OPERATION)

    def test_whitelabel_name_requires_the_whitelabel_product(self) -> None:
        with pytest.raises(ContractViolation, match="product='whitelabel'"):
            ESimPurchaseRequest(
                amount=1, operation_reference=OPERATION, whitelabel_name="DamDam"
            )

    def test_whitelabel_name_rejects_characters_the_docs_exclude(self) -> None:
        with pytest.raises(ContractViolation, match="letters, numbers"):
            ESimPurchaseRequest(
                amount=1,
                operation_reference=OPERATION,
                product="whitelabel",
                whitelabel_name="DamDam!",
            )

    def test_purchase_status_is_limited_to_the_documented_enum(self) -> None:
        with pytest.raises(ContractViolation, match="not accepted on purchase"):
            ESimPurchaseRequest(
                amount=1,
                operation_reference=OPERATION,
                status=SimCardStatus.DATA_LIMIT_EXCEEDED,
            )


class TestResponseParsing:
    def test_parses_an_accepted_purchase(self) -> None:
        response = ESimPurchaseResponse.from_payload(
            load_fixture("purchase_esims_202_success.json")
        )
        assert len(response.sim_cards) == 2
        assert response.errors == ()
        assert all(card.type == "esim" for card in response.sim_cards)

    def test_parses_a_partial_purchase_and_classifies_the_error(self) -> None:
        """The documented 202 body carries both `data` and `errors`."""
        response = ESimPurchaseResponse.from_payload(
            load_fixture("purchase_esims_202_partial.json")
        )
        assert len(response.sim_cards) == 1
        assert [e.code for e in response.errors] == [
            WirelessErrorCode.NOT_ENOUGH_SIM_CARDS.value
        ]
        assert response.errors[0].is_capacity is True
        assert response.errors[0].is_terminal is False

    def test_an_undocumented_status_fails_loudly(self) -> None:
        """A contract drift must surface, not be silently coerced."""
        payload = load_fixture("list_sim_cards_undocumented_status.json")
        with pytest.raises(ContractViolation, match="undocumented SIM card status"):
            SimCard.from_payload(payload["data"][0])

    def test_a_payload_without_an_id_is_refused(self) -> None:
        with pytest.raises(ContractViolation, match="no 'id'"):
            SimCard.from_payload({"status": "enabled"})

    def test_unknown_fields_are_preserved_rather_than_dropped(self) -> None:
        card = SimCard.from_payload(
            {"id": "x", "status": "enabled", "some_new_field": 42}
        )
        assert card.raw["some_new_field"] == 42

    def test_status_is_accepted_as_object_or_bare_string(self) -> None:
        as_string = SimCard.from_payload({"id": "x", "status": "enabled"})
        as_object = SimCard.from_payload({"id": "x", "status": {"value": "enabled"}})
        assert as_string.status is as_object.status is SimCardStatus.ENABLED


class TestDocumentedStatusModel:
    def test_transitional_and_system_imposed_sets_are_disjoint(self) -> None:
        assert not TRANSITIONAL_STATUSES & SYSTEM_IMPOSED_STATUSES

    def test_transitional_statuses_are_not_filterable(self) -> None:
        """`filter[status]` omits them, so a mid-transition SIM can be invisible.

        This is why reconciliation filters by tag and never by status.
        """
        assert not TRANSITIONAL_STATUSES & FILTERABLE_STATUSES

    def test_blocked_and_abolished_are_not_filterable_either(self) -> None:
        assert SimCardStatus.BLOCKED not in FILTERABLE_STATUSES
        assert SimCardStatus.ABOLISHED not in FILTERABLE_STATUSES


class TestReconciliationOfAnUnknownPurchaseOutcome:
    """Finding 4, against the documented contract.

    There is no idempotency key, so a lost response can only be resolved by
    looking up what the supplier actually created.
    """

    def test_all_requested_esims_present_is_complete_and_never_retries(self) -> None:
        tag = operation_tag(OPERATION)
        decision = reconcile_purchase(
            requested_amount=2,
            operation_reference=OPERATION,
            sim_cards=[_card(tag, "a"), _card(tag, "b")],
            lookup_is_trusted=True,
        )
        assert decision.outcome is ReconciliationOutcome.COMPLETE
        assert decision.may_retry_purchase is False
        assert decision.requires_manual_review is False

    def test_an_empty_untrusted_lookup_escalates_instead_of_retrying(self) -> None:
        """The core safety property.

        Tag-filter consistency after purchase is undocumented, so an empty
        result cannot be read as 'the purchase never landed'. Retrying on it
        would double-purchase -- exactly the reported defect.
        """
        decision = reconcile_purchase(
            requested_amount=2,
            operation_reference=OPERATION,
            sim_cards=[],
            lookup_is_trusted=False,
        )
        assert decision.may_retry_purchase is False
        assert decision.requires_manual_review is True
        assert "undocumented" in decision.reason

    def test_an_empty_trusted_lookup_may_retry_with_the_same_reference(self) -> None:
        decision = reconcile_purchase(
            requested_amount=2,
            operation_reference=OPERATION,
            sim_cards=[],
            lookup_is_trusted=True,
        )
        assert decision.outcome is ReconciliationOutcome.NOT_LANDED
        assert decision.may_retry_purchase is True

    def test_a_partial_result_never_auto_retries(self) -> None:
        decision = reconcile_purchase(
            requested_amount=2,
            operation_reference=OPERATION,
            sim_cards=[_card(operation_tag(OPERATION))],
            lookup_is_trusted=True,
        )
        assert decision.outcome is ReconciliationOutcome.PARTIAL
        assert decision.may_retry_purchase is False
        assert decision.requires_manual_review is True

    def test_over_delivery_is_flagged_as_an_existing_duplicate(self) -> None:
        tag = operation_tag(OPERATION)
        decision = reconcile_purchase(
            requested_amount=1,
            operation_reference=OPERATION,
            sim_cards=[_card(tag, "a"), _card(tag, "b")],
            lookup_is_trusted=True,
        )
        assert decision.outcome is ReconciliationOutcome.OVER_DELIVERED
        assert decision.requires_manual_review is True

    def test_a_result_carrying_the_wrong_tag_is_never_adopted(self) -> None:
        """If the filter returns something untagged, our query assumption is wrong."""
        decision = reconcile_purchase(
            requested_amount=1,
            operation_reference=OPERATION,
            sim_cards=[_card("damdam-op-99999999-9999-4999-8999-999999999999")],
            lookup_is_trusted=True,
        )
        assert decision.matched_count == 0
        assert decision.may_retry_purchase is False
        assert decision.requires_manual_review is True

    def test_no_reachable_outcome_both_retries_and_needs_review(self) -> None:
        tag = operation_tag(OPERATION)
        for cards, trusted, amount in (
            ([_card(tag, "a"), _card(tag, "b")], True, 2),
            ([], False, 2),
            ([], True, 2),
            ([_card(tag)], True, 2),
            ([_card(tag, "a"), _card(tag, "b")], True, 1),
        ):
            decision = reconcile_purchase(
                requested_amount=amount,
                operation_reference=OPERATION,
                sim_cards=cards,
                lookup_is_trusted=trusted,
            )
            assert not (
                decision.may_retry_purchase and decision.requires_manual_review
            )


class TestProbeRefusesUnauthorizedLiveUse:
    def test_live_mode_refuses_without_the_authorization_flag(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TELNYX_API_KEY", "irrelevant-because-it-refuses-first")
        assert main(["--mode", "live", "--tag", "damdam-op-x"]) == 2
        assert "Refusing to run live" in capsys.readouterr().err

    def test_live_mode_refuses_without_a_credential(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TELNYX_API_KEY", raising=False)
        exit_code = main(
            ["--mode", "live", "--i-have-authorization", "--tag", "damdam-op-x"]
        )
        assert exit_code == 2
        assert "TELNYX_API_KEY is not set" in capsys.readouterr().err

    def test_live_mode_refuses_without_a_tag(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TELNYX_API_KEY", "irrelevant")
        assert main(["--mode", "live", "--i-have-authorization"]) == 2
        assert "--tag is required" in capsys.readouterr().err

    def test_fixture_mode_labels_its_own_output_as_simulated(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main([]) == 0
        out = capsys.readouterr().out
        assert out.startswith("SIMULATED")
        assert "D1 remains OPEN" in out

    def test_the_package_exposes_no_purchase_call_path(self) -> None:
        """Nothing here may spend money.

        The purchase path is modelled as a request *body builder* only; no
        module in the harness issues a POST.
        """
        harness = Path(__file__).parent.parent / "tools" / "telnyx_probe"
        sources = "\n".join(
            p.read_text() for p in harness.glob("*.py")
        )
        assert ".post(" not in sources
        assert "httpx.post" not in sources
