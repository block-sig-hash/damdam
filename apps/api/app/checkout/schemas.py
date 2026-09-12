"""Request and response shapes for browsing, quoting and checkout (US-37).

Amounts are strings, not floats. A price crossing JSON as a float is a price
that can come back a hundredth different from the one that was quoted, and the
one thing a quote must be is exactly what was shown.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from app.payments.contract import PaymentMethodKind


class MarketSummary(BaseModel):
    country: str
    currency: str
    seller_name: str


class MarketListResponse(BaseModel):
    markets: list[MarketSummary]


class CallDestination(BaseModel):
    """One destination this plan's tariff actually prices.

    The chunk requires "supported call destinations" before payment. A
    destination absent from the tariff is a destination the plan cannot price,
    and therefore one it must not imply it covers.
    """

    country: str
    destination_kind: str
    per_minute_amount: str
    setup_amount: str
    increment_seconds: int


class ProductSummary(BaseModel):
    product_id: UUID
    sku: str
    name: str
    kind: str
    currency: str
    amount: str
    #: Bytes and seconds, as granted. The app formats them; the API does not
    #: round a balance into gigabytes on the way out.
    data_bytes: int
    voice_seconds: int
    validity_days: int | None
    requires_esim: bool
    requires_unlocked_device: bool
    device_notes: str | None
    number_type: str
    number_country: str | None
    number_assignment: str
    coverage_countries: list[str]
    call_destinations: list[CallDestination]
    tariff_version: int | None
    #: False with a reason when this device cannot take the plan. The list still
    #: includes it: hiding an unavailable plan tells the customer nothing, and
    #: they need to know *why* before they go looking for a different phone.
    purchasable: bool
    unavailable_reason: str | None


class ProductListResponse(BaseModel):
    country: str
    currency: str
    products: list[ProductSummary]


class QuoteLineRequest(BaseModel):
    product_id: UUID
    quantity: int = Field(default=1, ge=1, le=50)
    recipient_user_id: UUID | None = None


class DeviceFactsRequest(BaseModel):
    """What the app could actually determine about the handset.

    Both fields are optional and `None` means *not checked* — deliberately
    distinct from "checked and incapable". The chunk requires practical guidance
    "where automatic device/carrier-lock detection is unavailable" and forbids
    implying guaranteed detection, so the app reports what it observed and the
    server refuses to guess the rest.
    """

    supports_esim: bool | None = None
    is_unlocked: bool | None = None


class QuoteRequest(BaseModel):
    country: str = Field(min_length=2, max_length=2)
    currency: str = Field(min_length=3, max_length=3)
    lines: list[QuoteLineRequest] = Field(min_length=1, max_length=50)
    device: DeviceFactsRequest = DeviceFactsRequest()


class QuoteItemResponse(BaseModel):
    product_id: UUID
    product_name: str
    quantity: int
    unit_amount: str
    line_amount: str
    recipient_user_id: UUID | None


class QuoteResponse(BaseModel):
    quote_id: UUID
    reference: str
    status: str
    currency: str
    subtotal_amount: str
    tax_amount: str
    fee_amount: str
    total_amount: str
    #: Null until D3 records an entity and a tax treatment. Shown as "no tax
    #: has been applied" rather than as zero tax, which is a different claim.
    tax_configuration_reference: str | None
    seller_name: str
    issued_at: datetime
    expires_at: datetime
    items: list[QuoteItemResponse]


class WalletOption(BaseModel):
    wallet: str
    available: bool
    reason: str | None


class PaymentMethodsResponse(BaseModel):
    """What the customer may actually pay with, and why not otherwise.

    `card_fallback_required` is always true today and says so from the
    configuration rather than from a constant: a checkout that offers only a
    wallet on a device without one is a checkout nobody can complete.
    """

    methods: list[str]
    wallets: list[WalletOption]
    card_fallback_required: bool
    #: True only when a live merchant account exists for this seller and
    #: currency. False is the current state everywhere — D3/D4 are open.
    collection_enabled: bool
    collection_blocked_reason: str | None


class CheckoutRequest(BaseModel):
    quote_id: UUID
    method: PaymentMethodKind = PaymentMethodKind.CARD


class OrderItemResponse(BaseModel):
    order_item_id: UUID
    product_id: UUID
    product_name: str
    unit_currency: str
    unit_amount: str
    provisioning_state: str
    recipient_user_id: UUID | None


class OrderResponse(BaseModel):
    order_id: UUID
    #: The immutable basket that created the order. It lets a signed-in customer
    #: resume the same intent from another device without relying on local data.
    quote_id: UUID | None
    reference: str
    currency: str
    total_amount: str
    payment_state: str
    #: Latest processor attempt, including pending/unknown/failed. Order payment
    #: state alone cannot distinguish "not started" from "webhook delayed".
    payment_attempt_state: str | None
    placed_at: datetime
    items: list[OrderItemResponse]
    #: Where the whole order has got to, collapsing the item states into the one
    #: word a status screen leads with. The per-item states stay above it.
    fulfilment_state: str


class OrderListResponse(BaseModel):
    orders: list[OrderResponse]


class CheckoutOutcome(str, Enum):
    """What the app should do next, decided by the server.

    Not inferred client-side from a combination of fields: the whole point of
    AC-37.5 is that a paid-but-pending order leads to status rather than to
    another purchase, and that decision belongs where the money is.
    """

    PAY = "pay"
    ALREADY_PAID = "already_paid"
    #: Placed, unpaid, and no processor session — D4 is open or the processor
    #: could not be reached. The order is real and resumable either way.
    AWAITING_PROCESSOR = "awaiting_processor"


class CheckoutResponse(BaseModel):
    outcome: CheckoutOutcome
    order: OrderResponse
    #: Present only for `PAY`. Never a secret and never card data.
    redirect_url: str | None = None
    processor_reference: str | None = None
    #: True when this call returned an order that already existed.
    resumed: bool
