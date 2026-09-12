"""Quote → order → payment intent, idempotently (US-37, chunk 19).

Chunks 09–13 built each half of this and left the join unwritten: nothing in the
codebase turned a `Quote` into an `Order`. That join is where double-charging
lives, so this module has one job and states it plainly.

**The quote is the idempotency key.** Not a client-supplied header, and not a
hash of the request body. A quote is issued once, is server-priced, expires, and
can be redeemed exactly once by a conditional UPDATE — so "has this basket
already been bought" is a question the database can answer without trusting
anything the caller sends. A retried checkout, a double tap, a lost response and
a cold-started app returning from the processor all ask the same question, and
all get the same order back.

The alternative — an `Idempotency-Key` header — would have been a second,
weaker key layered over a strong one that already exists, and the two would
disagree the first time a client generated a fresh key for a retry.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlmodel import Session, col, select

from app.auth.models import User
from app.catalog.quotes import Quote, QuoteItem, QuoteStatus
from app.catalog.service import CatalogError, CatalogService
from app.money import round_money
from app.orders.models import Order, OrderItem, PaymentState, ProvisioningState
from app.payments.contract import (
    AttemptStatus,
    MerchantAccount,
    PaymentAttempt,
    PaymentIntent,
    PaymentMethodKind,
)
from app.payments.routing import (
    CheckoutSession,
    PaymentProcessorAdapter,
    PaymentRouter,
    PaymentRoutingError,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CheckoutError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


@dataclass(frozen=True)
class CheckoutResult:
    order: Order
    intent: PaymentIntent
    attempt: PaymentAttempt | None
    #: `None` when the order is already paid, or when the processor could not be
    #: reached. Neither is an error the customer should see as "try again":
    #: one is done, the other is recoverable from the order itself.
    session: CheckoutSession | None
    #: True when this call found an existing order rather than creating one.
    #: The route returns 200 rather than 201, and the app knows to resume.
    resumed: bool


class CheckoutService:
    def __init__(
        self,
        catalog: CatalogService,
        router: PaymentRouter,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.catalog = catalog
        self.router = router
        self.clock = clock

    # --- reading an existing checkout -------------------------------------

    def existing_intent(self, session: Session, quote_id: UUID) -> PaymentIntent | None:
        """The order this quote already produced, if it produced one.

        `payment_intents.quote_id` is what chunk 12 recorded and nothing has
        read until now. It is the link that makes the second checkout a lookup
        instead of a purchase.
        """
        return session.exec(
            select(PaymentIntent).where(PaymentIntent.quote_id == quote_id)
        ).first()

    # --- placing ----------------------------------------------------------

    def place(
        self,
        session: Session,
        *,
        quote_id: UUID,
        payer: User,
        method: PaymentMethodKind,
        adapter: PaymentProcessorAdapter | None,
        require_live: bool = True,
    ) -> CheckoutResult:
        """Buy the basket this quote priced. Twice means once.

        Ordering is deliberate and load-bearing:

        1. **Look for an existing intent first.** Before touching the quote,
           before routing, before the processor. A retry must be cheap and must
           never depend on the processor being reachable.
        2. **Redeem the quote.** The conditional UPDATE is the race winner;
           the loser of two simultaneous checkouts falls back to step 1's
           lookup rather than raising at the customer.
        3. **Create the order and its items**, then the intent, then the
           attempt — each of which is itself idempotent on re-entry.
        4. **Ask the processor last.** A processor failure leaves a placed,
           unpaid order the customer can resume, not a lost basket.
        """
        existing = self.existing_intent(session, quote_id)
        if existing is not None:
            return self._resume(session, existing, payer, method, adapter, require_live)

        quote = self.catalog.load_for_redemption(session, quote_id)
        self._assert_payer_may_redeem(session, quote, payer)

        try:
            self.catalog.redeem(session, quote_id)
        except CatalogError as exc:
            if exc.code != "quote_already_redeemed":
                raise
            # Lost the race, or a replay that arrived between the lookup and
            # here. Whoever won has created the intent; return theirs.
            racing = self.existing_intent(session, quote_id)
            if racing is None:
                # Redeemed with no intent: a checkout that crashed between the
                # two. Refusing is correct — the quote's price is claimed and
                # inventing a second order for it would be inventing a sale.
                raise CheckoutError(
                    "quote_already_redeemed",
                    "this quote was already claimed; ask for a new one",
                ) from exc
            return self._resume(session, racing, payer, method, adapter, require_live)

        items = list(
            session.exec(select(QuoteItem).where(QuoteItem.quote_id == quote.id)).all()
        )
        order = self._create_order(session, quote, payer, items)
        merchant = self.router.route(
            session,
            seller_legal_entity_id=order.seller_legal_entity_id,
            currency=order.currency,
            method=method,
            require_live=require_live,
        )
        intent = self.router.create_intent(
            session, order, merchant, order.total_amount, quote_id=quote.id
        )
        attempt = self.router.begin_attempt(session, intent, merchant, method)
        checkout = self._open_processor_session(
            session, adapter, attempt, intent, merchant, method, payer
        )
        return CheckoutResult(
            order=order,
            intent=intent,
            attempt=attempt,
            session=checkout,
            resumed=False,
        )

    def _resume(
        self,
        session: Session,
        intent: PaymentIntent,
        payer: User,
        method: PaymentMethodKind,
        adapter: PaymentProcessorAdapter | None,
        require_live: bool,
    ) -> CheckoutResult:
        """Return to an order that already exists (AC-37.5).

        The case this exists for: the customer paid, the webhook has not landed
        or the app was killed on the way back from the processor, and they tap
        buy again. They must reach *this* order, not a second one.
        """
        order = session.get(Order, intent.order_id)
        if order is None:  # pragma: no cover - FK guarantees this
            raise CheckoutError("order_not_found")
        if order.payer_user_id != payer.id:
            # A quote id is not an authorization capability. This check must
            # precede every attempt/session lookup so a replay cannot reveal
            # another customer's order or reopen their processor session.
            raise CheckoutError("quote_not_yours")

        succeeded = session.exec(
            select(PaymentAttempt).where(
                PaymentAttempt.intent_id == intent.id,
                PaymentAttempt.status == AttemptStatus.SUCCEEDED,
            )
        ).first()
        if succeeded is not None or order.payment_state is PaymentState.PAID:
            # Already paid. No new attempt, no new processor session, and
            # certainly no second charge: the app is sent to order status.
            return CheckoutResult(
                order=order,
                intent=intent,
                attempt=succeeded,
                session=None,
                resumed=True,
            )

        # An attempt that is still live is reusable; a customer who abandoned a
        # redirect and came back should land on the same processor session
        # rather than opening a second one against the same money.
        live = session.exec(
            select(PaymentAttempt)
            .where(
                PaymentAttempt.intent_id == intent.id,
                col(PaymentAttempt.status).in_(
                    [AttemptStatus.CREATED, AttemptStatus.PENDING]
                ),
            )
            .order_by(col(PaymentAttempt.created_at).desc())
        ).first()

        merchant = session.get(MerchantAccount, intent.merchant_account_id)
        if merchant is None:  # pragma: no cover - FK guarantees this
            raise CheckoutError("merchant_not_found")
        if require_live and not merchant.live_enabled:
            raise PaymentRoutingError("live_collection_disabled")

        attempt = live or self.router.begin_attempt(session, intent, merchant, method)
        checkout = self._open_processor_session(
            session,
            adapter,
            attempt,
            intent,
            merchant,
            attempt.method,
            payer,
        )
        return CheckoutResult(
            order=order,
            intent=intent,
            attempt=attempt,
            session=checkout,
            resumed=True,
        )

    # --- order construction -----------------------------------------------

    def _create_order(
        self,
        session: Session,
        quote: Quote,
        payer: User,
        items: list[QuoteItem],
    ) -> Order:
        """One order, and one order item per unit sold.

        `ck_order_items_single_line` requires `quantity = 1`, and chunk 05 says
        why: one item is one independently recoverable connectivity line. A
        quote line for three eSIMs therefore becomes three order items, each
        with its own recipient, supplier operation, entitlement and provisioning
        state. Collapsing them would make a partial provisioning failure
        unrepresentable.
        """
        if not items:  # pragma: no cover - a quote cannot be issued empty
            raise CheckoutError("quote_empty")

        order = Order(
            reference=f"OR-{secrets.token_hex(8).upper()}",
            seller_legal_entity_id=quote.seller_legal_entity_id,
            payer_user_id=payer.id,
            payer_organization_id=None,
            currency=quote.currency,
            total_amount=round_money(Decimal(quote.total_amount), quote.currency),
            payment_state=PaymentState.UNPAID,
            placed_at=self.clock(),
        )
        session.add(order)
        session.flush()

        for item in items:
            for _unit in range(item.quantity):
                session.add(
                    OrderItem(
                        order_id=order.id,
                        product_id=item.product_id,
                        # A consumer purchase names its recipient immediately.
                        # A quote line that named one keeps it; one that did not
                        # falls back to the payer, who is buying for themselves.
                        recipient_user_id=item.recipient_user_id or payer.id,
                        quantity=1,
                        unit_currency=item.unit_currency,
                        unit_amount=round_money(
                            Decimal(item.unit_amount), item.unit_currency
                        ),
                        provisioning_state=ProvisioningState.NOT_STARTED,
                    )
                )
        session.flush()
        return order

    @staticmethod
    def _assert_payer_may_redeem(session: Session, quote: Quote, payer: User) -> None:
        """A consumer quote may name exactly one account: its payer.

        Consumer routes always name the buyer. This refuses the case where a
        quote issued for named recipients is presented by an unrelated account —
        which would otherwise attach somebody else's service to this payer's
        order and receipt.
        """
        recipients = {
            item.recipient_user_id
            for item in session.exec(
                select(QuoteItem).where(QuoteItem.quote_id == quote.id)
            ).all()
            if item.recipient_user_id is not None
        }
        if recipients != {payer.id}:
            raise CheckoutError(
                "quote_not_yours",
                "this quote was priced for a different recipient",
            )

    @staticmethod
    def _open_processor_session(
        session: Session,
        adapter: PaymentProcessorAdapter | None,
        attempt: PaymentAttempt,
        intent: PaymentIntent,
        merchant: MerchantAccount,
        method: PaymentMethodKind,
        payer: User,
    ) -> CheckoutSession | None:
        """Ask the processor for somewhere to send the customer.

        `None` when no adapter is configured — D4 is open, so that is the
        current state rather than a failure — and `None` again when the
        processor call fails. Both leave a placed, unpaid order that the
        customer can resume, which is strictly better than losing the basket
        and strictly better than pretending a session exists.
        """
        if adapter is None:
            return None
        if adapter.name != merchant.processor:
            raise PaymentRoutingError("wrong_processor")
        try:
            checkout = adapter.create_checkout(
                idempotency_key=attempt.idempotency_key,
                amount=intent.amount,
                currency=intent.currency,
                method=method,
                metadata={
                    "order_id": str(intent.order_id),
                    "intent_id": str(intent.id),
                    "merchant": merchant.processor,
                    # Paystack requires an email to initialize hosted checkout.
                    # It is used only for that request and is not copied into
                    # processor metadata or persisted in a payment attempt.
                    "customer_email": payer.email,
                },
            )
        except Exception:  # noqa: BLE001 - any adapter failure is recoverable
            return None
        # Webhooks are allowed to identify a charge using the processor's own
        # reference, which need not equal our idempotency key. Persisting it is
        # not an adapter operation, so database failures must not be swallowed
        # as a recoverable processor timeout.
        attempt.processor_reference = checkout.processor_reference
        attempt.status = AttemptStatus.PENDING
        session.add(attempt)
        session.flush()
        return checkout


def quote_status_for(quote: Quote) -> str:
    return QuoteStatus(quote.status).value
