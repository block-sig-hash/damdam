"""Browse, quote, pay and recover (US-37, chunk 19).

The route layer is deliberately thin. Every rule that decides whether money may
move lives in `CatalogService`, `PaymentRouter` or `CheckoutService`, because a
rule written in a handler is a rule that exists once and is checked once.

The one decision made here is which HTTP status each outcome gets, and the
interesting one is `POST /v1/checkout`: **201 for a new order, 200 for one that
already existed.** The app can tell "I just bought this" from "this was already
yours" without parsing a body, which is what stops a retry from looking like a
purchase.
"""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlmodel import Session, col, select

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.catalog.models import LegalEntity, Product
from app.catalog.quotes import Quote, QuoteItem
from app.catalog.service import CatalogError, CatalogService, DeviceFacts, LineRequest
from app.checkout.catalog_view import CatalogViewService
from app.checkout.schemas import (
    CheckoutOutcome,
    CheckoutRequest,
    CheckoutResponse,
    DeviceFactsRequest,
    MarketListResponse,
    OrderItemResponse,
    OrderListResponse,
    OrderResponse,
    PaymentMethodsResponse,
    ProductListResponse,
    QuoteItemResponse,
    QuoteRequest,
    QuoteResponse,
    WalletOption,
)
from app.checkout.service import CheckoutError, CheckoutService
from app.db import SessionFactory
from app.money import format_money
from app.orders.models import Order, OrderItem, PaymentState, ProvisioningState
from app.payments.contract import MerchantAccount, PaymentMethodKind
from app.payments.routing import PaymentProcessorAdapter
from app.payments.wallets import (
    CURRENT_CONFIGURATION,
    Wallet,
    card_fallback_required,
    is_available,
)

catalog_router = APIRouter(prefix="/catalog", tags=["Checkout"])
quote_router = APIRouter(prefix="/quotes", tags=["Checkout"])
checkout_router = APIRouter(prefix="/checkout", tags=["Checkout"])
order_router = APIRouter(prefix="/me/orders", tags=["Checkout"])


def _session(request: Request) -> Session:
    factory = cast(SessionFactory, request.app.state.session_factory)
    return factory()


def _catalog(request: Request) -> CatalogService:
    return cast(CatalogService, request.app.state.catalog_service)


def _catalog_view(request: Request) -> CatalogViewService:
    return cast(CatalogViewService, request.app.state.catalog_view_service)


def _checkout(request: Request) -> CheckoutService:
    return cast(CheckoutService, request.app.state.checkout_service)


def _adapter(request: Request) -> PaymentProcessorAdapter | None:
    """The processor, when one has been selected.

    `None` today: D4 is open, and a default naming a candidate would be a
    decision sitting in code where it reads like one that was made.
    """
    return cast(
        "PaymentProcessorAdapter | None",
        getattr(request.app.state, "payment_processor_adapter", None),
    )


# --- browsing --------------------------------------------------------------


@catalog_router.get("/markets", response_model=MarketListResponse)
def list_markets(request: Request) -> MarketListResponse:
    """Unauthenticated: which markets are on sale.

    Empty in any real deployment today. That is D2's answer, not an outage.
    """
    with _session(request) as session:
        return MarketListResponse(markets=_catalog_view(request).markets(session))


@catalog_router.get("/products", response_model=ProductListResponse)
def list_products(
    request: Request,
    country: Annotated[str, Query(min_length=2, max_length=2)],
    currency: Annotated[str, Query(min_length=3, max_length=3)],
    supports_esim: Annotated[bool | None, Query()] = None,
    is_unlocked: Annotated[bool | None, Query()] = None,
) -> ProductListResponse:
    """What can be bought here, and for anything that cannot, why not.

    The device facts are **optional and tri-state**. Omitting `supports_esim`
    means "not checked", which is not the same as "checked and incapable": the
    first still lists eSIM plans with a reason to check the device, and the
    second does not pretend the plan will work. The chunk forbids implying
    guaranteed detection, and this is the shape that keeps the promise.
    """
    device = DeviceFacts(supports_esim=supports_esim, is_unlocked=is_unlocked)
    with _session(request) as session:
        products = _catalog_view(request).products(
            session, country.upper(), currency.upper(), device
        )
    return ProductListResponse(
        country=country.upper(), currency=currency.upper(), products=products
    )


# --- quoting ---------------------------------------------------------------


def _quote_response(session: Session, quote: Quote) -> QuoteResponse:
    items = list(
        session.exec(select(QuoteItem).where(QuoteItem.quote_id == quote.id)).all()
    )
    names = {
        product.id: product.name
        for product in session.exec(
            select(Product).where(
                col(Product.id).in_([item.product_id for item in items])
            )
        ).all()
    }
    seller = session.get(LegalEntity, quote.seller_legal_entity_id)
    return QuoteResponse(
        quote_id=quote.id,
        reference=quote.reference,
        status=quote.status.value,
        currency=quote.currency,
        subtotal_amount=format_money(quote.subtotal_amount, quote.currency),
        tax_amount=format_money(quote.tax_amount, quote.currency),
        fee_amount=format_money(quote.fee_amount, quote.currency),
        total_amount=format_money(quote.total_amount, quote.currency),
        tax_configuration_reference=quote.tax_configuration_reference,
        seller_name=seller.name if seller else "",
        issued_at=quote.issued_at,
        expires_at=quote.expires_at,
        items=[
            QuoteItemResponse(
                product_id=item.product_id,
                product_name=names.get(item.product_id, ""),
                quantity=item.quantity,
                unit_amount=format_money(item.unit_amount, item.unit_currency),
                line_amount=format_money(item.line_amount, item.unit_currency),
                recipient_user_id=item.recipient_user_id,
            )
            for item in items
        ],
    )


@quote_router.post(
    "", response_model=QuoteResponse, status_code=status.HTTP_201_CREATED
)
def create_quote(
    payload: QuoteRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> QuoteResponse:
    """Price a basket on the server, from published versions only.

    Authenticated, even though browsing is not: a quote is an immutable,
    redeemable price with an expiry, and issuing them to anonymous callers is
    issuing a claim on a price to nobody in particular.
    """
    del user  # authorization only; a quote belongs to whoever redeems it
    with _session(request) as session:
        quote, _items = _catalog(request).issue_quote(
            session,
            country=payload.country.upper(),
            currency=payload.currency.upper(),
            lines=[
                LineRequest(
                    product_id=line.product_id,
                    quantity=line.quantity,
                    recipient_user_id=line.recipient_user_id,
                )
                for line in payload.lines
            ],
            device=_device(payload.device),
        )
        response = _quote_response(session, quote)
        session.commit()
        return response


def _device(payload: DeviceFactsRequest) -> DeviceFacts:
    return DeviceFacts(
        supports_esim=payload.supports_esim, is_unlocked=payload.is_unlocked
    )


@quote_router.get("/{quote_id}", response_model=QuoteResponse)
def read_quote(
    quote_id: UUID,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> QuoteResponse:
    """Re-read a quote for the review screen, and for the app after a restart.

    Deliberately **does not** re-run redemption's checks. An expired quote is
    returned with its status and its `expires_at`, so the review screen can say
    "this price expired, here is a fresh one" instead of failing blank.
    """
    del user
    with _session(request) as session:
        quote = session.get(Quote, quote_id)
        if quote is None:
            raise CatalogError("quote_not_found")
        return _quote_response(session, quote)


# --- payment methods -------------------------------------------------------


@checkout_router.get("/methods", response_model=PaymentMethodsResponse)
def payment_methods(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    country: Annotated[str, Query(min_length=2, max_length=2)],
    currency: Annotated[str, Query(min_length=3, max_length=3)],
    device_offers_apple_pay: Annotated[bool, Query()] = False,
    device_offers_google_pay: Annotated[bool, Query()] = False,
) -> PaymentMethodsResponse:
    """What the customer may pay with here, with a reason for each refusal.

    Wallet availability is four separate conditions, and the reason matters: a
    checkout that says "Apple Pay unavailable" when the truth is "no processor
    has been selected" sends whoever is debugging to the wrong place, and the
    customer to a support conversation nobody can resolve.
    """
    del user
    domain = str(getattr(request.app.state.settings, "app_bundle_id", "") or "")
    wallets = [
        WalletOption(
            wallet=wallet.value,
            available=availability.available,
            reason=None if availability.available else availability.explanation,
        )
        for wallet, availability in (
            (
                wallet,
                is_available(
                    CURRENT_CONFIGURATION,
                    wallet,
                    domain,
                    device_offers_apple_pay
                    if wallet is Wallet.APPLE_PAY
                    else device_offers_google_pay,
                ),
            )
            for wallet in Wallet
        )
    ]
    needs_card = any(
        card_fallback_required(
            is_available(
                CURRENT_CONFIGURATION,
                wallet,
                domain,
                device_offers_apple_pay
                if wallet is Wallet.APPLE_PAY
                else device_offers_google_pay,
            )
        )
        for wallet in Wallet
    )

    with _session(request) as session:
        merchant = _live_merchant(session, country.upper(), currency.upper())

    methods = [PaymentMethodKind.CARD.value, PaymentMethodKind.BANK_TRANSFER.value]
    methods += [
        option.wallet for option in wallets if option.available
    ]
    return PaymentMethodsResponse(
        methods=methods,
        wallets=wallets,
        card_fallback_required=needs_card,
        collection_enabled=merchant is not None,
        collection_blocked_reason=(
            None
            if merchant is not None
            else "no live merchant account for this seller and currency "
            "(DECISIONS.md D3/D4)"
        ),
    )


def _live_merchant(
    session: Session, country: str, currency: str
) -> MerchantAccount | None:
    from app.catalog.market import PublicationStatus, SalesMarket

    market = session.exec(
        select(SalesMarket).where(
            SalesMarket.country == country,
            SalesMarket.currency == currency,
            SalesMarket.status == PublicationStatus.PUBLISHED,
        )
    ).first()
    if market is None or market.legal_entity_id is None:
        return None
    return session.exec(
        select(MerchantAccount).where(
            MerchantAccount.legal_entity_id == market.legal_entity_id,
            MerchantAccount.currency == currency,
            col(MerchantAccount.live_enabled).is_(True),
        )
    ).first()


# --- checkout --------------------------------------------------------------


@checkout_router.post("", response_model=CheckoutResponse)
def place_checkout(
    payload: CheckoutRequest,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
) -> CheckoutResponse:
    """Buy the basket this quote priced. Twice means once.

    **201** when an order was created, **200** when an existing one was
    returned. The distinction is the whole recovery story: a retry, a double
    tap, and an app cold-started on the way back from the processor all get 200
    and their own order.
    """
    service = _checkout(request)
    with _session(request) as session:
        account = session.get(User, user.id)
        if account is None:  # pragma: no cover - a live token implies a row
            raise CheckoutError("order_not_found")
        result = service.place(
            session,
            quote_id=payload.quote_id,
            payer=account,
            method=payload.method,
            adapter=_adapter(request),
        )
        body = CheckoutResponse(
            outcome=(
                CheckoutOutcome.ALREADY_PAID
                if result.order.payment_state is PaymentState.PAID
                else CheckoutOutcome.PAY
                if result.session is not None
                else CheckoutOutcome.AWAITING_PROCESSOR
            ),
            order=_order_response(session, result.order),
            redirect_url=result.session.redirect_url if result.session else None,
            processor_reference=(
                result.session.processor_reference if result.session else None
            ),
            resumed=result.resumed,
        )
        session.commit()
    response.status_code = (
        status.HTTP_200_OK if body.resumed else status.HTTP_201_CREATED
    )
    return body


# --- orders ----------------------------------------------------------------


def _fulfilment_state(items: list[OrderItem]) -> str:
    """The one word an order-status screen leads with.

    Deliberately pessimistic in a specific way: an order is only `provisioned`
    when **every** item is. A partially provisioned bulk order that reported
    success would hide the lines that failed, and chunk 05 split the items apart
    precisely so those stay visible.
    """
    if not items:
        return ProvisioningState.NOT_STARTED.value
    states = {item.provisioning_state for item in items}
    if states == {ProvisioningState.PROVISIONED}:
        return ProvisioningState.PROVISIONED.value
    if ProvisioningState.OUTCOME_UNKNOWN in states:
        return ProvisioningState.OUTCOME_UNKNOWN.value
    if ProvisioningState.FAILED in states:
        return ProvisioningState.FAILED.value
    if ProvisioningState.REQUESTED in states:
        return ProvisioningState.REQUESTED.value
    if states == {ProvisioningState.CANCELLED}:
        return ProvisioningState.CANCELLED.value
    return ProvisioningState.NOT_STARTED.value


def _order_response(session: Session, order: Order) -> OrderResponse:
    items = list(
        session.exec(select(OrderItem).where(OrderItem.order_id == order.id)).all()
    )
    names = {
        product.id: product.name
        for product in session.exec(
            select(Product).where(
                col(Product.id).in_([item.product_id for item in items])
            )
        ).all()
    }
    return OrderResponse(
        order_id=order.id,
        reference=order.reference,
        currency=order.currency,
        total_amount=format_money(order.total_amount, order.currency),
        payment_state=order.payment_state.value,
        placed_at=order.placed_at,
        items=[
            OrderItemResponse(
                order_item_id=item.id,
                product_id=item.product_id,
                product_name=names.get(item.product_id, ""),
                unit_currency=item.unit_currency,
                unit_amount=format_money(item.unit_amount, item.unit_currency),
                provisioning_state=item.provisioning_state.value,
                recipient_user_id=item.recipient_user_id,
            )
            for item in items
        ],
        fulfilment_state=_fulfilment_state(items),
    )


@order_router.get("", response_model=OrderListResponse)
def list_orders(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> OrderListResponse:
    with _session(request) as session:
        orders = session.exec(
            select(Order)
            .where(Order.payer_user_id == user.id)
            .order_by(col(Order.placed_at).desc())
        ).all()
        return OrderListResponse(
            orders=[_order_response(session, order) for order in orders]
        )


@order_router.get("/{order_id}", response_model=OrderResponse)
def read_order(
    order_id: UUID,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> OrderResponse:
    """The recovery destination, and the app's source of truth after a restart.

    Scoped to the payer. `order_not_found` for somebody else's order rather than
    a 403: the difference between "does not exist" and "is not yours" is an
    oracle for whether a reference is real.
    """
    with _session(request) as session:
        order = session.get(Order, order_id)
        if order is None or order.payer_user_id != user.id:
            raise CheckoutError("order_not_found")
        return _order_response(session, order)
