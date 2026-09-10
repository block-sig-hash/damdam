"""Paystack, behind the provider-neutral contract (US-33, chunk 12).

`prd.md` §10 retains Paystack **conditionally, for approved local NGN**, and
this adapter is written to that: it declines anything that is not NGN rather
than attempting a conversion, and it collects nothing at all until a merchant
account is marked live, which needs an approval reference D4 has not produced.

The legacy adapter in `app/payments/providers.py` is untouched and still serves
the legacy purchase path. This is the one new orders use, and the two coexist
until the chunk that retires the legacy path.

**Vendor behaviour is documented, not assumed.** Every claim below names where
it comes from and when it was checked, because a mock agreeing with itself is
not evidence of anything.

Source: Paystack API reference — Transactions (`/transaction/initialize`,
`/transaction/verify/{reference}`) and the webhook signature scheme
(`x-paystack-signature`, HMAC SHA-512 over the raw body with the secret key).
Checked **10 September 2026** against the public documentation. No live or
sandbox call has been made from this branch.
"""

import json
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.auth.models import utc_now
from app.money import currency_exponent, round_money
from app.payments.contract import PaymentMethodKind
from app.payments.routing import (
    CheckoutSession,
    PaymentRoutingError,
    ProcessorCharge,
    verify_hmac_sha512,
)

#: Paystack's documented terminal statuses. `success` is the only one that
#: means money moved; everything else is explicitly not a success rather than
#: "anything we do not recognise is a failure", because an unrecognised status
#: is an unknown and unknowns reconcile.
SUCCESS_STATUS = "success"
DEFINITE_FAILURES = frozenset({"failed", "abandoned", "reversed"})


class PaystackAdapter:
    """Hosted checkout, verified webhooks, and a real `fetch_charge`.

    The transport is injected rather than imported so the conformance suite can
    exercise every branch — including the ones a live sandbox will not produce
    on demand, like a reordered webhook or an ambiguous status.
    """

    name = "paystack"
    supported_currencies = frozenset({"NGN"})

    def __init__(
        self,
        secret_key: str,
        transport: Callable[[str, str, dict[str, Any]], dict[str, Any]],
        base_url: str = "https://api.paystack.co",
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.secret_key = secret_key
        self.transport = transport
        self.base_url = base_url.rstrip("/")
        self.clock = clock

    # --- checkout ---------------------------------------------------------

    def create_checkout(
        self,
        idempotency_key: str,
        amount: Decimal,
        currency: str,
        method: PaymentMethodKind,
        metadata: dict[str, Any],
    ) -> CheckoutSession:
        """Hosted checkout. Raw card data never reaches DamDam.

        `security.md` requires card details to stay outside our systems, and a
        hosted page is how that is true rather than promised: the customer types
        their card on Paystack's page and we receive a reference.
        """
        if currency not in self.supported_currencies:
            # No conversion. Quietly charging NGN for a GBP order would be a
            # foreign-exchange decision this product has not made.
            raise PaymentRoutingError(
                "currency_not_supported",
                f"{self.name} is retained for NGN only; got {currency}",
            )

        # Paystack takes the amount in the currency's minor unit as an integer.
        # Deriving the exponent rather than hardcoding 100 keeps this correct if
        # the adapter is ever pointed at a zero- or three-exponent currency.
        minor = int(
            round_money(amount, currency).scaleb(currency_exponent(currency))
        )
        response = self.transport(
            "POST",
            f"{self.base_url}/transaction/initialize",
            {
                "amount": minor,
                "currency": currency,
                "reference": idempotency_key,
                "channels": _channels_for(method),
                "metadata": metadata,
            },
        )
        data = response.get("data") or {}
        reference = data.get("reference")
        url = data.get("authorization_url")
        if not reference or not url:
            raise PaymentRoutingError(
                "checkout_unavailable", "Paystack returned no checkout session"
            )
        return CheckoutSession(
            processor_reference=str(reference),
            redirect_url=str(url),
            metadata={"access_code": data.get("access_code")},
        )

    # --- webhooks ---------------------------------------------------------

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        """HMAC SHA-512 over the **raw** body, per Paystack's documentation.

        Raw, not re-serialised. Any normalisation — key order, whitespace, a
        JSON round trip — changes the bytes and the signature stops matching,
        which is exactly what an attacker would like us to conclude is a
        Paystack bug.
        """
        signature = ""
        for key, value in headers.items():
            if key.lower() == "x-paystack-signature":
                signature = value
                break
        return verify_hmac_sha512(self.secret_key, raw_body, signature)

    def parse_webhook(self, raw_body: bytes) -> ProcessorCharge:
        payload = json.loads(raw_body.decode())
        data = payload.get("data") or {}
        return self._charge_from(data)

    # --- reconciliation ---------------------------------------------------

    def fetch_charge(self, processor_reference: str) -> ProcessorCharge | None:
        """`GET /transaction/verify/{reference}` — the authoritative answer.

        Returns `None` when Paystack cannot say, which routes to review rather
        than to a guess. A transport failure is not "the charge did not
        happen".
        """
        try:
            response = self.transport(
                "GET",
                f"{self.base_url}/transaction/verify/{processor_reference}",
                {},
            )
        except Exception:
            return None
        if not response.get("status"):
            return None
        data = response.get("data") or {}
        if not data:
            return None
        return self._charge_from(data)

    def _charge_from(self, data: dict[str, Any]) -> ProcessorCharge:
        currency = str(data.get("currency") or "NGN")
        minor = int(data.get("amount") or 0)
        status = str(data.get("status") or "unknown")
        return ProcessorCharge(
            processor_reference=str(data.get("reference") or ""),
            status=status,
            # Back out of the minor unit with the same exponent we sent.
            amount=round_money(
                Decimal(minor).scaleb(-currency_exponent(currency)), currency
            ),
            currency=currency,
            succeeded=status == SUCCESS_STATUS,
        )


def _channels_for(method: PaymentMethodKind) -> list[str]:
    """Paystack channel names for a method.

    Nigerian checkout has no mobile-money rail; OPay and PalmPay customers pay
    through the bank-transfer rail, which the legacy adapter already documents.
    """
    if method is PaymentMethodKind.CARD:
        return ["card"]
    if method is PaymentMethodKind.BANK_TRANSFER:
        return ["bank_transfer", "bank"]
    if method is PaymentMethodKind.USSD:
        return ["ussd"]
    return ["card", "bank_transfer", "bank", "ussd"]
