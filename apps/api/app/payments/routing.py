"""Payment routing and authoritative capture (US-33, chunk 12).

Two responsibilities, and both are about refusing things.

**Routing** picks a merchant account from seller, currency and method — never
from nationality, never from an IP address. Those are guesses about a person;
the merchant account is a fact about who may legally take their money in that
currency. Routing on a guess is how a customer in one country is charged through
an entity with no relationship to them.

**Capture** decides whether an order is paid, and it believes exactly one thing:
a webhook whose signature verifies, whose amount, currency, merchant account and
order all match what we intended. Everything else is refused.

A browser redirect can never mark an order paid. It is a message from the
customer's own browser, and anyone can navigate to a URL — the redirect is a
hint to show a spinner, not evidence that money moved.

**Live collection is disabled.** `MerchantAccount.live_enabled` defaults to
false and cannot be set true without an approval reference, because D3 and D4
are open. A passing sandbox call is not merchant approval.
"""

import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.auth.models import utc_now
from app.money import round_money
from app.orders.models import Order, PaymentState
from app.payments.contract import (
    AttemptStatus,
    ExcessPayment,
    MerchantAccount,
    PaymentAttempt,
    PaymentIntent,
    PaymentMethodKind,
)


class PaymentRoutingError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


@dataclass(frozen=True)
class CheckoutSession:
    """What a processor gives us to send the customer to."""

    processor_reference: str
    redirect_url: str
    #: Whatever the processor needs echoed back. Never a secret, never a card.
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ProcessorCharge:
    """A charge as the processor describes it, after verification."""

    processor_reference: str
    status: str
    amount: Decimal
    currency: str
    #: The processor's own identifier for the merchant the money went to.
    merchant_reference: str | None = None
    succeeded: bool = False


class PaymentProcessorAdapter(Protocol):
    """The whole surface a processor must present. Deliberately small.

    D4 is open, so this is written to be satisfiable by whoever is chosen
    rather than shaped around one candidate's API.
    """

    name: str

    def create_checkout(
        self,
        idempotency_key: str,
        amount: Decimal,
        currency: str,
        method: PaymentMethodKind,
        metadata: dict[str, Any],
    ) -> CheckoutSession: ...

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        """Signature check. Returns False rather than raising on a forgery."""
        ...

    def parse_webhook(self, raw_body: bytes) -> ProcessorCharge: ...

    def fetch_charge(self, processor_reference: str) -> ProcessorCharge | None:
        """Ask the processor what really happened. `None` if it cannot say."""
        ...


def verify_hmac_sha512(secret: str, raw_body: bytes, signature: str) -> bool:
    """Constant-time HMAC comparison, the shape Paystack documents.

    `compare_digest` rather than `==` because a byte-by-byte comparison leaks
    how much of a forged signature was correct, and a forger who learns that can
    find the rest one byte at a time.
    """
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature or "")


class PaymentRouter:
    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self.clock = clock

    # --- routing ----------------------------------------------------------

    def route(
        self,
        session: Session,
        seller_legal_entity_id: UUID,
        currency: str,
        method: PaymentMethodKind,
        require_live: bool = True,
    ) -> MerchantAccount:
        """Choose the merchant account by seller, currency and method.

        Not by the customer's nationality and not by their IP. Both are guesses
        about a person; a merchant account is a fact about who may take their
        money in that currency.
        """
        # `method` is recorded on the attempt rather than used for selection:
        # no processor here yet varies by it, and branching on it now would be
        # a rule nobody asked for.
        del method
        account = session.exec(
            select(MerchantAccount).where(
                MerchantAccount.legal_entity_id == seller_legal_entity_id,
                MerchantAccount.currency == currency,
            )
        ).first()
        if account is None:
            raise PaymentRoutingError(
                "no_merchant_account",
                f"no merchant account for this seller in {currency}",
            )
        if require_live and not account.live_enabled:
            # Where D3/D4 bite. A sandbox that works is not merchant approval.
            raise PaymentRoutingError(
                "live_collection_disabled",
                f"{account.processor} is not approved for live collection in "
                f"{currency}; see DECISIONS.md D3/D4",
            )
        return account

    # --- intents and attempts --------------------------------------------

    def create_intent(
        self,
        session: Session,
        order: Order,
        merchant: MerchantAccount,
        amount: Decimal,
        quote_id: UUID | None = None,
    ) -> PaymentIntent:
        existing = session.exec(
            select(PaymentIntent).where(PaymentIntent.order_id == order.id)
        ).first()
        if existing is not None:
            return existing
        if merchant.currency != order.currency:
            raise PaymentRoutingError("currency_mismatch")

        intent = PaymentIntent(
            order_id=order.id,
            quote_id=quote_id,
            seller_legal_entity_id=order.seller_legal_entity_id,
            merchant_account_id=merchant.id,
            currency=order.currency,
            amount=round_money(amount, order.currency),
            created_at=self.clock(),
        )
        session.add(intent)
        session.flush()
        return intent

    def begin_attempt(
        self,
        session: Session,
        intent: PaymentIntent,
        merchant: MerchantAccount,
        method: PaymentMethodKind,
    ) -> PaymentAttempt:
        """Start one try at collecting. Refused if one already succeeded."""
        succeeded = session.exec(
            select(PaymentAttempt).where(
                PaymentAttempt.intent_id == intent.id,
                PaymentAttempt.status == AttemptStatus.SUCCEEDED,
            )
        ).first()
        if succeeded is not None:
            raise PaymentRoutingError("already_paid")

        previous = session.exec(
            select(PaymentAttempt).where(PaymentAttempt.intent_id == intent.id)
        ).all()
        attempt = PaymentAttempt(
            intent_id=intent.id,
            processor=merchant.processor,
            method=method,
            idempotency_key=f"intent:{intent.id}:attempt:{len(previous) + 1}",
            currency=intent.currency,
            amount=intent.amount,
            status=AttemptStatus.CREATED,
            created_at=self.clock(),
        )
        session.add(attempt)
        session.flush()
        return attempt

    # --- capture ----------------------------------------------------------

    def capture(
        self,
        session: Session,
        charge: ProcessorCharge,
        processor: str,
        raw_payload: dict[str, Any] | None = None,
    ) -> PaymentAttempt | ExcessPayment:
        """Turn a verified processor charge into a paid order, or into excess.

        Everything is re-checked against what *we* intended, because a webhook
        is a claim by an external party about our money:

        - the attempt exists and belongs to this processor;
        - the amount matches exactly;
        - the currency matches;
        - the merchant account matches;
        - no other attempt on the intent has already succeeded.

        A charge that fails the last check is **recorded as excess, not
        dropped**. The money may already have left the customer's account, and
        refusing to record it would be losing it.
        """
        if not charge.succeeded:
            return self._record_failure(session, charge, processor)

        attempt = session.exec(
            select(PaymentAttempt).where(
                PaymentAttempt.processor == processor,
                PaymentAttempt.idempotency_key == charge.processor_reference,
            )
        ).first()
        if attempt is None:
            attempt = session.exec(
                select(PaymentAttempt).where(
                    PaymentAttempt.processor == processor,
                    PaymentAttempt.processor_reference == charge.processor_reference,
                )
            ).first()
        if attempt is None:
            return self._record_excess(
                session,
                None,
                processor,
                charge,
                "charge does not match any known payment attempt",
                raw_payload,
            )

        if attempt.status is AttemptStatus.SUCCEEDED:
            # A replayed webhook for a charge we already captured. Nothing to
            # do, and nothing wrong.
            return attempt

        intent = session.get(PaymentIntent, attempt.intent_id)
        if intent is None:  # pragma: no cover - FK guarantees this
            raise PaymentRoutingError("intent_not_found")

        mismatches = []
        if round_money(charge.amount, intent.currency) != intent.amount:
            mismatches.append(
                f"amount {charge.amount} != intended {intent.amount}"
            )
        if charge.currency != intent.currency:
            mismatches.append(
                f"currency {charge.currency} != intended {intent.currency}"
            )
        merchant = session.get(MerchantAccount, intent.merchant_account_id)
        if merchant is None:  # pragma: no cover
            raise PaymentRoutingError("merchant_not_found")
        if (
            charge.merchant_reference is not None
            and merchant.approval_reference is not None
            and charge.merchant_reference != merchant.approval_reference
        ):
            mismatches.append("merchant account does not match the intent")

        if mismatches:
            # Do not fulfil, do not discard. Somebody paid something; what it
            # was needs a human.
            return self._record_excess(
                session,
                intent.id,
                processor,
                charge,
                "; ".join(mismatches),
                raw_payload,
            )

        other_success = session.exec(
            select(PaymentAttempt).where(
                PaymentAttempt.intent_id == intent.id,
                PaymentAttempt.status == AttemptStatus.SUCCEEDED,
                col(PaymentAttempt.id) != attempt.id,
            )
        ).first()
        if other_success is not None:
            return self._record_excess(
                session,
                intent.id,
                processor,
                charge,
                "order already paid by another attempt",
                raw_payload,
            )

        now = self.clock()
        attempt.status = AttemptStatus.SUCCEEDED
        attempt.processor_reference = charge.processor_reference
        attempt.processor_status = charge.status
        attempt.captured_at = now
        session.add(attempt)

        order = session.get(Order, intent.order_id)
        if order is not None:
            order.payment_state = PaymentState.PAID
            session.add(order)
        try:
            session.flush()
        except IntegrityError as exc:
            # `ux_payment_attempts_one_success` -- a concurrent capture won.
            session.rollback()
            raise PaymentRoutingError("already_paid") from exc
        return attempt

    def _record_failure(
        self, session: Session, charge: ProcessorCharge, processor: str
    ) -> PaymentAttempt:
        attempt = session.exec(
            select(PaymentAttempt).where(
                PaymentAttempt.processor == processor,
                PaymentAttempt.idempotency_key == charge.processor_reference,
            )
        ).first()
        if attempt is None:
            raise PaymentRoutingError("attempt_not_found")
        attempt.status = AttemptStatus.FAILED
        attempt.processor_status = charge.status
        attempt.processor_reference = charge.processor_reference
        session.add(attempt)
        session.flush()
        return attempt

    def _record_excess(
        self,
        session: Session,
        intent_id: UUID | None,
        processor: str,
        charge: ProcessorCharge,
        reason: str,
        raw_payload: dict[str, Any] | None,
    ) -> ExcessPayment:
        existing = session.exec(
            select(ExcessPayment).where(
                ExcessPayment.processor == processor,
                ExcessPayment.processor_reference == charge.processor_reference,
            )
        ).first()
        if existing is not None:
            return existing
        excess = ExcessPayment(
            intent_id=intent_id,
            processor=processor,
            processor_reference=charge.processor_reference,
            currency=charge.currency,
            amount=round_money(charge.amount, charge.currency),
            reason=reason[:500],
            raw_payload=raw_payload,
            created_at=self.clock(),
        )
        session.add(excess)
        session.flush()
        return excess

    # --- reconciliation ---------------------------------------------------

    def reconcile(
        self,
        session: Session,
        attempt: PaymentAttempt,
        adapter: PaymentProcessorAdapter,
    ) -> PaymentAttempt:
        """Ask the processor what really happened to an unknown attempt.

        Same rule as chunk 11's supplier reconciliation: the *same* processor,
        the *same* reference. Routing a second charge to a different processor
        because the first went quiet is how a customer pays twice.
        """
        if adapter.name != attempt.processor:
            raise PaymentRoutingError(
                "wrong_processor",
                f"attempt was made through {attempt.processor}, not {adapter.name}",
            )
        reference = attempt.processor_reference or attempt.idempotency_key
        charge = adapter.fetch_charge(reference)
        if charge is None:
            attempt.status = AttemptStatus.UNKNOWN
            attempt.failure_reason = (
                f"{adapter.name} could not confirm the outcome of {reference}"
            )
            session.add(attempt)
            session.flush()
            return attempt
        result = self.capture(session, charge, adapter.name)
        if isinstance(result, PaymentAttempt):
            return result
        # The reconciliation turned up money that does not belong to this
        # attempt. The attempt itself remains unresolved.
        attempt.status = AttemptStatus.UNKNOWN
        attempt.failure_reason = f"reconciliation recorded excess {result.id}"
        session.add(attempt)
        session.flush()
        return attempt


def canonical_metadata(intent: PaymentIntent) -> str:
    """What we ask a processor to echo back, so a reply can be tied to us."""
    return json.dumps(
        {
            "intent": str(intent.id),
            "order": str(intent.order_id),
            "currency": intent.currency,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
