"""US-37 chunk 19 — quote → order → payment intent, on PostgreSQL.

One property dominates this file: **a customer who has already paid never buys a
second time.** Every other assertion here is a way that property gets broken in
production — a double tap, a lost response, an app killed on the way back from
the processor, two devices, two threads.

PostgreSQL rather than SQLite because the guarantee is enforced by the database:
the quote's redemption is a conditional `UPDATE ... WHERE status = 'issued'`,
`ux_payment_attempts_one_success` is a partial unique index, and the concurrent
case needs two real connections racing.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from app import model_registry  # noqa: F401  -- completes SQLModel.metadata
from app.auth.models import Locale, User, UserStatus
from app.catalog.market import (
    DeviceEligibilityRule,
    NumberAssignment,
    NumberPolicy,
    NumberType,
    ProductCoverage,
    ProviderOffering,
    PublicationStatus,
    SalesMarket,
)
from app.catalog.models import (
    LegalEntity,
    Product,
    ProductAllowance,
    ProductKind,
    ProductPrice,
)
from app.catalog.service import CatalogError, CatalogService, DeviceFacts, LineRequest
from app.catalog.tariffs import DestinationKind, OriginKind, Tariff, TariffRate
from app.checkout.service import CheckoutError, CheckoutService
from app.orders.models import Order, OrderItem, PaymentState
from app.payments.contract import (
    AttemptStatus,
    MerchantAccount,
    PaymentAttempt,
    PaymentIntent,
    PaymentMethodKind,
)
from app.payments.routing import (
    CheckoutSession,
    PaymentRouter,
    PaymentRoutingError,
    ProcessorCharge,
)

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="checkout idempotency is enforced by database constraints",
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
TABLES = (
    "excess_payments, payment_attempts, payment_intents, merchant_accounts, "
    "quote_items, quotes, order_items, orders, number_policies, "
    "tariff_rates, tariffs, "
    "device_eligibility_rules, provider_offerings, product_coverage, "
    "product_allowances, product_prices, products, sales_markets, "
    "legal_entities, users"
)


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: float) -> None:
        self.value += timedelta(**kwargs)


class FakeProcessor:
    """A processor that can succeed, fail, or be unreachable, on request."""

    name = "fakepay"

    def __init__(self) -> None:
        self.checkouts: list[str] = []
        self.unreachable = False

    def create_checkout(
        self,
        idempotency_key: str,
        amount: Decimal,
        currency: str,
        method: PaymentMethodKind,
        metadata: dict[str, Any],
    ) -> CheckoutSession:
        if self.unreachable:
            raise RuntimeError("processor timed out")
        self.checkouts.append(idempotency_key)
        return CheckoutSession(
            processor_reference=idempotency_key,
            redirect_url=f"https://pay.example.test/{idempotency_key}",
            metadata=metadata,
        )

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        return True

    def parse_webhook(self, raw_body: bytes) -> ProcessorCharge:  # pragma: no cover
        raise NotImplementedError

    def fetch_charge(
        self, processor_reference: str
    ) -> ProcessorCharge | None:  # pragma: no cover
        return None


@pytest.fixture(scope="module")
def engine():
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        session.exec(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        session.commit()
        yield session
        session.rollback()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def catalog(clock: Clock) -> CatalogService:
    return CatalogService(clock=clock)


@pytest.fixture
def service(catalog: CatalogService, clock: Clock) -> CheckoutService:
    return CheckoutService(catalog, PaymentRouter(clock=clock), clock=clock)


@pytest.fixture
def processor() -> FakeProcessor:
    return FakeProcessor()


# --- fixtures that build a purchasable market ------------------------------


def _user(session: Session, phone: str = "+2348010000001") -> User:
    user = User(phone_number=phone, locale=Locale.EN, status=UserStatus.ACTIVE)
    session.add(user)
    session.flush()
    return user


def _sellable(
    session: Session,
    clock: Clock,
    *,
    kind: ProductKind = ProductKind.BUNDLE,
    requires_esim: bool = True,
    amount: str = "10000.00",
    live_enabled: bool = True,
) -> tuple[LegalEntity, Product, SalesMarket, MerchantAccount]:
    """Everything D2/D3/D4 would have to be resolved for, as a fixture.

    Written out in full rather than hidden in a factory because the point of
    `docs/implementation/DECISIONS.md` is that none of this exists in a real
    deployment: no seller entity is seeded, no market is published and no
    merchant account is live. A test fixture may create them; the production
    catalog may not.
    """
    entity = LegalEntity(code=uuid4().hex[:8], name="Test Seller Ltd", country="NG")
    session.add(entity)
    session.flush()

    product = Product(sku=uuid4().hex[:12], name="Travel 5GB + calls", kind=kind)
    session.add(product)
    session.flush()

    session.add(
        ProductAllowance(
            product_id=product.id,
            data_bytes=5_368_709_120,
            voice_seconds=3_600,
            validity_days=30,
        )
    )
    session.add(
        ProductPrice(
            product_id=product.id,
            legal_entity_id=entity.id,
            currency="NGN",
            amount=Decimal(amount),
            version=1,
            effective_from=NOW - timedelta(days=1),
        )
    )
    session.add(
        ProviderOffering(
            product_id=product.id,
            provider="telnyx",
            provider_sku="sku-1",
            status=PublicationStatus.PUBLISHED,
            supports_data=True,
            supports_native_voice=True,
            evidence_reference="docs/implementation/handoffs/15.md",
            verified_at=NOW - timedelta(days=1),
        )
    )
    session.add(
        DeviceEligibilityRule(
            product_id=product.id,
            requires_esim=requires_esim,
            requires_unlocked_device=True,
        )
    )
    session.add(
        NumberPolicy(
            product_id=product.id,
            number_type=NumberType.MOBILE,
            number_country="NG",
            assignment=NumberAssignment.NEW_ASSIGNED,
        )
    )
    session.add(ProductCoverage(product_id=product.id, country="NG"))

    # A product that sells calls needs a published tariff, or `issue_quote`
    # refuses to price it. Chunk 09 put that check in for the right reason: a
    # voice plan quoted with no rate version is a plan whose calls have no
    # agreed price.
    tariff = Tariff(
        product_id=product.id,
        currency="NGN",
        version=1,
        status=PublicationStatus.PUBLISHED,
        effective_from=NOW - timedelta(days=1),
        evidence_reference="docs/implementation/handoffs/09.md",
        verified_at=NOW - timedelta(days=1),
    )
    session.add(tariff)
    session.flush()
    session.add(
        TariffRate(
            tariff_id=tariff.id,
            origin_kind=OriginKind.CARRIER_VISITED_NETWORK,
            origin_country=None,
            destination_country="NG",
            destination_kind=DestinationKind.MOBILE,
            per_minute_amount=Decimal("25.000000"),
            setup_amount=Decimal("0.00"),
            minimum_seconds=0,
            increment_seconds=60,
        )
    )

    market = SalesMarket(
        country="NG",
        currency="NGN",
        status=PublicationStatus.VERIFIED,
        evidence_reference="docs/implementation/DECISIONS.md#d2",
        verified_at=NOW - timedelta(days=1),
    )
    session.add(market)
    session.flush()
    CatalogService(clock=clock).publish_market(session, market, entity)

    merchant = MerchantAccount(
        legal_entity_id=entity.id,
        processor="fakepay",
        currency="NGN",
        live_enabled=live_enabled,
        approval_reference="approval-1",
    )
    session.add(merchant)
    session.flush()
    return entity, product, market, merchant


def _quote(
    session: Session,
    catalog: CatalogService,
    product: Product,
    *,
    quantity: int = 1,
    recipient: User | None = None,
) -> UUID:
    quote, _items = catalog.issue_quote(
        session,
        country="NG",
        currency="NGN",
        lines=[
            LineRequest(
                product_id=product.id,
                quantity=quantity,
                recipient_user_id=recipient.id if recipient else None,
            )
        ],
        device=DeviceFacts(supports_esim=True, is_unlocked=True),
    )
    return quote.id


# --- the property this module exists for -----------------------------------


def test_a_second_checkout_of_one_quote_returns_the_first_order(
    session: Session,
    service: CheckoutService,
    catalog: CatalogService,
    clock: Clock,
    processor: FakeProcessor,
) -> None:
    """The double tap, and the retry after a lost response.

    Both reach `place()` with the same quote. If this ever produced two orders,
    the customer would be charged twice for one basket and provisioned twice,
    which is the failure `AGENTS.md` calls "the single most expensive failure
    mode in this product".
    """
    _entity, product, _market, _merchant = _sellable(session, clock)
    payer = _user(session)
    quote_id = _quote(session, catalog, product)

    first = service.place(
        session,
        quote_id=quote_id,
        payer=payer,
        method=PaymentMethodKind.CARD,
        adapter=processor,
    )
    second = service.place(
        session,
        quote_id=quote_id,
        payer=payer,
        method=PaymentMethodKind.CARD,
        adapter=processor,
    )

    assert first.resumed is False
    assert second.resumed is True
    assert second.order.id == first.order.id
    assert session.exec(select(Order)).all() == [first.order]
    assert (
        len(session.exec(select(PaymentIntent)).all()) == 1
    ), "a second intent means a second collectable amount"
    # The live attempt is reused rather than replaced: two open processor
    # sessions against one intent is two ways for the customer to pay.
    assert second.attempt is not None
    assert second.attempt.id == first.attempt.id
    assert processor.checkouts == [first.attempt.idempotency_key] * 2


def test_a_paid_order_is_never_offered_a_new_payment_session(
    session: Session,
    service: CheckoutService,
    catalog: CatalogService,
    clock: Clock,
    processor: FakeProcessor,
) -> None:
    """The chunk's headline acceptance: paid-but-pending leads to status.

    The customer paid, the webhook has landed, provisioning has not finished, and
    they tap buy again — from a stale screen, or because nothing looks different
    yet. They must reach their order, with no attempt and no redirect.
    """
    _entity, product, _market, merchant = _sellable(session, clock)
    payer = _user(session)
    quote_id = _quote(session, catalog, product)

    placed = service.place(
        session,
        quote_id=quote_id,
        payer=payer,
        method=PaymentMethodKind.CARD,
        adapter=processor,
    )
    PaymentRouter(clock=clock).capture(
        session,
        ProcessorCharge(
            processor_reference=placed.attempt.idempotency_key,
            status="success",
            amount=placed.intent.amount,
            currency=placed.intent.currency,
            merchant_reference=merchant.approval_reference,
            succeeded=True,
        ),
        processor="fakepay",
    )
    session.flush()
    checkouts_before = len(processor.checkouts)

    resumed = service.place(
        session,
        quote_id=quote_id,
        payer=payer,
        method=PaymentMethodKind.CARD,
        adapter=processor,
    )

    assert resumed.resumed is True
    assert resumed.order.payment_state is PaymentState.PAID
    assert resumed.session is None, "a paid order must not be given a redirect"
    assert resumed.attempt is not None
    assert resumed.attempt.status is AttemptStatus.SUCCEEDED
    assert len(processor.checkouts) == checkouts_before, (
        "the processor must not be asked to open a second session for money "
        "that has already been collected"
    )
    assert len(session.exec(select(PaymentAttempt)).all()) == 1


def test_two_simultaneous_checkouts_produce_one_order(
    engine,
    session: Session,
    catalog: CatalogService,
    clock: Clock,
) -> None:
    """Two devices, or one device and a retry, arriving together.

    Both threads load the same issued quote and both try to redeem it. The
    conditional UPDATE decides; the loser must find the winner's order rather
    than raising at a customer who did nothing wrong.
    """
    _entity, product, _market, _merchant = _sellable(session, clock)
    payer = _user(session)
    quote_id = _quote(session, catalog, product)
    payer_id = payer.id
    session.commit()

    barrier = Barrier(2)

    def attempt() -> tuple[UUID | None, str | None]:
        own_clock = Clock()
        own = CheckoutService(
            CatalogService(clock=own_clock),
            PaymentRouter(clock=own_clock),
            clock=own_clock,
        )
        with Session(engine) as own_session:
            user = own_session.get(User, payer_id)
            assert user is not None
            barrier.wait(timeout=10)
            try:
                result = own.place(
                    own_session,
                    quote_id=quote_id,
                    payer=user,
                    method=PaymentMethodKind.CARD,
                    adapter=FakeProcessor(),
                )
                own_session.commit()
                return result.order.id, None
            except (CheckoutError, CatalogError, PaymentRoutingError) as exc:
                own_session.rollback()
                return None, exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        outcomes = [future.result() for future in futures]

    order_ids = {order_id for order_id, _code in outcomes if order_id is not None}
    codes = [code for _order_id, code in outcomes if code is not None]

    session.expire_all()
    orders = session.exec(select(Order)).all()
    assert len(orders) == 1, f"one quote, one order; got {len(orders)} ({codes})"
    assert len(order_ids) <= 1
    # Whichever thread lost either returned the same order or reported the
    # claimed quote. What it must never do is create a second order.
    assert all(
        code in {"quote_already_redeemed", None} for code in codes
    ), codes


def test_a_quote_line_for_three_becomes_three_recoverable_order_items(
    session: Session,
    service: CheckoutService,
    catalog: CatalogService,
    clock: Clock,
    processor: FakeProcessor,
) -> None:
    """Chunk 05's invariant, at the point where it is created.

    `ck_order_items_single_line` requires `quantity = 1`. Three eSIMs is three
    items so that one supplier failure is one failed line, recoverable on its
    own, rather than an all-or-nothing order.
    """
    _entity, product, _market, _merchant = _sellable(session, clock)
    payer = _user(session)
    quote_id = _quote(session, catalog, product, quantity=3)

    result = service.place(
        session,
        quote_id=quote_id,
        payer=payer,
        method=PaymentMethodKind.CARD,
        adapter=processor,
    )

    items = session.exec(
        select(OrderItem).where(OrderItem.order_id == result.order.id)
    ).all()
    assert len(items) == 3
    assert {item.quantity for item in items} == {1}
    assert {item.recipient_user_id for item in items} == {payer.id}
    # The order total is the quote's total, not the sum recomputed here: a
    # checkout that re-derives a price can disagree with what was shown.
    assert result.order.total_amount == Decimal("30000.00")


def test_an_expired_quote_cannot_be_bought(
    session: Session,
    service: CheckoutService,
    catalog: CatalogService,
    clock: Clock,
    processor: FakeProcessor,
) -> None:
    _entity, product, _market, _merchant = _sellable(session, clock)
    payer = _user(session)
    quote_id = _quote(session, catalog, product)

    clock.advance(minutes=31)

    with pytest.raises(CatalogError) as raised:
        service.place(
            session,
            quote_id=quote_id,
            payer=payer,
            method=PaymentMethodKind.CARD,
            adapter=processor,
        )
    assert raised.value.code == "quote_expired"
    assert session.exec(select(Order)).all() == []


def test_a_quote_priced_for_someone_else_is_refused(
    session: Session,
    service: CheckoutService,
    catalog: CatalogService,
    clock: Clock,
    processor: FakeProcessor,
) -> None:
    """Otherwise one account's order and receipt carry another's service."""
    _entity, product, _market, _merchant = _sellable(session, clock)
    recipient = _user(session, "+2348010000002")
    stranger = _user(session, "+2348010000003")
    quote_id = _quote(session, catalog, product, recipient=recipient)

    with pytest.raises(CheckoutError) as raised:
        service.place(
            session,
            quote_id=quote_id,
            payer=stranger,
            method=PaymentMethodKind.CARD,
            adapter=processor,
        )
    assert raised.value.code == "quote_not_yours"
    assert session.exec(select(Order)).all() == []


def test_an_unreachable_processor_leaves_a_resumable_order_not_a_lost_basket(
    session: Session,
    service: CheckoutService,
    catalog: CatalogService,
    clock: Clock,
    processor: FakeProcessor,
) -> None:
    """The processor is asked last, and its failure is not the order's failure.

    The quote is claimed and the order exists. Refusing to record it would send
    the customer back to a quote that can no longer be redeemed, with nothing to
    show for it.
    """
    _entity, product, _market, _merchant = _sellable(session, clock)
    payer = _user(session)
    quote_id = _quote(session, catalog, product)
    processor.unreachable = True

    result = service.place(
        session,
        quote_id=quote_id,
        payer=payer,
        method=PaymentMethodKind.CARD,
        adapter=processor,
    )

    assert result.session is None
    assert result.order.payment_state is PaymentState.UNPAID

    processor.unreachable = False
    resumed = service.place(
        session,
        quote_id=quote_id,
        payer=payer,
        method=PaymentMethodKind.CARD,
        adapter=processor,
    )
    assert resumed.order.id == result.order.id
    assert resumed.session is not None


def test_checkout_is_refused_while_the_merchant_account_is_not_live(
    session: Session,
    service: CheckoutService,
    catalog: CatalogService,
    clock: Clock,
    processor: FakeProcessor,
) -> None:
    """D3/D4 in force: a sandbox that works is not merchant approval.

    The refusal happens *after* the quote is redeemed, which is deliberate —
    the price was claimed and the customer must not be able to reuse it — but
    before any order is committed by the route, which rolls back.
    """
    _entity, product, _market, _merchant = _sellable(
        session, clock, live_enabled=False
    )
    payer = _user(session)
    quote_id = _quote(session, catalog, product)

    with pytest.raises(PaymentRoutingError) as raised:
        service.place(
            session,
            quote_id=quote_id,
            payer=payer,
            method=PaymentMethodKind.CARD,
            adapter=processor,
        )
    assert raised.value.code == "live_collection_disabled"


def test_no_adapter_still_places_the_order(
    session: Session,
    service: CheckoutService,
    catalog: CatalogService,
    clock: Clock,
) -> None:
    """D4 is open, so "no processor" is today's state, not an error.

    The order and its intent exist and are recoverable. What does not exist is
    a redirect, because there is nowhere to redirect to.
    """
    _entity, product, _market, _merchant = _sellable(session, clock)
    payer = _user(session)
    quote_id = _quote(session, catalog, product)

    result = service.place(
        session,
        quote_id=quote_id,
        payer=payer,
        method=PaymentMethodKind.CARD,
        adapter=None,
    )

    assert result.session is None
    assert result.order.payment_state is PaymentState.UNPAID
    assert result.intent.amount == Decimal("10000.00")
