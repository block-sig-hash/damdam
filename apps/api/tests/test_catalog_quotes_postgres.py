"""US-31 chunk 09 — catalog eligibility and immutable quotes, on PostgreSQL.

Written before the implementation. A quote is the server's promise of a price,
so every test here is somebody trying to make that promise mean something else:
a stale one redeemed late, a redeemed one redeemed twice, a tampered total, a
plan sold against a supplier that cannot deliver it, a market nobody verified.

The concurrency and constraint tests need a real database — a partial index, a
CHECK and an `UPDATE ... WHERE` are the things doing the work, and SQLite would
quietly not enforce any of them.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

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
from app.catalog.models import LegalEntity, Product, ProductKind, ProductPrice
from app.catalog.quotes import QuoteItem, QuoteStatus, compute_digest
from app.catalog.service import (
    CatalogError,
    CatalogService,
    DeviceFacts,
    LineRequest,
)
from app.catalog.tariffs import (
    DestinationKind,
    OriginKind,
    RateNotFoundError,
    Tariff,
    TariffRate,
    select_rate,
)

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="quote immutability and races require PostgreSQL",
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def engine():
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    return engine


TABLES = (
    "quote_items, quotes, tariff_rates, tariffs, product_coverage, "
    "provider_offerings, device_eligibility_rules, number_policies, "
    "region_countries, coverage_regions, sales_markets, product_prices, "
    "products, legal_entities, users"
)


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        session.exec(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        session.commit()
        yield session
        session.rollback()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def service(clock):
    return CatalogService(clock=clock)


# --- fixtures ---------------------------------------------------------------


def _entity(session: Session) -> LegalEntity:
    entity = LegalEntity(code=f"E{uuid4().hex[:6]}", name="Seller", country="NG")
    session.add(entity)
    session.flush()
    return entity


def _market(
    session: Session,
    entity: LegalEntity | None = None,
    country: str = "NG",
    currency: str = "NGN",
    status: PublicationStatus = PublicationStatus.PUBLISHED,
) -> SalesMarket:
    verified = status is not PublicationStatus.DRAFT
    market = SalesMarket(
        country=country,
        currency=currency,
        status=status,
        legal_entity_id=entity.id if entity else None,
        evidence_reference="DECISIONS.md D2 fixture" if verified else None,
        verified_at=NOW if verified else None,
        published_at=NOW if status is PublicationStatus.PUBLISHED else None,
    )
    session.add(market)
    session.flush()
    return market


def _product(
    session: Session, kind: ProductKind = ProductKind.DATA, sku: str | None = None
) -> Product:
    product = Product(
        sku=sku or f"sku-{uuid4().hex[:8]}", name="Plan", kind=kind, active=True
    )
    session.add(product)
    session.flush()
    return product


def _price(
    session: Session,
    product: Product,
    entity: LegalEntity,
    amount: str = "1000.00",
    currency: str = "NGN",
    version: int = 1,
    effective_from: datetime = NOW - timedelta(days=1),
    effective_to: datetime | None = None,
) -> ProductPrice:
    price = ProductPrice(
        product_id=product.id,
        legal_entity_id=entity.id,
        currency=currency,
        amount=Decimal(amount),
        version=version,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    session.add(price)
    session.flush()
    return price


def _offering(
    session: Session,
    product: Product,
    *,
    data: bool = True,
    native_voice: bool = False,
    internet_voice: bool = False,
    status: PublicationStatus = PublicationStatus.PUBLISHED,
) -> ProviderOffering:
    offering = ProviderOffering(
        product_id=product.id,
        provider="telnyx",
        provider_sku=f"sku-{uuid4().hex[:6]}",
        status=status,
        supports_data=data,
        supports_native_voice=native_voice,
        supports_internet_voice=internet_voice,
        evidence_reference="chunk 03 capability matrix",
        verified_at=NOW,
    )
    session.add(offering)
    session.flush()
    return offering


def _eligibility(
    session: Session, product: Product, requires_esim: bool = True
) -> DeviceEligibilityRule:
    rule = DeviceEligibilityRule(product_id=product.id, requires_esim=requires_esim)
    session.add(rule)
    session.flush()
    return rule


def _tariff(
    session: Session,
    product: Product,
    currency: str = "NGN",
    version: int = 1,
    status: PublicationStatus = PublicationStatus.PUBLISHED,
) -> Tariff:
    tariff = Tariff(
        product_id=product.id,
        currency=currency,
        version=version,
        status=status,
        effective_from=NOW - timedelta(days=1),
        evidence_reference="V01 rate fixture",
        verified_at=NOW,
    )
    session.add(tariff)
    session.flush()
    return tariff


def _sellable_data_product(session, service, currency="NGN", country="NG"):
    entity = _entity(session)
    market = _market(session, entity, country=country, currency=currency)
    product = _product(session)
    _price(session, product, entity, currency=currency)
    _offering(session, product, data=True)
    _eligibility(session, product)
    session.commit()
    return entity, market, product


ESIM_PHONE = DeviceFacts(supports_esim=True, is_unlocked=True)


# --- publication gating -----------------------------------------------------


class TestPublicationGating:
    def test_an_unpublished_market_cannot_be_quoted(self, session, service):
        entity = _entity(session)
        _market(session, entity, status=PublicationStatus.VERIFIED)
        product = _product(session)
        _price(session, product, entity)
        _offering(session, product)
        _eligibility(session, product)
        session.commit()

        with pytest.raises(CatalogError) as excinfo:
            service.issue_quote(
                session, "NG", "NGN", [LineRequest(product.id)], ESIM_PHONE
            )
        assert excinfo.value.code == "market_unavailable"

    def test_an_absent_market_fails_the_same_way_as_an_unpublished_one(
        self, session, service
    ):
        # Otherwise the difference tells a caller which markets are coming.
        with pytest.raises(CatalogError) as excinfo:
            service.issue_quote(
                session, "ZW", "NGN", [LineRequest(uuid4())], ESIM_PHONE
            )
        assert excinfo.value.code == "market_unavailable"

    def test_the_database_refuses_a_verified_market_with_no_evidence(self, session):
        session.add(
            SalesMarket(
                country="GB",
                currency="GBP",
                status=PublicationStatus.VERIFIED,
                evidence_reference=None,
                verified_at=None,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_the_database_refuses_publishing_without_a_seller(self, session):
        # Where D3 bites: legal_entities is deliberately unseeded.
        session.add(
            SalesMarket(
                country="GB",
                currency="GBP",
                status=PublicationStatus.PUBLISHED,
                legal_entity_id=None,
                evidence_reference="ref",
                verified_at=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_publishing_a_draft_market_is_refused_by_the_service(
        self, session, service
    ):
        entity = _entity(session)
        market = _market(session, entity, status=PublicationStatus.DRAFT)
        session.commit()
        with pytest.raises(CatalogError) as excinfo:
            service.publish_market(session, market, entity)
        assert excinfo.value.code == "market_not_verified"

    def test_an_inactive_seller_cannot_publish_or_keep_selling(
        self, session, service
    ):
        entity = _entity(session)
        market = _market(session, entity, status=PublicationStatus.VERIFIED)
        entity.active = False
        session.add(entity)
        session.commit()

        with pytest.raises(CatalogError) as excinfo:
            service.publish_market(session, market, entity)
        assert excinfo.value.code == "seller_inactive"

        market.status = PublicationStatus.PUBLISHED
        market.published_at = NOW
        session.add(market)
        session.commit()
        product = _product(session)
        _price(session, product, entity)
        _offering(session, product)
        _eligibility(session, product)
        session.commit()
        with pytest.raises(CatalogError) as excinfo:
            service.issue_quote(
                session, "NG", "NGN", [LineRequest(product.id)], ESIM_PHONE
            )
        assert excinfo.value.code == "market_unavailable"


# --- supplier capability ----------------------------------------------------


class TestCapability:
    def test_a_data_only_supplier_cannot_satisfy_a_voice_plan(self, session, service):
        """The rule AGENTS.md names outright.

        Aggregate supplier data coverage is not native-voice eligibility, and
        selling on that basis produces a customer with a line that cannot call.
        """
        entity = _entity(session)
        _market(session, entity)
        product = _product(session, kind=ProductKind.VOICE)
        _price(session, product, entity)
        _offering(session, product, data=True, native_voice=False, internet_voice=False)
        _eligibility(session, product)
        session.commit()

        with pytest.raises(CatalogError) as excinfo:
            service.issue_quote(
                session, "NG", "NGN", [LineRequest(product.id)], ESIM_PHONE
            )
        assert excinfo.value.code == "supplier_capability_mismatch"

    def test_a_bundle_needs_both_halves_from_one_offering(self, session, service):
        # Two offerings that each do half do not add up to one line a supplier
        # will actually fulfil.
        entity = _entity(session)
        _market(session, entity)
        product = _product(session, kind=ProductKind.BUNDLE)
        _price(session, product, entity)
        _offering(session, product, data=True, native_voice=False)
        _offering(session, product, data=False, native_voice=True)
        _eligibility(session, product)
        _tariff(session, product)
        session.commit()

        with pytest.raises(CatalogError) as excinfo:
            service.issue_quote(
                session, "NG", "NGN", [LineRequest(product.id)], ESIM_PHONE
            )
        assert excinfo.value.code == "supplier_capability_mismatch"

    def test_an_unpublished_offering_does_not_count(self, session, service):
        entity = _entity(session)
        _market(session, entity)
        product = _product(session)
        _price(session, product, entity)
        _offering(session, product, status=PublicationStatus.VERIFIED)
        _eligibility(session, product)
        session.commit()

        with pytest.raises(CatalogError) as excinfo:
            service.issue_quote(
                session, "NG", "NGN", [LineRequest(product.id)], ESIM_PHONE
            )
        assert excinfo.value.code == "no_verified_supplier"

    def test_capabilities_default_to_absent(self, session):
        # An unverified capability is an absent capability. Defaulting to true
        # would make every new offering claim everything.
        product = _product(session)
        offering = ProviderOffering(
            product_id=product.id, provider="x", provider_sku="y"
        )
        session.add(offering)
        session.commit()
        session.refresh(offering)
        assert offering.supports_data is False
        assert offering.supports_native_voice is False
        assert offering.supports_number_assignment is False

    def test_a_voice_plan_needs_a_published_tariff(self, session, service):
        entity = _entity(session)
        _market(session, entity)
        product = _product(session, kind=ProductKind.VOICE)
        _price(session, product, entity)
        _offering(session, product, data=False, native_voice=True)
        _eligibility(session, product)
        _tariff(session, product, status=PublicationStatus.VERIFIED)
        session.commit()

        with pytest.raises(CatalogError) as excinfo:
            service.issue_quote(
                session, "NG", "NGN", [LineRequest(product.id)], ESIM_PHONE
            )
        assert excinfo.value.code == "tariff_unavailable"


# --- device eligibility -----------------------------------------------------


class TestDeviceEligibility:
    def test_an_esim_plan_is_refused_for_an_incapable_phone(self, session, service):
        _, _, product = _sellable_data_product(session, service)
        with pytest.raises(CatalogError) as excinfo:
            service.issue_quote(
                session,
                "NG",
                "NGN",
                [LineRequest(product.id)],
                DeviceFacts(supports_esim=False),
            )
        assert excinfo.value.code == "device_not_esim_capable"

    def test_an_unchecked_device_is_refused_rather_than_assumed_capable(
        self, session, service
    ):
        # Checked-and-incapable and not-checked are different states. Accepting
        # the second sells an eSIM to a phone that cannot take one.
        _, _, product = _sellable_data_product(session, service)
        with pytest.raises(CatalogError) as excinfo:
            service.issue_quote(
                session, "NG", "NGN", [LineRequest(product.id)], DeviceFacts()
            )
        assert excinfo.value.code == "device_not_checked"

    def test_an_unchecked_unlock_state_is_refused(self, session, service):
        _, _, product = _sellable_data_product(session, service)
        with pytest.raises(CatalogError) as excinfo:
            service.issue_quote(
                session,
                "NG",
                "NGN",
                [LineRequest(product.id)],
                DeviceFacts(supports_esim=True, is_unlocked=None),
            )
        assert excinfo.value.code == "device_lock_not_checked"

    def test_an_internet_only_offer_needs_no_esim_check_at_all(self, session, service):
        """VOICE-EXPANSION.md: internet calling is sold without an eSIM."""
        entity = _entity(session)
        _market(session, entity)
        product = _product(session, kind=ProductKind.VOICE)
        _price(session, product, entity)
        _offering(session, product, data=False, internet_voice=True)
        _eligibility(session, product, requires_esim=False)
        _tariff(session, product)
        session.commit()

        quote, items = service.issue_quote(
            session, "NG", "NGN", [LineRequest(product.id)], DeviceFacts()
        )
        session.commit()
        assert quote.total_amount == Decimal("1000.00")
        assert items[0].tariff_id is not None

    def test_a_product_with_no_device_rule_cannot_be_sold(self, session, service):
        entity = _entity(session)
        _market(session, entity)
        product = _product(session)
        _price(session, product, entity)
        _offering(session, product)
        session.commit()

        with pytest.raises(CatalogError) as excinfo:
            service.issue_quote(
                session, "NG", "NGN", [LineRequest(product.id)], ESIM_PHONE
            )
        assert excinfo.value.code == "device_rule_missing"


# --- quotes -----------------------------------------------------------------


class TestQuotes:
    def test_a_quote_pins_the_price_version_it_was_made_from(self, session, service):
        entity, _, product = _sellable_data_product(session, service)
        quote, items = service.issue_quote(
            session, "NG", "NGN", [LineRequest(product.id)], ESIM_PHONE
        )
        session.commit()
        original_total = quote.total_amount
        pinned = items[0].product_price_id

        # The price changes afterwards.
        _price(
            session,
            product,
            entity,
            amount="2500.00",
            version=2,
            effective_from=NOW - timedelta(minutes=1),
        )
        session.commit()

        redeemed = service.load_for_redemption(session, quote.id)
        assert redeemed.total_amount == original_total
        assert items[0].product_price_id == pinned

    def test_a_later_price_applies_to_the_next_quote(self, session, service):
        entity, _, product = _sellable_data_product(session, service)
        _price(
            session,
            product,
            entity,
            amount="2500.00",
            version=2,
            effective_from=NOW - timedelta(minutes=1),
        )
        session.commit()
        quote, _ = service.issue_quote(
            session, "NG", "NGN", [LineRequest(product.id)], ESIM_PHONE
        )
        assert quote.total_amount == Decimal("2500.00")

    def test_expiry_is_exclusive_at_the_exact_boundary(self, session, service, clock):
        _, _, product = _sellable_data_product(session, service)
        quote, _ = service.issue_quote(
            session, "NG", "NGN", [LineRequest(product.id)], ESIM_PHONE
        )
        session.commit()

        expiry = quote.expires_at.replace(tzinfo=timezone.utc)
        clock.value = expiry - timedelta(seconds=1)
        assert service.load_for_redemption(session, quote.id).id == quote.id

        clock.value = expiry
        with pytest.raises(CatalogError) as excinfo:
            service.load_for_redemption(session, quote.id)
        assert excinfo.value.code == "quote_expired"

    def test_a_redeemed_quote_cannot_be_redeemed_again(self, session, service):
        _, _, product = _sellable_data_product(session, service)
        quote, _ = service.issue_quote(
            session, "NG", "NGN", [LineRequest(product.id)], ESIM_PHONE
        )
        session.commit()
        service.redeem(session, quote.id)
        session.commit()

        with pytest.raises(CatalogError) as excinfo:
            service.redeem(session, quote.id)
        assert excinfo.value.code == "quote_already_redeemed"

    def test_a_tampered_total_is_detected(self, session, service):
        """Belt to the trigger's braces.

        The trigger stops an `UPDATE`; this catches rows reached another way --
        a restore, a manual psql session, a migration with a bug in it.

        The tamper is *internally consistent* on purpose. `ck_quotes_total_is_sum`
        already refuses a total that does not equal its parts, so a crude edit
        never reaches the digest check -- writing this test found that. What the
        constraint cannot know is whether those parts are the ones the server
        issued, and a subtotal that no longer matches its own lines is exactly
        the shape a bad restore leaves behind. That is what the digest is for.
        """
        _, _, product = _sellable_data_product(session, service)
        quote, _ = service.issue_quote(
            session, "NG", "NGN", [LineRequest(product.id)], ESIM_PHONE
        )
        session.commit()

        # Bypass both the ORM and the trigger, the way a restore would.
        session.exec(text("ALTER TABLE quotes DISABLE TRIGGER trg_quotes_immutable"))
        session.exec(
            text(
                "UPDATE quotes SET subtotal_amount = 1, total_amount = 1 "
                "WHERE id = CAST(:id AS uuid)"
            ).bindparams(id=str(quote.id))
        )
        session.exec(text("ALTER TABLE quotes ENABLE TRIGGER trg_quotes_immutable"))
        session.commit()
        session.expire_all()

        with pytest.raises(CatalogError) as excinfo:
            service.load_for_redemption(session, quote.id)
        assert excinfo.value.code == "quote_tampered"

    def test_the_database_refuses_to_edit_a_priced_column(self, session, service):
        # The immutability that is not a promise about code.
        _, _, product = _sellable_data_product(session, service)
        quote, _ = service.issue_quote(
            session, "NG", "NGN", [LineRequest(product.id)], ESIM_PHONE
        )
        session.commit()

        with pytest.raises(Exception) as excinfo:
            session.exec(
                text(
                    "UPDATE quotes SET total_amount = 1 WHERE id = CAST(:id AS uuid)"
                ).bindparams(id=str(quote.id))
            )
            session.commit()
        assert "immutable" in str(excinfo.value).lower()
        session.rollback()

    def test_the_database_allows_the_status_transition(self, session, service):
        _, _, product = _sellable_data_product(session, service)
        quote, _ = service.issue_quote(
            session, "NG", "NGN", [LineRequest(product.id)], ESIM_PHONE
        )
        session.commit()
        service.redeem(session, quote.id)
        session.commit()
        session.refresh(quote)
        assert quote.status is QuoteStatus.REDEEMED

    def test_a_redeemed_quote_cannot_be_reopened_in_the_database(
        self, session, service
    ):
        _, _, product = _sellable_data_product(session, service)
        quote, _ = service.issue_quote(
            session, "NG", "NGN", [LineRequest(product.id)], ESIM_PHONE
        )
        service.redeem(session, quote.id)
        session.commit()

        with pytest.raises(Exception) as excinfo:
            session.exec(
                text(
                    "UPDATE quotes SET status = 'issued', redeemed_at = NULL "
                    "WHERE id = CAST(:id AS uuid)"
                ).bindparams(id=str(quote.id))
            )
            session.commit()
        assert "terminal" in str(excinfo.value).lower()
        session.rollback()

    def test_quote_items_cannot_be_deleted(self, session, service):
        _, _, product = _sellable_data_product(session, service)
        quote, items = service.issue_quote(
            session, "NG", "NGN", [LineRequest(product.id)], ESIM_PHONE
        )
        session.commit()

        with pytest.raises(Exception) as excinfo:
            session.exec(
                text("DELETE FROM quote_items WHERE id = CAST(:id AS uuid)").bindparams(
                    id=str(items[0].id)
                )
            )
            session.commit()
        assert "immutable" in str(excinfo.value).lower()
        session.rollback()

    def test_a_quote_item_cannot_carry_a_different_currency(self, session, service):
        _, _, product = _sellable_data_product(session, service)
        quote, _ = service.issue_quote(
            session, "NG", "NGN", [LineRequest(product.id)], ESIM_PHONE
        )
        session.commit()
        session.add(
            QuoteItem(
                quote_id=quote.id,
                product_id=product.id,
                product_price_id=uuid4(),
                quantity=1,
                unit_currency="USD",
                unit_amount=Decimal("1.00"),
                line_amount=Decimal("1.00"),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_quantity_multiplies_the_line_and_the_total(self, session, service):
        _, _, product = _sellable_data_product(session, service)
        quote, items = service.issue_quote(
            session, "NG", "NGN", [LineRequest(product.id, quantity=7)], ESIM_PHONE
        )
        assert items[0].line_amount == Decimal("7000.00")
        assert quote.total_amount == Decimal("7000.00")

    def test_an_unsupported_currency_is_refused_before_anything_is_priced(
        self, session, service
    ):
        with pytest.raises(CatalogError) as excinfo:
            service.issue_quote(session, "NG", "ZZZ", [LineRequest(uuid4())])
        assert excinfo.value.code == "currency_unsupported"

    def test_a_zero_exponent_currency_quotes_whole_units(self, session, service):
        entity = _entity(session)
        _market(session, entity, country="JP", currency="JPY")
        product = _product(session)
        _price(session, product, entity, amount="1234.56", currency="JPY")
        _offering(session, product)
        _eligibility(session, product)
        session.commit()

        quote, items = service.issue_quote(
            session, "JP", "JPY", [LineRequest(product.id)], ESIM_PHONE
        )
        assert str(items[0].unit_amount) == "1235"
        assert str(quote.total_amount) == "1235"

    def test_concurrent_redemption_claims_the_quote_once(self, engine, service):
        with Session(engine) as setup:
            setup.exec(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
            setup.commit()
            _, _, product = _sellable_data_product(setup, service)
            quote, _ = service.issue_quote(
                setup, "NG", "NGN", [LineRequest(product.id)], ESIM_PHONE
            )
            setup.commit()
            quote_id = quote.id

        barrier = Barrier(2)

        def redeem(_: int) -> str:
            with Session(engine) as scoped:
                barrier.wait(timeout=10)
                try:
                    service.redeem(scoped, quote_id)
                    scoped.commit()
                    return "ok"
                except CatalogError as exc:
                    scoped.rollback()
                    return exc.code
                except Exception:
                    scoped.rollback()
                    return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(redeem, range(2)))

        assert outcomes.count("ok") == 1, outcomes

    def test_the_digest_covers_the_items_not_just_the_header(self, session, service):
        _, _, product = _sellable_data_product(session, service)
        quote, items = service.issue_quote(
            session, "NG", "NGN", [LineRequest(product.id)], ESIM_PHONE
        )
        before = compute_digest(quote, items)
        items[0].quantity = 99
        assert compute_digest(quote, items) != before


# --- tariff rate selection --------------------------------------------------


class TestRateSelection:
    def _rates(self) -> list[TariffRate]:
        common = {
            "tariff_id": uuid4(),
            "destination_country": "GB",
            "destination_kind": DestinationKind.MOBILE,
            "setup_amount": Decimal("0"),
        }
        return [
            TariffRate(
                origin_kind=OriginKind.INTERNET,
                origin_country=None,
                per_minute_amount=Decimal("10"),
                **common,
            ),
            TariffRate(
                origin_kind=OriginKind.INTERNET,
                origin_country="NG",
                per_minute_amount=Decimal("5"),
                **common,
            ),
            TariffRate(
                origin_kind=OriginKind.CARRIER_VISITED_NETWORK,
                origin_country=None,
                per_minute_amount=Decimal("20"),
                **common,
            ),
        ]

    def test_an_exact_origin_country_beats_the_wildcard(self):
        rate = select_rate(
            self._rates(), OriginKind.INTERNET, "NG", "GB", DestinationKind.MOBILE
        )
        assert rate.per_minute_amount == Decimal("5")

    def test_an_unlisted_origin_country_falls_back_to_the_wildcard(self):
        rate = select_rate(
            self._rates(), OriginKind.INTERNET, "KE", "GB", DestinationKind.MOBILE
        )
        assert rate.per_minute_amount == Decimal("10")

    def test_it_never_falls_back_across_origin_kind(self):
        """A roaming rate is not a substitute for a missing internet rate.

        Using one because it happens to be there prices a call at a number that
        describes a different call.
        """
        internet_only = [
            rate
            for rate in self._rates()
            if rate.origin_kind is OriginKind.CARRIER_VISITED_NETWORK
        ]
        with pytest.raises(RateNotFoundError):
            select_rate(
                internet_only, OriginKind.INTERNET, "NG", "GB", DestinationKind.MOBILE
            )

    def test_an_unpriced_destination_raises_rather_than_guessing(self):
        with pytest.raises(RateNotFoundError):
            select_rate(
                self._rates(), OriginKind.INTERNET, "NG", "FR", DestinationKind.MOBILE
            )

    def test_destination_kind_is_part_of_the_match(self):
        with pytest.raises(RateNotFoundError):
            select_rate(
                self._rates(),
                OriginKind.INTERNET,
                "NG",
                "GB",
                DestinationKind.PREMIUM,
            )


# --- the four countries are four columns ------------------------------------


class TestSeparateCountries:
    def test_coverage_number_and_market_are_recorded_separately(self, session):
        """The collapse `prd.md` §10 warns about, made structurally impossible."""
        entity = _entity(session)
        market = _market(session, entity, country="NG", currency="NGN")
        product = _product(session, kind=ProductKind.VOICE)
        session.add(ProductCoverage(product_id=product.id, country="SA"))
        session.add(
            NumberPolicy(
                product_id=product.id,
                number_type=NumberType.MOBILE,
                number_country="GB",
                assignment=NumberAssignment.NEW_ASSIGNED,
            )
        )
        session.commit()

        # Sold in Nigeria, works in Saudi Arabia, number issued in Britain.
        # Three different countries, and none of them implies another.
        assert market.country == "NG"
        coverage = session.exec(
            select(ProductCoverage).where(ProductCoverage.product_id == product.id)
        ).one()
        policy = session.exec(
            select(NumberPolicy).where(NumberPolicy.product_id == product.id)
        ).one()
        assert coverage.country == "SA"
        assert policy.number_country == "GB"

    def test_a_number_policy_of_none_may_not_name_a_country(self, session):
        product = _product(session)
        session.add(
            NumberPolicy(
                product_id=product.id,
                number_type=NumberType.NONE,
                number_country="GB",
                assignment=NumberAssignment.NONE,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
