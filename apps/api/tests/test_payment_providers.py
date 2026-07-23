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
    """AC-09.7: verify the raw body, then retain only audit-safe fields."""
    settings = Settings(paystack_secret_key="paystack-secret")
    provider = PaystackProvider(settings)
    body = json.dumps(
        {
            "event": "charge.success",
            "data": {
                "id": 302961,
                "domain": "live",
                "status": "success",
                "reference": "ref",
                "amount": 14_500_000,
                "currency": "NGN",
                "channel": "ussd",
                "paid_at": "2026-07-23T12:34:56.000Z",
                "created_at": "2026-07-23T12:30:00.000Z",
                "fees": 217500,
                "gateway_response": "Successful",
                "ip_address": "203.0.113.9",
                "metadata": {"internal_note": "do not retain"},
                "customer": {
                    "email": "pilgrim@example.com",
                    "phone": "+2348012345678",
                    "customer_code": "CUS_sensitive",
                },
                "authorization": {
                    "authorization_code": "AUTH_reusable_secret",
                    "bin": "408408",
                    "last4": "4081",
                    "bank": "TEST BANK",
                },
            },
        }
    ).encode()
    signature = hmac.new(b"paystack-secret", body, hashlib.sha512).hexdigest()

    event = provider.parse_webhook(body, {"x-paystack-signature": signature})

    assert event is not None
    assert event.amount_ngn == Decimal("145000")
    assert event.payment_method == "ussd"
    assert event.payload == {
        "event": "charge.success",
        "data": {
            "id": 302961,
            "domain": "live",
            "status": "success",
            "reference": "ref",
            "amount": 14_500_000,
            "currency": "NGN",
            "channel": "ussd",
            "paid_at": "2026-07-23T12:34:56.000Z",
            "created_at": "2026-07-23T12:30:00.000Z",
            "fees": 217500,
        },
    }
    with pytest.raises(PaymentProviderError, match="signature"):
        provider.parse_webhook(body, {"x-paystack-signature": "wrong"})


def test_flutterwave_webhook_verifies_hash_and_parses_success() -> None:
    """AC-09.7: Flutterwave retains reconciliation fields, not payer PII."""
    provider = FlutterwaveProvider(
        Settings(flutterwave_webhook_hash="flutterwave-verification-hash")
    )
    body = json.dumps(
        {
            "event": "charge.completed",
            "data": {
                "id": 285959875,
                "status": "successful",
                "tx_ref": "ref",
                "flw_ref": "FLW-MOCK-REF",
                "amount": 145000,
                "charged_amount": 145000,
                "currency": "NGN",
                "app_fee": 2100,
                "merchant_fee": 0,
                "processor_response": "Approved",
                "auth_model": "PIN",
                "payment_type": "banktransfer",
                "created_at": "2026-07-23T12:34:56.000Z",
                "account_id": 12345,
                "ip": "203.0.113.10",
                "device_fingerprint": "device-sensitive",
                "customer": {
                    "email": "pilgrim@example.com",
                    "phone_number": "+221771234567",
                    "name": "Sensitive Name",
                },
                "card": {
                    "first_6digits": "539983",
                    "last_4digits": "8381",
                    "issuer": "TEST BANK",
                },
                "meta": {"internal_note": "do not retain"},
            },
        }
    ).encode()

    event = provider.parse_webhook(
        body, {"verif-hash": "flutterwave-verification-hash"}
    )

    assert event is not None
    assert event.processor == "flutterwave"
    assert event.processor_reference == "ref"
    assert event.payload == {
        "event": "charge.completed",
        "data": {
            "id": 285959875,
            "status": "successful",
            "tx_ref": "ref",
            "flw_ref": "FLW-MOCK-REF",
            "amount": 145000,
            "charged_amount": 145000,
            "currency": "NGN",
            "app_fee": 2100,
            "merchant_fee": 0,
            "payment_type": "banktransfer",
            "created_at": "2026-07-23T12:34:56.000Z",
            "account_id": 12345,
        },
    }
    with pytest.raises(PaymentProviderError, match="signature"):
        provider.parse_webhook(body, {"verif-hash": "wrong"})
