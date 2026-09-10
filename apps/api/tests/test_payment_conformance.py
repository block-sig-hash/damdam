"""US-33 chunk 13 — the shared adapter conformance suite, and the D4 block.

The chunk's own instruction, when no processor has been selected: *"finish
conformance tests and the adapter boundary, then mark provider-specific work
blocked."* So this file does two things — runs the suite against the one adapter
that exists, and asserts that no second one has been quietly added.

**This is not evidence of external compatibility.** Every case drives an
injected transport, because the behaviours worth checking are the ones a sandbox
will not produce on demand: an ambiguous status, a reordered webhook, a
transport failure mid-charge. What it proves is that an adapter obeys *our*
contract. Whether a vendor obeys *its own documentation* needs a sandbox run,
and none has been made.
"""

import hashlib
import hmac
from decimal import Decimal
from typing import Any

import pytest

from app.payments.conformance import CASES, AdapterHarness, ConformanceFailure
from app.payments.paystack_adapter import PaystackAdapter
from app.payments.wallets import (
    CURRENT_CONFIGURATION,
    Wallet,
    WalletConfiguration,
    WalletUnavailableReason,
    card_fallback_required,
    is_available,
)

SECRET = "sk_test_conformance_only"


class ScriptedTransport:
    def __init__(self) -> None:
        self.next_response: dict[str, Any] = {}
        self.raises = False
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, method: str, url: str, body: dict) -> dict:
        self.calls.append((method, url, body))
        if self.raises:
            self.raises = False  # one failure, not a permanent one
            raise ConnectionError("network went away")
        return self.next_response


def _paystack_harness() -> AdapterHarness:
    transport = ScriptedTransport()
    adapter = PaystackAdapter(SECRET, transport)

    def respond(envelope: dict) -> None:
        transport.next_response = envelope

    def fail() -> None:
        transport.raises = True

    def sign(body: bytes) -> dict[str, str]:
        return {
            "x-paystack-signature": hmac.new(
                SECRET.encode(), body, hashlib.sha512
            ).hexdigest()
        }

    return AdapterHarness(
        adapter=adapter,
        currency="NGN",
        secret=SECRET,
        respond=respond,
        fail_transport=fail,
        sign=sign,
    )


#: Every adapter that exists. A second entry appears here when D4 selects a
#: processor and its adapter is written -- and it must pass every case below
#: before it is used for anything.
ADAPTER_HARNESSES = {"paystack": _paystack_harness}


@pytest.mark.parametrize("adapter_name", sorted(ADAPTER_HARNESSES))
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_adapter_conformance(adapter_name: str, case) -> None:
    harness = ADAPTER_HARNESSES[adapter_name]()
    try:
        case.run(harness)
    except ConformanceFailure as failure:
        pytest.fail(f"{adapter_name}: {case.name} — {failure}\nwhy: {case.why}")


class TestTheSuiteItself:
    def test_every_case_says_what_it_prevents(self):
        # A conformance suite whose cases are unexplained gets weakened by
        # whoever next finds one inconvenient.
        for case in CASES:
            assert case.why, f"{case.name} does not say what it prevents"
            assert len(case.why) > 20

    def test_the_suite_covers_the_outcomes_the_chunk_names(self):
        """The assignment: asynchronous success, abandonment, decline, ambiguity."""
        names = " ".join(case.name for case in CASES)
        assert "abandonment" in names
        assert "decline" in names
        assert "unknown status" in names
        assert "transport failure" in names

    def test_a_broken_adapter_fails_the_suite(self):
        """The suite must be able to fail, or it is decoration.

        A conformance suite that passes for any input is worse than none: it
        creates confidence in a qualification that never happened.
        """
        harness = _paystack_harness()

        class AlwaysSucceeds:
            name = "broken"

            def fetch_charge(self, reference: str):
                from app.payments.routing import ProcessorCharge

                return ProcessorCharge(
                    processor_reference=reference,
                    status="whatever",
                    amount=Decimal("1.00"),
                    currency="NGN",
                    succeeded=True,  # the bug
                )

        harness.adapter = AlwaysSucceeds()  # type: ignore[assignment]
        unknown_status = next(
            case for case in CASES if case.name == "unknown status is not success"
        )
        with pytest.raises(ConformanceFailure):
            unknown_status.run(harness)


class TestProviderSpecificWorkIsBlocked:
    """D4 is open. This records the block rather than working around it."""

    def test_no_global_processor_adapter_exists_yet(self):
        # When D4 selects one, its adapter is added to ADAPTER_HARNESSES and
        # this expectation changes in the same commit -- which is the point:
        # adding an adapter without qualifying it fails here.
        assert sorted(ADAPTER_HARNESSES) == ["paystack"]

    def test_no_processor_is_named_in_the_wallet_configuration(self):
        """A default naming Stripe would read like a decision D4 has not made."""
        assert CURRENT_CONFIGURATION.processor is None
        assert CURRENT_CONFIGURATION.supported_wallets == frozenset()
        assert CURRENT_CONFIGURATION.merchant_is_live is False

    def test_the_repository_contains_no_stripe_integration(self):
        """Prose about the candidate is fine; code is not.

        Parsed with `ast` rather than grepped, because the first version of this
        test flagged its own docstrings -- and a check that cannot tell an
        explanation from an import would either be disabled or would push the
        explanation out of the code, which is worse than either.
        """
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1] / "app"
        offenders: list[str] = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text())
            # Identified by node identity, not by value: `ast.get_docstring`
            # returns a cleaned string while the Constant holds the raw one, so
            # comparing them never matches and every docstring reads as code.
            docstring_nodes = set()
            for node in ast.walk(tree):
                body = getattr(node, "body", None)
                if not isinstance(body, list) or not body:
                    continue
                first = body[0]
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    docstring_nodes.add(id(first.value))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import | ast.ImportFrom):
                    names = [alias.name for alias in node.names]
                    if isinstance(node, ast.ImportFrom):
                        names.append(node.module or "")
                    if any("stripe" in name.lower() for name in names):
                        offenders.append(f"{path.name}: imports stripe")
                elif isinstance(node, ast.Name) and "stripe" in node.id.lower():
                    offenders.append(f"{path.name}: name {node.id}")
                elif (
                    isinstance(node, ast.Attribute) and "stripe" in node.attr.lower()
                ):
                    offenders.append(f"{path.name}: attribute {node.attr}")
                elif (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and "stripe" in node.value.lower()
                    and id(node) not in docstring_nodes
                ):
                    offenders.append(f"{path.name}: literal {node.value[:40]!r}")
        assert offenders == [], offenders


class TestWalletAvailability:
    def _configured(self) -> WalletConfiguration:
        return WalletConfiguration(
            processor="selected-processor",
            supported_wallets=frozenset({Wallet.APPLE_PAY}),
            merchant_is_live=True,
            registered_domains=frozenset({"pay.damdam.example"}),
        )

    def test_no_wallet_is_available_today(self):
        result = is_available(
            CURRENT_CONFIGURATION, Wallet.APPLE_PAY, "pay.damdam.example", True
        )
        assert result.available is False
        assert result.reason is WalletUnavailableReason.NO_PROCESSOR_SELECTED

    def test_an_unregistered_domain_blocks_it(self):
        # A manual step with an external approval attached. Skipping it shows
        # the customer a payment button that fails.
        result = is_available(
            self._configured(), Wallet.APPLE_PAY, "staging.damdam.example", True
        )
        assert result.reason is WalletUnavailableReason.DOMAIN_NOT_REGISTERED

    def test_a_processor_that_does_not_support_it_blocks_it(self):
        result = is_available(
            self._configured(), Wallet.GOOGLE_PAY, "pay.damdam.example", True
        )
        assert result.reason is WalletUnavailableReason.PROCESSOR_DOES_NOT_SUPPORT

    def test_a_merchant_that_is_not_live_blocks_it(self):
        configuration = WalletConfiguration(
            processor="selected-processor",
            supported_wallets=frozenset({Wallet.APPLE_PAY}),
            merchant_is_live=False,
            registered_domains=frozenset({"pay.damdam.example"}),
        )
        result = is_available(
            configuration, Wallet.APPLE_PAY, "pay.damdam.example", True
        )
        assert result.reason is WalletUnavailableReason.MERCHANT_NOT_LIVE

    def test_a_device_that_does_not_offer_it_is_the_last_reason(self):
        # Last because it is the only one that is not a configuration problem.
        result = is_available(
            self._configured(), Wallet.APPLE_PAY, "pay.damdam.example", False
        )
        assert result.reason is WalletUnavailableReason.DEVICE_DOES_NOT_OFFER

    def test_everything_aligned_makes_it_available(self):
        result = is_available(
            self._configured(), Wallet.APPLE_PAY, "pay.damdam.example", True
        )
        assert result.available is True

    def test_card_fallback_is_required_whenever_a_wallet_is_not_offered(self):
        """Which is always, today.

        A checkout offering only a wallet, on a device without one, is a
        checkout nobody can complete.
        """
        unavailable = is_available(
            CURRENT_CONFIGURATION, Wallet.APPLE_PAY, "pay.damdam.example", True
        )
        assert card_fallback_required(unavailable) is True
        available = is_available(
            self._configured(), Wallet.APPLE_PAY, "pay.damdam.example", True
        )
        assert card_fallback_required(available) is False

    def test_no_store_billing_is_implemented(self):
        """The assignment forbids it outright.

        Store billing takes a commission on the sale and applies store rules to
        a service the stores do not provide.
        """
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1] / "app"
        for path in root.rglob("*.py"):
            lowered = path.read_text().lower()
            for forbidden in ("storekit", "in_app_purchase", "billingclient"):
                assert forbidden not in lowered, f"{path.name} references {forbidden}"
