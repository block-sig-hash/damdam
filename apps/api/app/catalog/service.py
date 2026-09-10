"""Catalog eligibility and quoting (US-31, chunk 09).

The rule everything here serves: **an offer nobody has verified cannot be
bought.** Not hidden in the UI — refused by the server, at the moment somebody
tries to turn it into money.

D1 (carrier capability), D2 (markets and coverage), D3 (selling entity) and D4
(merchant approval) are all open. Rather than guess at any of them, publication
requires recorded evidence and quoting requires publication, so the open
decisions express themselves as things that will not sell rather than as claims
that turn out to be false.
"""

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import CursorResult, update
from sqlmodel import Session, col, select

from app.auth.models import utc_now
from app.catalog.market import (
    DeviceEligibilityRule,
    ProductCoverage,
    ProviderOffering,
    PublicationStatus,
    SalesMarket,
)
from app.catalog.models import LegalEntity, Product, ProductKind, ProductPrice
from app.catalog.quotes import (
    Quote,
    QuoteItem,
    QuoteStatus,
    compute_digest,
)
from app.catalog.tariffs import Tariff
from app.money import CurrencyError, round_money, sum_money


class CatalogError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


@dataclass(frozen=True)
class LineRequest:
    """What a caller asks for. Note what is absent: any amount."""

    product_id: UUID
    quantity: int = 1
    recipient_user_id: UUID | None = None


@dataclass(frozen=True)
class DeviceFacts:
    """What we know about the device a line is destined for.

    `None` means "not checked". Deliberately distinct from "checked and
    incapable": refusing an unchecked device would block every internet-only
    purchase, and accepting one would sell an eSIM to a phone that cannot take
    it.
    """

    supports_esim: bool | None = None
    is_unlocked: bool | None = None


#: "Nothing is known about the device." A module-level singleton because a
#: mutable default argument is a footgun and ruff is right to refuse one.
UNCHECKED_DEVICE = DeviceFacts()


class CatalogService:
    #: How long a quote holds its price. Short enough that a rate change is not
    #: outrun by a stale quote, long enough to finish a checkout.
    QUOTE_TTL = timedelta(minutes=30)

    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self.clock = clock

    # --- publication ------------------------------------------------------

    def publish_market(
        self, session: Session, market: SalesMarket, legal_entity: LegalEntity
    ) -> SalesMarket:
        """Publishing needs evidence and a seller, and says so.

        The seller requirement is where D3 bites: `legal_entities` is
        deliberately unseeded, so in a real deployment there is nothing to pass
        here until the decision is recorded.
        """
        if market.status is PublicationStatus.DRAFT:
            raise CatalogError(
                "market_not_verified",
                "record the evidence and verify the market before publishing it",
            )
        if market.evidence_reference is None or market.verified_at is None:
            raise CatalogError("market_not_verified")
        now = self.clock()
        market.legal_entity_id = legal_entity.id
        market.status = PublicationStatus.PUBLISHED
        market.published_at = now
        session.add(market)
        session.flush()
        return market

    def _published_market(
        self, session: Session, country: str, currency: str
    ) -> SalesMarket:
        market = session.exec(
            select(SalesMarket).where(
                SalesMarket.country == country,
                SalesMarket.currency == currency,
                SalesMarket.status == PublicationStatus.PUBLISHED,
            )
        ).first()
        if market is None:
            # One code for "no such market" and "not published yet". A caller
            # probing which markets are coming next learns nothing.
            raise CatalogError(
                "market_unavailable", f"{country}/{currency} is not on sale"
            )
        return market

    # --- eligibility ------------------------------------------------------

    def assert_fulfillable(
        self, session: Session, product: Product, device: DeviceFacts
    ) -> ProviderOffering:
        """Find a published offering that can actually deliver this product.

        The check `AGENTS.md` names explicitly: a data-only adapter cannot
        satisfy a native-voice plan. Aggregate supplier data coverage is not
        voice eligibility, and this is where that stops being a slogan.
        """
        offerings = session.exec(
            select(ProviderOffering).where(
                ProviderOffering.product_id == product.id,
                ProviderOffering.status == PublicationStatus.PUBLISHED,
            )
        ).all()
        if not offerings:
            raise CatalogError("no_verified_supplier")

        capable = [
            offering
            for offering in offerings
            if self._offering_satisfies(product, offering)
        ]
        if not capable:
            raise CatalogError(
                "supplier_capability_mismatch",
                f"no published offering for {product.sku} advertises the "
                f"capability a {product.kind.value} product needs",
            )

        self.assert_device_eligible(session, product, device)
        return capable[0]

    @staticmethod
    def _offering_satisfies(product: Product, offering: ProviderOffering) -> bool:
        if product.kind is ProductKind.DATA:
            return offering.supports_data
        if product.kind is ProductKind.VOICE:
            # Either mode counts as voice capability; which one a customer gets
            # is the number policy's and V02's business, not the catalog's.
            return offering.supports_native_voice or offering.supports_internet_voice
        # A bundle needs both halves from the same offering. Two offerings that
        # each do half do not add up to one line the supplier will fulfil.
        return offering.supports_data and (
            offering.supports_native_voice or offering.supports_internet_voice
        )

    def assert_device_eligible(
        self, session: Session, product: Product, device: DeviceFacts
    ) -> None:
        rule = session.exec(
            select(DeviceEligibilityRule).where(
                DeviceEligibilityRule.product_id == product.id
            )
        ).first()
        if rule is None:
            # No rule is not "no requirement". A product whose device rule
            # nobody wrote is a product nobody decided was installable.
            raise CatalogError("device_rule_missing")
        if not rule.requires_esim:
            # An internet-only offer. No eSIM check at all -- which is the
            # point of selling it to someone whose phone cannot take one.
            return
        if device.supports_esim is None:
            raise CatalogError(
                "device_not_checked",
                "this plan needs an eSIM; check the device before quoting",
            )
        if not device.supports_esim:
            raise CatalogError("device_not_esim_capable")
        if rule.requires_unlocked_device and device.is_unlocked is False:
            raise CatalogError("device_locked")

    def covers(self, session: Session, product: Product, country: str) -> bool:
        return (
            session.exec(
                select(ProductCoverage).where(
                    ProductCoverage.product_id == product.id,
                    ProductCoverage.country == country,
                )
            ).first()
            is not None
        )

    # --- pricing ----------------------------------------------------------

    def _current_price(
        self,
        session: Session,
        product: Product,
        legal_entity_id: UUID,
        currency: str,
        now: datetime,
    ) -> ProductPrice:
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
            raise CatalogError(
                "price_unavailable",
                f"{product.sku} has no live {currency} price for this seller",
            )
        # Highest version wins if two windows overlap. Overlapping windows are
        # a data error, but picking deterministically beats picking whichever
        # row the planner returned first.
        return max(live, key=lambda price: price.version)

    def _published_tariff(
        self, session: Session, product: Product, currency: str, now: datetime
    ) -> Tariff | None:
        if product.kind is ProductKind.DATA:
            return None
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
            raise CatalogError(
                "tariff_unavailable",
                f"{product.sku} sells calls but has no published {currency} tariff",
            )
        return max(live, key=lambda tariff: tariff.version)

    # --- quoting ----------------------------------------------------------

    def issue_quote(
        self,
        session: Session,
        country: str,
        currency: str,
        lines: list[LineRequest],
        device: DeviceFacts = UNCHECKED_DEVICE,
    ) -> tuple[Quote, list[QuoteItem]]:
        """Price a basket, on the server, from published versions only."""
        if not lines:
            raise CatalogError("empty_quote")
        try:
            round_money(Decimal(0), currency)
        except CurrencyError as exc:
            raise CatalogError("currency_unsupported", str(exc)) from exc

        now = self.clock()
        market = self._published_market(session, country, currency)
        assert market.legal_entity_id is not None  # the publish constraint

        # Built whole, then inserted once. The immutability trigger refuses any
        # UPDATE to a priced column -- including the service's own -- so a
        # quote that is inserted empty and then filled in cannot exist. That is
        # the constraint doing its job, not an inconvenience to work around.
        quote_id = uuid4()
        items: list[QuoteItem] = []
        for line in lines:
            if line.quantity < 1:
                raise CatalogError("invalid_quantity")
            product = session.get(Product, line.product_id)
            if product is None or not product.active:
                raise CatalogError("product_unavailable")

            self.assert_fulfillable(session, product, device)
            price = self._current_price(
                session, product, market.legal_entity_id, currency, now
            )
            tariff = self._published_tariff(session, product, currency, now)

            unit_amount = round_money(price.amount, currency)
            items.append(
                QuoteItem(
                    quote_id=quote_id,
                    product_id=product.id,
                    product_price_id=price.id,
                    tariff_id=tariff.id if tariff else None,
                    recipient_user_id=line.recipient_user_id,
                    quantity=line.quantity,
                    unit_currency=currency,
                    unit_amount=unit_amount,
                    # The line is the rounded unit times quantity, so somebody
                    # adding up the receipt gets the number at the bottom.
                    line_amount=unit_amount * line.quantity,
                )
            )

        subtotal = sum_money([item.line_amount for item in items], currency)
        # Tax and fees stay zero until D3 records an entity and a treatment.
        # Charging an invented rate would put a number on an invoice that no
        # authority asked for.
        tax = round_money(Decimal(0), currency)
        fee = round_money(Decimal(0), currency)
        quote = Quote(
            id=quote_id,
            reference=f"QT-{secrets.token_hex(8).upper()}",
            seller_legal_entity_id=market.legal_entity_id,
            sales_market_id=market.id,
            currency=currency,
            subtotal_amount=subtotal,
            tax_amount=tax,
            tax_configuration_reference=None,
            fee_amount=fee,
            total_amount=sum_money([subtotal, tax, fee], currency),
            issued_at=now,
            expires_at=now + self.QUOTE_TTL,
            digest="",
        )
        quote.digest = compute_digest(quote, items)

        session.add(quote)
        for item in items:
            session.add(item)
        session.flush()
        return quote, items

    def load_for_redemption(self, session: Session, quote_id: UUID) -> Quote:
        """Re-check everything before the quote becomes money.

        Order matters. Existence, then status, then expiry, then integrity —
        so a caller cannot use the difference between two failures to learn
        anything about a quote that is not theirs.
        """
        quote = session.get(Quote, quote_id)
        if quote is None:
            raise CatalogError("quote_not_found")
        if quote.status is QuoteStatus.REDEEMED:
            raise CatalogError("quote_already_redeemed")
        if quote.status is QuoteStatus.VOID:
            raise CatalogError("quote_void")

        now = self.clock()
        if now >= _aware(quote.expires_at):
            raise CatalogError("quote_expired")

        items = list(
            session.exec(
                select(QuoteItem).where(QuoteItem.quote_id == quote.id)
            ).all()
        )
        if compute_digest(quote, items) != quote.digest:
            # Reached the rows some way the trigger does not see: a restore, a
            # manual session, a migration with a bug in it.
            raise CatalogError("quote_tampered")
        return quote

    def redeem(self, session: Session, quote_id: UUID) -> Quote:
        """Claim the quote exactly once.

        The `UPDATE ... WHERE status = 'issued'` is what makes it once: two
        simultaneous checkouts both load the same issued quote, and only one
        reports a row changed.
        """
        quote = self.load_for_redemption(session, quote_id)
        now = self.clock()
        claimed = cast(
            "CursorResult[Any]",
            session.execute(
                update(Quote)
                .where(
                    col(Quote.id) == quote.id,
                    col(Quote.status) == QuoteStatus.ISSUED,
                )
                .values(status=QuoteStatus.REDEEMED, redeemed_at=now)
            ),
        )
        if claimed.rowcount != 1:
            raise CatalogError("quote_already_redeemed")
        session.refresh(quote)
        return quote


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
