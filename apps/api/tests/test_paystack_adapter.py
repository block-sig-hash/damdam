"""US-33 chunk 12 — the modernized Paystack adapter.

Two things are checked here that a happy-path test would not.

**The wire format.** Paystack takes the amount in the currency's minor unit as
an integer, and the adapter derives the exponent rather than hardcoding 100.
Getting that wrong by a factor of a hundred is a silent, catastrophic pricing
bug in either direction, and it is exactly the kind of thing a mock built from
the same assumption would agree with.

**The refusals.** Anything that is not NGN, and any status that is not
`success`, are refused rather than interpreted.

Source for the wire format and signature scheme: Paystack API reference —
Transactions and webhook verification (`x-paystack-signature`, HMAC SHA-512 over
the raw body). Checked **10 September 2026** against the public documentation.
No live or sandbox call has been made from this branch, and none of this is
evidence that Paystack behaves as documented.
"""

import hashlib
import hmac
import json
from decimal import Decimal

import pytest

from app.payments.contract import PaymentMethodKind
from app.payments.paystack_adapter import PaystackAdapter
from app.payments.routing import PaymentRoutingError

SECRET = "sk_test_never_a_real_key"


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.response: dict = {}
        self.raises = False

    def __call__(self, method: str, url: str, body: dict) -> dict:
        self.calls.append((method, url, body))
        if self.raises:
            raise ConnectionError("network went away")
        return self.response


def _adapter(transport: FakeTransport) -> PaystackAdapter:
    return PaystackAdapter(SECRET, transport)


def _initialize_response(reference: str = "ref-1") -> dict:
    return {
        "status": True,
        "data": {
            "reference": reference,
            "authorization_url": f"https://checkout.paystack.com/{reference}",
            "access_code": "ac_1",
        },
    }


class TestCheckout:
    @pytest.mark.parametrize(
        ("amount", "currency", "minor"),
        [
            ("5000.00", "NGN", 500000),
            ("0.01", "NGN", 1),
            ("1234.56", "NGN", 123456),
        ],
    )
    def test_the_amount_is_sent_in_the_currency_minor_unit(
        self, amount, currency, minor
    ):
        transport = FakeTransport()
        transport.response = _initialize_response()
        _adapter(transport).create_checkout(
            "key-1", Decimal(amount), currency, PaymentMethodKind.CARD, {}
        )
        assert transport.calls[0][2]["amount"] == minor

    def test_our_idempotency_key_is_the_processor_reference(self):
        # So a reconciliation can ask about the charge we made, by the name we
        # gave it, without having stored anything a crash could take with it.
        transport = FakeTransport()
        transport.response = _initialize_response("key-1")
        session = _adapter(transport).create_checkout(
            "key-1", Decimal("100.00"), "NGN", PaymentMethodKind.CARD, {}
        )
        assert transport.calls[0][2]["reference"] == "key-1"
        assert session.processor_reference == "key-1"

    def test_a_non_ngn_currency_is_refused_rather_than_converted(self):
        """prd.md §10 retains Paystack conditionally, for approved local NGN.

        Quietly charging NGN for a GBP order would be a foreign-exchange
        decision this product has not made.
        """
        transport = FakeTransport()
        with pytest.raises(PaymentRoutingError) as excinfo:
            _adapter(transport).create_checkout(
                "key-1", Decimal("100.00"), "GBP", PaymentMethodKind.CARD, {}
            )
        assert excinfo.value.code == "currency_not_supported"
        assert transport.calls == []

    def test_a_response_without_a_checkout_url_is_an_error_not_a_session(self):
        transport = FakeTransport()
        transport.response = {"status": True, "data": {}}
        with pytest.raises(PaymentRoutingError) as excinfo:
            _adapter(transport).create_checkout(
                "key-1", Decimal("100.00"), "NGN", PaymentMethodKind.CARD, {}
            )
        assert excinfo.value.code == "checkout_unavailable"

    def test_bank_transfer_uses_the_bank_rails(self):
        # Nigerian checkout has no mobile-money rail; OPay and PalmPay
        # customers pay through bank transfer.
        transport = FakeTransport()
        transport.response = _initialize_response()
        _adapter(transport).create_checkout(
            "key-1",
            Decimal("100.00"),
            "NGN",
            PaymentMethodKind.BANK_TRANSFER,
            {},
        )
        assert "bank_transfer" in transport.calls[0][2]["channels"]
        assert "card" not in transport.calls[0][2]["channels"]


class TestWebhooks:
    def _signed(self, body: dict) -> tuple[bytes, dict[str, str]]:
        raw = json.dumps(body).encode()
        signature = hmac.new(SECRET.encode(), raw, hashlib.sha512).hexdigest()
        return raw, {"x-paystack-signature": signature}

    def test_a_correctly_signed_webhook_verifies(self):
        raw, headers = self._signed({"event": "charge.success"})
        assert _adapter(FakeTransport()).verify_webhook(raw, headers) is True

    def test_the_header_is_matched_case_insensitively(self):
        # Proxies normalise header case, and a signature check that misses the
        # header fails closed on legitimate traffic.
        raw, _ = self._signed({"event": "charge.success"})
        signature = hmac.new(SECRET.encode(), raw, hashlib.sha512).hexdigest()
        assert (
            _adapter(FakeTransport()).verify_webhook(
                raw, {"X-Paystack-Signature": signature}
            )
            is True
        )

    def test_a_forged_signature_is_refused(self):
        raw, _ = self._signed({"event": "charge.success"})
        assert (
            _adapter(FakeTransport()).verify_webhook(
                raw, {"x-paystack-signature": "0" * 128}
            )
            is False
        )

    def test_re_serialising_the_body_would_break_verification(self):
        """Why the raw bytes are used, and not a parsed-and-redumped payload.

        Any normalisation changes the bytes and the signature stops matching --
        which looks like a Paystack bug and is in fact us verifying something
        the sender never signed.
        """
        raw, headers = self._signed({"b": 2, "a": 1})
        adapter = _adapter(FakeTransport())
        assert adapter.verify_webhook(raw, headers) is True

        reserialised = json.dumps(json.loads(raw), sort_keys=True).encode()
        assert reserialised != raw
        assert adapter.verify_webhook(reserialised, headers) is False

    def test_a_missing_header_is_refused(self):
        raw, _ = self._signed({"event": "charge.success"})
        assert _adapter(FakeTransport()).verify_webhook(raw, {}) is False

    def test_a_parsed_charge_comes_back_out_of_the_minor_unit(self):
        raw = json.dumps(
            {
                "event": "charge.success",
                "data": {
                    "reference": "key-1",
                    "status": "success",
                    "amount": 500000,
                    "currency": "NGN",
                },
            }
        ).encode()
        charge = _adapter(FakeTransport()).parse_webhook(raw)
        assert charge.amount == Decimal("5000.00")
        assert charge.succeeded is True


class TestVerification:
    def test_a_verified_success_is_reported_as_succeeded(self):
        transport = FakeTransport()
        transport.response = {
            "status": True,
            "data": {
                "reference": "key-1",
                "status": "success",
                "amount": 500000,
                "currency": "NGN",
            },
        }
        charge = _adapter(transport).fetch_charge("key-1")
        assert charge is not None
        assert charge.succeeded is True
        assert charge.amount == Decimal("5000.00")
        assert transport.calls[0][0] == "GET"

    @pytest.mark.parametrize("status", ["failed", "abandoned", "reversed"])
    def test_a_documented_failure_is_not_a_success(self, status):
        transport = FakeTransport()
        transport.response = {
            "status": True,
            "data": {
                "reference": "key-1",
                "status": status,
                "amount": 500000,
                "currency": "NGN",
            },
        }
        charge = _adapter(transport).fetch_charge("key-1")
        assert charge is not None
        assert charge.succeeded is False

    def test_an_unrecognised_status_is_not_treated_as_a_success(self):
        # And equally not silently as a failure: it comes back with the status
        # verbatim so the router records it and reconciliation decides.
        transport = FakeTransport()
        transport.response = {
            "status": True,
            "data": {
                "reference": "key-1",
                "status": "something-new",
                "amount": 500000,
                "currency": "NGN",
            },
        }
        charge = _adapter(transport).fetch_charge("key-1")
        assert charge is not None
        assert charge.succeeded is False
        assert charge.status == "something-new"

    def test_a_transport_failure_is_unknown_not_failed(self):
        """The distinction that stops a customer being charged twice.

        "We could not reach Paystack" is not "the charge did not happen".
        """
        transport = FakeTransport()
        transport.raises = True
        assert _adapter(transport).fetch_charge("key-1") is None

    def test_an_unsuccessful_api_envelope_is_unknown(self):
        transport = FakeTransport()
        transport.response = {"status": False, "message": "transaction not found"}
        assert _adapter(transport).fetch_charge("key-1") is None
