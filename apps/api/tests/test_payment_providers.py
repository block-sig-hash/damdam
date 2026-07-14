import hashlib
import hmac
import json
from decimal import Decimal

import httpx
import pytest

from app.config import Settings
from app.payments.providers import (
    FlutterwaveProvider,
    PaymentInitialization,
    PaymentProviderError,
    PaystackProvider,
)


def _initialization() -> PaymentInitialization:
    return PaymentInitialization(
        reference="retail-reference",
        amount_ngn=Decimal("145000.00"),
        customer_email="pilgrim@example.com",
        channels=("card", "bank_transfer", "ussd", "mobile_money"),
        callback_url="https://damdam.app/payment/callback",
    )


def test_paystack_initialization_uses_kobo_and_generic_checkout(monkeypatch) -> None:
    """AC-09.1/2: Paystack receives all rails without leaking its shape upstream."""
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs):
        captured.update({"url": url, **kwargs})
        return httpx.Response(
            200,
            json={"data": {"authorization_url": "https://checkout.paystack.test/ref"}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = PaystackProvider(Settings(paystack_secret_key="paystack-secret"))

    checkout = provider.initialize(_initialization())

    assert checkout.processor == "paystack"
    assert checkout.checkout_url == "https://checkout.paystack.test/ref"
    assert captured["json"]["amount"] == 14_500_000  # type: ignore[index]
    assert captured["json"]["channels"] == [  # type: ignore[index]
        "card",
        "bank_transfer",
        "ussd",
    ]


def test_paystack_webhook_verifies_raw_body_hmac_sha512() -> None:
    """AC-09.7: Paystack callbacks require HMAC SHA512 over the raw body."""
    settings = Settings(paystack_secret_key="paystack-secret")
    provider = PaystackProvider(settings)
    body = json.dumps(
        {
            "event": "charge.success",
            "data": {
                "reference": "ref",
                "amount": 14_500_000,
                "currency": "NGN",
                "channel": "ussd",
            },
        }
    ).encode()
    signature = hmac.new(b"paystack-secret", body, hashlib.sha512).hexdigest()

    event = provider.parse_webhook(body, {"x-paystack-signature": signature})

    assert event is not None
    assert event.amount_ngn == Decimal("145000")
    assert event.payment_method == "ussd"
    with pytest.raises(PaymentProviderError, match="signature"):
        provider.parse_webhook(body, {"x-paystack-signature": "wrong"})


def test_flutterwave_webhook_verifies_hash_and_parses_success() -> None:
    """AC-09.7: Flutterwave callbacks use the same neutral event contract."""
    provider = FlutterwaveProvider(
        Settings(flutterwave_webhook_hash="flutterwave-verification-hash")
    )
    body = json.dumps(
        {
            "event": "charge.completed",
            "data": {
                "status": "successful",
                "tx_ref": "ref",
                "amount": 145000,
                "currency": "NGN",
                "payment_type": "banktransfer",
            },
        }
    ).encode()

    event = provider.parse_webhook(
        body, {"verif-hash": "flutterwave-verification-hash"}
    )

    assert event is not None
    assert event.processor == "flutterwave"
    assert event.processor_reference == "ref"
    with pytest.raises(PaymentProviderError, match="signature"):
        provider.parse_webhook(body, {"verif-hash": "wrong"})
