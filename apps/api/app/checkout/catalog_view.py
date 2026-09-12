"""Reading the catalog the way a customer browses it (US-37, chunk 19).

Chunk 09 built the catalog as a set of independent, correctly-separated tables:
what is sold, what it costs, who sells it, where it works, which supplier will
deliver it, what device it needs, which number it gets and what its calls cost.
Correct, and eight joins away from a screen.

This assembles them into one product card and refuses to smooth over the gaps.
A product with no published offering is **listed and marked unpurchasable with a
reason**, rather than hidden: a customer whose phone cannot take an eSIM needs to
know that is why the plan is greyed out, not to watch it disappear.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from sqlmodel import Session, col, select

from app.catalog.market import (
    DeviceEligibilityRule,
    NumberPolicy,
    ProductCoverage,
    PublicationStatus,
    SalesMarket,
)
from app.catalog.models import LegalEntity, Product, ProductAllowance, ProductPrice
from app.catalog.service import CatalogError, CatalogService, DeviceFacts
from app.catalog.tariffs import Tariff, TariffRate
from app.checkout.schemas import (
    CallDestination,
    MarketSummary,
    ProductSummary,
)
from app.money import format_money


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class CatalogViewService:
    def __init__(
        self, catalog: CatalogService, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self.catalog = catalog
        self.clock = clock

    def markets(self, session: Session) -> list[MarketSummary]:
        """Published markets only.

        Today that is an empty list in any real deployment, and that is the
        correct answer rather than a bug: D2 keeps every market unpublishable
        and nothing is seeded. An app that showed a draft market would be
        offering to sell somewhere nobody has cleared.
        """
        rows = session.exec(
            select(SalesMarket, LegalEntity)
            .join(
                LegalEntity,
                col(LegalEntity.id) == col(SalesMarket.legal_entity_id),
            )
            .where(SalesMarket.status == PublicationStatus.PUBLISHED)
            .order_by(col(SalesMarket.country), col(SalesMarket.currency))
        ).all()
        return [
            MarketSummary(
                country=market.country,
                currency=market.currency,
                seller_name=entity.name,
            )
            for market, entity in rows
        ]

    def products(
        self,
        session: Session,
        country: str,
        currency: str,
        device: DeviceFacts,
    ) -> list[ProductSummary]:
        market = session.exec(
            select(SalesMarket).where(
                SalesMarket.country == country,
                SalesMarket.currency == currency,
                SalesMarket.status == PublicationStatus.PUBLISHED,
            )
        ).first()
        if market is None or market.legal_entity_id is None:
            # Same answer for "no such market" and "not published yet", matching
            # `CatalogService._published_market`: a caller probing which markets
            # are coming next learns nothing from the difference.
            raise CatalogError(
                "market_unavailable", f"{country}/{currency} is not on sale"
            )

        now = self.clock()
        summaries: list[ProductSummary] = []
        for product in session.exec(
            select(Product)
            .where(col(Product.active).is_(True))
            .order_by(col(Product.name))
        ).all():
            price = self._price(session, product, market.legal_entity_id, currency, now)
            if price is None:
                # No price from this seller in this currency is not a product
                # with a hidden price; it is a product this market does not
                # sell. Listing it with no amount would be worse than omitting
                # it, because there would be nothing to decide from.
                continue

            coverage = [
                row.country
                for row in session.exec(
                    select(ProductCoverage)
                    .where(ProductCoverage.product_id == product.id)
                    .order_by(col(ProductCoverage.country))
                ).all()
            ]
            allowance = session.exec(
                select(ProductAllowance).where(
                    ProductAllowance.product_id == product.id
                )
            ).first()
            rule = session.exec(
                select(DeviceEligibilityRule).where(
                    DeviceEligibilityRule.product_id == product.id
                )
            ).first()
            policy = session.exec(
                select(NumberPolicy).where(NumberPolicy.product_id == product.id)
            ).first()
            tariff, destinations = self._destinations(session, product, currency, now)

            purchasable, reason = self._purchasable(session, product, device)
            if country not in coverage:
                # Supplier capability is not visited-network coverage. The
                # consumer may see the plan, but cannot buy a profile that is
                # not verified for the country they selected.
                purchasable, reason = False, "coverage_unavailable"
            if allowance is None:
                # Chunk 15's rule: provisioning cannot invent what the customer
                # bought. A product with no allowance cannot be sold, and the
                # card says so rather than showing a plan with no contents.
                purchasable, reason = False, "allowance_missing"

            summaries.append(
                ProductSummary(
                    product_id=product.id,
                    sku=product.sku,
                    name=product.name,
                    kind=product.kind.value,
                    currency=currency,
                    amount=format_money(price.amount, currency),
                    data_bytes=allowance.data_bytes if allowance else 0,
                    voice_seconds=allowance.voice_seconds if allowance else 0,
                    validity_days=allowance.validity_days if allowance else None,
                    requires_esim=rule.requires_esim if rule else True,
                    requires_unlocked_device=(
                        rule.requires_unlocked_device if rule else True
                    ),
                    device_notes=rule.notes if rule else None,
                    number_type=policy.number_type.value if policy else "none",
                    number_country=policy.number_country if policy else None,
                    number_assignment=policy.assignment.value if policy else "none",
                    coverage_countries=coverage,
                    call_destinations=destinations,
                    tariff_version=tariff.version if tariff else None,
                    purchasable=purchasable,
                    unavailable_reason=reason,
                )
            )
        return summaries

    def _purchasable(
        self, session: Session, product: Product, device: DeviceFacts
    ) -> tuple[bool, str | None]:
        """Ask the real check, and report its refusal verbatim.

        Reusing `assert_fulfillable` rather than re-deriving eligibility here is
        the point: a browse screen that says "available" where quoting says
        "no verified supplier" is a screen that sells something the customer
        cannot have.
        """
        try:
            self.catalog.assert_fulfillable(session, product, device)
        except CatalogError as exc:
            return False, exc.code
        return True, None

    @staticmethod
    def _price(
        session: Session,
        product: Product,
        legal_entity_id: object,
        currency: str,
        now: datetime,
    ) -> ProductPrice | None:
        prices = session.exec(
            select(ProductPrice).where(
                ProductPrice.product_id == product.id,
                ProductPrice.legal_entity_id == legal_entity_id,
                ProductPrice.currency == currency,
            )
        ).all()
        live = [
            price
            for price in prices
            if _aware(price.effective_from) <= now
            and (price.effective_to is None or _aware(price.effective_to) > now)
        ]
        if not live:
            return None
        return max(live, key=lambda price: price.version)

    @staticmethod
    def _destinations(
        session: Session, product: Product, currency: str, now: datetime
    ) -> tuple[Tariff | None, list[CallDestination]]:
        tariffs = session.exec(
            select(Tariff).where(
                Tariff.product_id == product.id,
                Tariff.currency == currency,
                Tariff.status == PublicationStatus.PUBLISHED,
            )
        ).all()
        live = [
            tariff
            for tariff in tariffs
            if _aware(tariff.effective_from) <= now
            and (tariff.effective_to is None or _aware(tariff.effective_to) > now)
        ]
        if not live:
            return None, []
        tariff = max(live, key=lambda row: row.version)
        rates = session.exec(
            select(TariffRate)
            .where(TariffRate.tariff_id == tariff.id)
            .order_by(col(TariffRate.destination_country))
        ).all()
        return tariff, [
            CallDestination(
                country=rate.destination_country,
                destination_kind=rate.destination_kind.value,
                # Rates carry more decimal places than money does — a per-minute
                # price rounded to the currency's scale is a price that cannot
                # represent a fraction of a kobo, and a metered charge built
                # from it is wrong by the difference every minute.
                per_minute_amount=str(rate.per_minute_amount),
                setup_amount=format_money(rate.setup_amount, currency),
                increment_seconds=rate.increment_seconds,
            )
            for rate in rates
        ]
