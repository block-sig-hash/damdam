"""The shared payment-adapter conformance suite (US-33, chunk 13).

**D4 is open.** No global processor has been selected — `DECISIONS.md` records
Stripe as a *candidate*, and the chunk assignment is explicit about what to do
in that case: *"Without a selection, finish conformance tests and the adapter
boundary, then mark provider-specific work blocked."* That is what this is.

The suite is a set of behaviours every adapter must exhibit, expressed against
the `PaymentProcessorAdapter` contract and nothing else. Running it against a
new adapter is how a processor is qualified; running it against Paystack today
is how we know the contract is satisfiable by a real integration rather than
only by a fake built to fit it.

What it deliberately does **not** do:

- It does not reach the network. Each case drives the adapter's injected
  transport, because the behaviours worth checking — an ambiguous status, a
  reordered webhook, a transport failure mid-charge — are precisely the ones a
  sandbox will not produce on demand.
- It is therefore **not evidence of external compatibility.** A mock passing
  itself proves nothing about a vendor, and `AGENTS.md` says so. What it proves
  is that the adapter obeys *our* contract; whether the vendor obeys *its own
  documentation* needs a sandbox run, and that is recorded as outstanding.

Every case states the failure it prevents, because a conformance suite whose
cases are unexplained gets weakened by whoever next finds one inconvenient.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.payments.contract import PaymentMethodKind
from app.payments.routing import (
    PaymentProcessorAdapter,
    PaymentRoutingError,
)


@dataclass
class ConformanceCase:
    """One required behaviour, and the incident it prevents."""

    name: str
    why: str
    run: Callable[["AdapterHarness"], None]


@dataclass
class AdapterHarness:
    """Everything a case needs to drive one adapter deterministically.

    An adapter that cannot be driven this way cannot be qualified, and that is
    a deliberate barrier to entry: a processor integration nobody can test
    against an ambiguous outcome is one whose ambiguous outcomes are discovered
    in production.
    """

    adapter: PaymentProcessorAdapter
    currency: str
    secret: str
    #: Sets what the next transport call returns, or makes it raise.
    respond: Callable[[dict[str, Any]], None]
    fail_transport: Callable[[], None]
    #: Signs a raw body the way this processor does.
    sign: Callable[[bytes], dict[str, str]]
    #: The raw bodies the harness has signed, for a reordering case.
    history: list[bytes] = field(default_factory=list)


class ConformanceFailure(AssertionError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConformanceFailure(message)


# --- the cases ---------------------------------------------------------------


def _amount_round_trips(harness: AdapterHarness) -> None:
    """An amount sent must come back as the same amount.

    The failure: a minor-unit convention applied in one direction and not the
    other, which is a hundredfold error that looks like a pricing decision.
    """
    harness.respond(_success_envelope(harness, "conf-1", Decimal("1234.56")))
    charge = harness.adapter.fetch_charge("conf-1")
    _require(charge is not None, "fetch_charge returned nothing for a known charge")
    assert charge is not None
    _require(
        charge.amount == Decimal("1234.56"),
        f"amount did not round-trip: got {charge.amount}",
    )
    _require(charge.currency == harness.currency, "currency did not round-trip")


def _unknown_status_is_not_success(harness: AdapterHarness) -> None:
    """An unrecognised status is not a success.

    The failure: `succeeded = status != "failed"`, which turns every future
    status a processor invents into a fulfilled order.
    """
    harness.respond(
        _envelope(harness, "conf-2", Decimal("10.00"), status="a-new-status")
    )
    charge = harness.adapter.fetch_charge("conf-2")
    assert charge is not None
    _require(
        charge.succeeded is False,
        "an unrecognised status was reported as a success",
    )
    _require(
        charge.status == "a-new-status",
        "the processor's own status was not preserved for reconciliation",
    )


def _transport_failure_is_unknown(harness: AdapterHarness) -> None:
    """"We could not reach the processor" is not "the charge did not happen".

    The failure: treating a timeout as a decline, retrying, and charging the
    customer twice. This is the payment twin of chunk 11's lost supplier
    response.
    """
    harness.fail_transport()
    result = harness.adapter.fetch_charge("conf-3")
    _require(
        result is None,
        "a transport failure was reported as a definite outcome",
    )


def _forged_signature_is_refused(harness: AdapterHarness) -> None:
    """The whole basis for believing a webhook."""
    body = b'{"event":"charge.success","data":{"reference":"conf-4"}}'
    _require(
        harness.adapter.verify_webhook(body, {"x-signature": "0" * 128}) is False,
        "a forged signature verified",
    )
    _require(
        harness.adapter.verify_webhook(body, {}) is False,
        "a missing signature verified",
    )


def _tampered_body_is_refused(harness: AdapterHarness) -> None:
    """Keep the signature, change the amount.

    The failure this catches is verifying a re-serialised body rather than the
    raw bytes, which silently accepts an altered payload.
    """
    original = b'{"amount":500000}'
    headers = harness.sign(original)
    _require(
        harness.adapter.verify_webhook(original, headers) is True,
        "a correctly signed body did not verify",
    )
    _require(
        harness.adapter.verify_webhook(b'{"amount":1}', headers) is False,
        "a tampered body verified against the original signature",
    )


def _reordered_webhooks_are_independently_verifiable(
    harness: AdapterHarness,
) -> None:
    """Delivery order is not guaranteed, and each message stands alone.

    The failure: verification that depends on sequence state, so an
    out-of-order delivery is rejected as a forgery and a real payment is lost.
    """
    first = b'{"event":"charge.pending","data":{"reference":"conf-5"}}'
    second = b'{"event":"charge.success","data":{"reference":"conf-5"}}'
    first_headers = harness.sign(first)
    second_headers = harness.sign(second)

    _require(
        harness.adapter.verify_webhook(second, second_headers) is True,
        "the later webhook did not verify when delivered first",
    )
    _require(
        harness.adapter.verify_webhook(first, first_headers) is True,
        "the earlier webhook did not verify when delivered second",
    )


def _abandonment_is_reported_not_guessed(harness: AdapterHarness) -> None:
    """An abandoned checkout is a real, terminal, non-success outcome.

    The failure: leaving it `pending` forever, so a customer who walked away
    holds a reservation nobody releases.
    """
    harness.respond(
        _envelope(harness, "conf-6", Decimal("10.00"), status="abandoned")
    )
    charge = harness.adapter.fetch_charge("conf-6")
    assert charge is not None
    _require(charge.succeeded is False, "an abandoned checkout read as a success")


def _decline_is_reported(harness: AdapterHarness) -> None:
    harness.respond(_envelope(harness, "conf-7", Decimal("10.00"), status="failed"))
    charge = harness.adapter.fetch_charge("conf-7")
    assert charge is not None
    _require(charge.succeeded is False, "a decline read as a success")


def _unsupported_currency_is_refused(harness: AdapterHarness) -> None:
    """An adapter must refuse what it cannot price, rather than convert.

    The failure: an adapter that quietly charges in its own currency, which is
    an unapproved foreign-exchange decision made in an integration layer.
    """
    unsupported = "KWD" if harness.currency != "KWD" else "JPY"
    try:
        harness.adapter.create_checkout(
            "conf-8",
            Decimal("10.000"),
            unsupported,
            PaymentMethodKind.CARD,
            {},
        )
    except PaymentRoutingError:
        return
    raise ConformanceFailure(
        f"adapter accepted {unsupported}, which it does not support"
    )


def _our_key_is_the_reference(harness: AdapterHarness) -> None:
    """The reference the processor knows must be the key we chose.

    The failure: an adapter that lets the processor name the charge, so a lost
    response leaves us with nothing to reconcile against.
    """
    harness.respond(_checkout_envelope(harness, "conf-9"))
    session = harness.adapter.create_checkout(
        "conf-9", Decimal("10.00"), harness.currency, PaymentMethodKind.CARD, {}
    )
    _require(
        session.processor_reference == "conf-9",
        "the adapter did not use our idempotency key as the processor reference",
    )


CASES: tuple[ConformanceCase, ...] = (
    ConformanceCase(
        "amount round-trips",
        "a one-way minor-unit conversion is a hundredfold pricing error",
        _amount_round_trips,
    ),
    ConformanceCase(
        "unknown status is not success",
        "otherwise every future status a processor invents fulfils an order",
        _unknown_status_is_not_success,
    ),
    ConformanceCase(
        "transport failure is unknown",
        "a timeout treated as a decline charges the customer twice",
        _transport_failure_is_unknown,
    ),
    ConformanceCase(
        "forged signature is refused",
        "the whole basis for believing a webhook",
        _forged_signature_is_refused,
    ),
    ConformanceCase(
        "tampered body is refused",
        "verifying a re-serialised body accepts an altered payload",
        _tampered_body_is_refused,
    ),
    ConformanceCase(
        "reordered webhooks verify independently",
        "sequence-dependent verification loses a real payment",
        _reordered_webhooks_are_independently_verifiable,
    ),
    ConformanceCase(
        "abandonment is terminal",
        "otherwise a walked-away customer holds a reservation forever",
        _abandonment_is_reported_not_guessed,
    ),
    ConformanceCase(
        "decline is reported",
        "a decline read as success fulfils an unpaid order",
        _decline_is_reported,
    ),
    ConformanceCase(
        "unsupported currency is refused",
        "converting is an unapproved FX decision made in an integration layer",
        _unsupported_currency_is_refused,
    ),
    ConformanceCase(
        "our key is the processor reference",
        "otherwise a lost response leaves nothing to reconcile against",
        _our_key_is_the_reference,
    ),
)


# --- envelope helpers --------------------------------------------------------
#
# Shaped like Paystack's today because that is the only adapter that exists. A
# second processor supplies its own via the harness rather than bending to
# this shape -- which is the point of the harness carrying `respond`.


def _envelope(
    harness: AdapterHarness, reference: str, amount: Decimal, status: str
) -> dict[str, Any]:
    from app.money import currency_exponent

    return {
        "status": True,
        "data": {
            "reference": reference,
            "status": status,
            "amount": int(amount.scaleb(currency_exponent(harness.currency))),
            "currency": harness.currency,
        },
    }


def _success_envelope(
    harness: AdapterHarness, reference: str, amount: Decimal
) -> dict[str, Any]:
    return _envelope(harness, reference, amount, "success")


def _checkout_envelope(harness: AdapterHarness, reference: str) -> dict[str, Any]:
    return {
        "status": True,
        "data": {
            "reference": reference,
            "authorization_url": f"https://checkout.example/{reference}",
            "access_code": "ac_conformance",
        },
    }
