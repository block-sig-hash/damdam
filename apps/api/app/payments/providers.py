import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

import httpx

from app.config import Settings


class PaymentProviderError(Exception):
    pass


@dataclass(frozen=True)
class PaymentInitialization:
    reference: str
    amount_ngn: Decimal
    customer_email: str
    channels: tuple[str, ...]
    callback_url: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PaymentCheckout:
    processor: str
    processor_reference: str
    checkout_url: str


@dataclass(frozen=True)
class PaymentWebhookEvent:
    processor: str
    processor_reference: str
    amount_ngn: Decimal
    payment_method: str
    payload: dict[str, object]


class PaymentProvider(Protocol):
    name: str

    def initialize(self, payment: PaymentInitialization) -> PaymentCheckout: ...

    def parse_webhook(
        self, body: bytes, headers: Mapping[str, str]
    ) -> PaymentWebhookEvent | None: ...


def _json_object(body: bytes) -> dict[str, object]:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PaymentProviderError("invalid webhook payload") from exc
    if not isinstance(payload, dict):
        raise PaymentProviderError("invalid webhook payload")
    return payload


def _audit_payload(
    event: object, data: dict[str, object], retained_fields: tuple[str, ...]
) -> dict[str, object]:
    """Build the long-lived financial evidence without payer/instrument PII."""
    return {
        "event": event,
        "data": {key: data[key] for key in retained_fields if key in data},
    }


class PaystackProvider:
    name = "paystack"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def initialize(self, payment: PaymentInitialization) -> PaymentCheckout:
        if not self.settings.paystack_secret_key:
            raise PaymentProviderError("Paystack is not configured")
        try:
            response = httpx.post(
                f"{self.settings.paystack_base_url.rstrip('/')}/transaction/initialize",
                headers={
                    "Authorization": f"Bearer {self.settings.paystack_secret_key}"
                },
                json={
                    "email": payment.customer_email,
                    "amount": int(payment.amount_ngn * 100),
                    "currency": "NGN",
                    "reference": payment.reference,
                    "callback_url": payment.callback_url,
                    # Paystack's Nigerian checkout has no mobile-money rail;
                    # OPay/PalmPay users pay through its bank-transfer rail.
                    "channels": [
                        channel
                        for channel in payment.channels
                        if channel != "mobile_money"
                    ],
                    "metadata": json.dumps(payment.metadata),
                },
                timeout=self.settings.payment_request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            url = payload["data"]["authorization_url"]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise PaymentProviderError("Paystack initialization failed") from exc
        return PaymentCheckout(self.name, payment.reference, str(url))

    def parse_webhook(
        self, body: bytes, headers: Mapping[str, str]
    ) -> PaymentWebhookEvent | None:
        if not self.settings.paystack_secret_key:
            raise PaymentProviderError("invalid webhook signature")
        provided = headers.get("x-paystack-signature", "")
        expected = hmac.new(
            self.settings.paystack_secret_key.encode(), body, hashlib.sha512
        ).hexdigest()
        if not provided or not hmac.compare_digest(provided, expected):
            raise PaymentProviderError("invalid webhook signature")
        payload = _json_object(body)
        if payload.get("event") != "charge.success":
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            raise PaymentProviderError("invalid webhook payload")
        if data.get("currency") != "NGN":
            raise PaymentProviderError("invalid webhook payload")
        try:
            return PaymentWebhookEvent(
                processor=self.name,
                processor_reference=str(data["reference"]),
                amount_ngn=Decimal(str(data["amount"])) / 100,
                payment_method=str(data.get("channel", "card")),
                payload=_audit_payload(
                    payload.get("event"),
                    data,
                    (
                        "id",
                        "domain",
                        "status",
                        "reference",
                        "amount",
                        "currency",
                        "channel",
                        "paid_at",
                        "created_at",
                        "fees",
                    ),
                ),
            )
        except (KeyError, ValueError) as exc:
            raise PaymentProviderError("invalid webhook payload") from exc


class FlutterwaveProvider:
    name = "flutterwave"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def initialize(self, payment: PaymentInitialization) -> PaymentCheckout:
        if not self.settings.flutterwave_secret_key:
            raise PaymentProviderError("Flutterwave is not configured")
        options = {
            "card": "card",
            "bank_transfer": "banktransfer",
            "ussd": "ussd",
            "mobile_money": "opay",
        }
        try:
            response = httpx.post(
                f"{self.settings.flutterwave_base_url.rstrip('/')}/v3/payments",
                headers={
                    "Authorization": f"Bearer {self.settings.flutterwave_secret_key}"
                },
                json={
                    "tx_ref": payment.reference,
                    "amount": str(payment.amount_ngn),
                    "currency": "NGN",
                    "redirect_url": payment.callback_url,
                    "payment_options": ",".join(
                        options[channel] for channel in payment.channels
                    ),
                    "customer": {"email": payment.customer_email},
                    "meta": payment.metadata,
                },
                timeout=self.settings.payment_request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            url = payload["data"]["link"]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise PaymentProviderError("Flutterwave initialization failed") from exc
        return PaymentCheckout(self.name, payment.reference, str(url))

    def parse_webhook(
        self, body: bytes, headers: Mapping[str, str]
    ) -> PaymentWebhookEvent | None:
        provided = headers.get("verif-hash", "")
        expected = self.settings.flutterwave_webhook_hash
        if not provided or not expected or not hmac.compare_digest(provided, expected):
            raise PaymentProviderError("invalid webhook signature")
        payload = _json_object(body)
        if payload.get("event") != "charge.completed":
            return None
        data = payload.get("data")
        if not isinstance(data, dict) or data.get("status") != "successful":
            return None
        if data.get("currency") != "NGN":
            raise PaymentProviderError("invalid webhook payload")
        try:
            return PaymentWebhookEvent(
                processor=self.name,
                processor_reference=str(data["tx_ref"]),
                amount_ngn=Decimal(str(data["amount"])),
                payment_method=str(data.get("payment_type", "card")),
                payload=_audit_payload(
                    payload.get("event"),
                    data,
                    (
                        "id",
                        "status",
                        "tx_ref",
                        "flw_ref",
                        "amount",
                        "charged_amount",
                        "currency",
                        "app_fee",
                        "merchant_fee",
                        "payment_type",
                        "created_at",
                        "account_id",
                    ),
                ),
            )
        except (KeyError, ValueError) as exc:
            raise PaymentProviderError("invalid webhook payload") from exc
