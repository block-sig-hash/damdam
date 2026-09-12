"""US-37 chunk 19 — the purchase journey over HTTP.

`test_checkout_postgres.py` proves the idempotency guarantee against real
database constraints. This file proves the *contract*: which status code each
outcome gets, what the app is allowed to learn, and that the browse screen and
the quote agree about what can be bought.

The status codes are load-bearing. **201 means an order was created; 200 means
one already existed.** An app that could not tell those apart would have to
guess whether a retry bought something, and guessing wrong in that direction is
a second charge.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

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
from app.catalog.service import CatalogService
from app.catalog.tariffs import DestinationKind, OriginKind, Tariff, TariffRate
from app.payments.contract import (
    AttemptStatus,
    MerchantAccount,
    MerchantPaymentMethod,
    PaymentAttempt,
    PaymentMethodKind,
)

NOW = datetime(2026, 7, 13, tzinfo=timezone.utc)

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason=(
        "a quote's digest is computed over stored amounts and timestamps; "
        "SQLite round-trips both differently and every read fails integrity"
    ),
)


@pytest.fixture
def session_factory():
    """The app, on real PostgreSQL, in a schema of its own.

    Overrides `conftest`'s SQLite factory, which `api` depends on — so the whole
    application under test runs against the database its constraints were
    written for. A per-test schema rather than a shared database because these
    tests publish markets and merchant accounts, and a leaked published market
    would make a later test's "nothing is on sale" assertion pass or fail
    depending on ordering.
    """
    url = os.environ["TEST_DATABASE_URL"]
    schema = f"checkout_{uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        SQLModel.metadata.create_all(engine)
        yield lambda: Session(engine)
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def client(api: FastAPI) -> TestClient:
    return TestClient(api)


def _user(session: Session, phone: str = "+2348010000001") -> User:
    user = User(
        phone_number=phone,
        email=f"buyer-{phone[-4:]}@example.test",
        locale=Locale.EN,
        status=UserStatus.ACTIVE,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    session.expunge(user)
    return user


def _auth(api: FastAPI, user: User) -> dict[str, str]:
    with api.state.session_factory() as session:
        pair = api.state.otp_service.tokens.issue(
            session, session.get(User, user.id), api.state.clock()
        )
        session.commit()
    return {"Authorization": f"Bearer {pair.access_token}"}


def _sellable(
    api: FastAPI,
    session: Session,
    *,
    requires_esim: bool = True,
    live_enabled: bool = True,
    with_offering: bool = True,
    with_coverage: bool = True,
    coverage_country: str = "NG",
    name: str = "Travel 5GB + calls",
) -> Product:
    """A published market with one purchasable product.

    None of this exists in a real deployment — D2 publishes no market, D3 seeds
    no seller and D4 approves no merchant. A test fixture may create them; the
    production catalog may not, and the `markets` test below asserts exactly
    that for an untouched database.
    """
    entity = LegalEntity(code=uuid4().hex[:8], name="Test Seller Ltd", country="NG")
    session.add(entity)
    session.commit()
    session.refresh(entity)

    product = Product(sku=uuid4().hex[:12], name=name, kind=ProductKind.BUNDLE)
    session.add(product)
    session.commit()
    session.refresh(product)

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
            amount=Decimal("10000.00"),
            version=1,
            effective_from=NOW - timedelta(days=1),
        )
    )
    if with_offering:
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
    if with_coverage:
        session.add(ProductCoverage(product_id=product.id, country=coverage_country))

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
    session.commit()
    session.refresh(tariff)
    session.add(
        TariffRate(
            tariff_id=tariff.id,
            origin_kind=OriginKind.CARRIER_VISITED_NETWORK,
            destination_country="NG",
            destination_kind=DestinationKind.MOBILE,
            per_minute_amount=Decimal("25.000000"),
            setup_amount=Decimal("0.00"),
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
    session.commit()
    session.refresh(market)
    CatalogService(clock=api.state.clock).publish_market(session, market, entity)

    merchant = MerchantAccount(
        legal_entity_id=entity.id,
        processor="fakepay",
        currency="NGN",
        live_enabled=live_enabled,
        approval_reference="approval-1",
    )
    session.add(merchant)
    session.flush()
    session.add(
        MerchantPaymentMethod(
            merchant_account_id=merchant.id, method=PaymentMethodKind.CARD
        )
    )
    session.commit()
    session.refresh(product)
    session.expunge(product)
    return product


def _quote(
    client: TestClient,
    headers: dict[str, str],
    product: Product,
    *,
    quantity: int = 1,
    supports_esim: bool | None = True,
) -> dict:
    response = client.post(
        "/v1/quotes",
        json={
            "country": "NG",
            "currency": "NGN",
            "lines": [{"product_id": str(product.id), "quantity": quantity}],
            "device": {"supports_esim": supports_esim, "is_unlocked": True},
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- what an untouched deployment sells ------------------------------------


def test_an_unseeded_deployment_sells_nothing_and_says_so(
    client: TestClient,
) -> None:
    """D2/D3 in one assertion.

    No market is published and no seller is seeded, so the catalog is empty.
    This is the shipping state, and the app must render it as "not on sale here"
    rather than as a loading failure.
    """
    markets = client.get("/v1/catalog/markets")
    assert markets.status_code == 200
    assert markets.json() == {"markets": []}

    products = client.get(
        "/v1/catalog/products", params={"country": "NG", "currency": "NGN"}
    )
    assert products.status_code == 404
    assert products.json()["error"] == "market_unavailable"


# --- browsing ---------------------------------------------------------------


def test_a_product_card_carries_everything_shown_before_payment(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    """The chunk's requirement, item by item.

    "Display full price/currency, assigned-number policy, included data/voice
    and supported call destinations before payment." All four come from the
    catalog rather than from copy in the app, because copy drifts from the
    tariff and the tariff is what the customer is charged against.
    """
    with session_factory() as session:
        product = _sellable(api, session)

    body = client.get(
        "/v1/catalog/products", params={"country": "NG", "currency": "NGN"}
    ).json()

    (card,) = body["products"]
    assert card["amount"] == "10000.00"
    assert card["currency"] == "NGN"
    assert card["data_bytes"] == 5_368_709_120
    assert card["voice_seconds"] == 3_600
    assert card["validity_days"] == 30
    assert card["number_type"] == "mobile"
    assert card["number_country"] == "NG"
    assert card["number_assignment"] == "new_assigned"
    assert card["coverage_countries"] == ["NG"]
    assert card["call_destinations"] == [
        {
            "country": "NG",
            "destination_kind": "mobile",
            # Full stored precision, not the currency's two places: a
            # per-minute rate rounded to kobo cannot represent a fraction of
            # one, and a metered charge built from the rounded number is wrong
            # by the difference every minute.
            "per_minute_amount": "25.0000000000",
            "setup_amount": "0.00",
            "increment_seconds": 60,
        }
    ]
    assert card["tariff_version"] == 1
    assert card["purchasable"] is False
    # Not checked is not incapable: the plan needs an eSIM and nobody has said
    # whether this phone has one.
    assert card["unavailable_reason"] == "device_not_checked"
    assert product.id == UUID(card["product_id"])


def test_a_phone_that_cannot_take_an_esim_is_told_why_not_left_guessing(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    """The plan stays listed. Hiding it would answer no question the customer has."""
    with session_factory() as session:
        _sellable(api, session)

    body = client.get(
        "/v1/catalog/products",
        params={
            "country": "NG",
            "currency": "NGN",
            "supports_esim": False,
            "is_unlocked": True,
        },
    ).json()

    (card,) = body["products"]
    assert card["purchasable"] is False
    assert card["unavailable_reason"] == "device_not_esim_capable"


def test_an_internet_only_plan_is_purchasable_by_a_phone_with_no_esim(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    """The calling amendment: internet-only checkout without eSIM gating."""
    with session_factory() as session:
        _sellable(api, session, requires_esim=False, name="Calling 100")

    body = client.get(
        "/v1/catalog/products",
        params={"country": "NG", "currency": "NGN", "supports_esim": False},
    ).json()

    (card,) = body["products"]
    assert card["requires_esim"] is False
    assert card["purchasable"] is True
    assert card["unavailable_reason"] is None


def test_a_plan_with_no_verified_supplier_is_listed_as_unavailable(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        _sellable(api, session, with_offering=False)

    body = client.get(
        "/v1/catalog/products",
        params={"country": "NG", "currency": "NGN", "supports_esim": True},
    ).json()

    (card,) = body["products"]
    assert card["purchasable"] is False
    assert card["unavailable_reason"] == "no_verified_supplier"


def test_a_plan_with_no_verified_coverage_cannot_be_bought(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        product = _sellable(api, session, with_coverage=False)
        user = _user(session)

    card = client.get(
        "/v1/catalog/products",
        params={"country": "NG", "currency": "NGN", "supports_esim": True},
    ).json()["products"][0]
    assert card["purchasable"] is False
    assert card["unavailable_reason"] == "coverage_unavailable"

    response = client.post(
        "/v1/quotes",
        json={
            "country": "NG",
            "currency": "NGN",
            "lines": [{"product_id": str(product.id), "quantity": 1}],
            "device": {"supports_esim": True, "is_unlocked": True},
        },
        headers=_auth(api, user),
    )
    assert response.status_code == 409
    assert response.json()["error"] == "coverage_unavailable"


def test_coverage_in_a_different_country_does_not_make_this_destination_sellable(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        product = _sellable(api, session, coverage_country="SA")
        user = _user(session)

    card = client.get(
        "/v1/catalog/products",
        params={"country": "NG", "currency": "NGN", "supports_esim": True},
    ).json()["products"][0]
    assert card["coverage_countries"] == ["SA"]
    assert card["purchasable"] is False
    assert card["unavailable_reason"] == "coverage_unavailable"

    response = client.post(
        "/v1/quotes",
        json={
            "country": "NG",
            "currency": "NGN",
            "lines": [{"product_id": str(product.id), "quantity": 1}],
            "device": {"supports_esim": True, "is_unlocked": True},
        },
        headers=_auth(api, user),
    )
    assert response.status_code == 409
    assert response.json()["error"] == "coverage_unavailable"


# --- quoting ----------------------------------------------------------------


def test_a_quote_is_server_priced_and_carries_its_own_expiry(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        product = _sellable(api, session)
        user = _user(session)

    body = _quote(client, _auth(api, user), product, quantity=2)

    assert body["subtotal_amount"] == "20000.00"
    assert body["total_amount"] == "20000.00"
    # Zero tax is not "no tax decided". The reference is null until D3 records
    # an entity and a treatment, and the app shows that rather than a 0% rate.
    assert body["tax_amount"] == "0.00"
    assert body["tax_configuration_reference"] is None
    assert body["status"] == "issued"
    assert datetime.fromisoformat(body["expires_at"]) > datetime.fromisoformat(
        body["issued_at"]
    )


def test_quoting_requires_a_session(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        product = _sellable(api, session)

    response = client.post(
        "/v1/quotes",
        json={
            "country": "NG",
            "currency": "NGN",
            "lines": [{"product_id": str(product.id), "quantity": 1}],
        },
    )
    assert response.status_code == 401


def test_an_expired_quote_reads_back_with_its_status_rather_than_failing(
    api: FastAPI, client: TestClient, session_factory: type[Session], clock
) -> None:
    """The review screen after a long pause, and after an app restart.

    Failing this read would leave the screen blank with an error toast, and the
    customer with no way to know their price expired or how to get another.
    """
    with session_factory() as session:
        product = _sellable(api, session)
        user = _user(session)
    headers = _auth(api, user)
    quote = _quote(client, headers, product)

    clock.advance(minutes=31)
    # The access token's TTL (15 minutes) is shorter than the quote's (30), so
    # advancing past the price's expiry also expires the session. A real
    # customer's app would have refreshed; this re-authenticates so the test is
    # about the quote rather than about the token.
    headers = _auth(api, user)

    response = client.get(f"/v1/quotes/{quote['quote_id']}", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "issued"
    assert datetime.fromisoformat(response.json()["expires_at"]) < clock.value


def test_a_quote_is_visible_only_to_the_account_that_requested_it(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        product = _sellable(api, session)
        buyer = _user(session, "+2348010000011")
        stranger = _user(session, "+2348010000012")
    quote = _quote(client, _auth(api, buyer), product)

    response = client.get(
        f"/v1/quotes/{quote['quote_id']}", headers=_auth(api, stranger)
    )

    assert response.status_code == 404
    assert response.json()["error"] == "quote_not_found"


def test_a_consumer_cannot_issue_a_quote_for_another_account(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        product = _sellable(api, session)
        buyer = _user(session, "+2348010000013")
        recipient = _user(session, "+2348010000014")

    response = client.post(
        "/v1/quotes",
        json={
            "country": "NG",
            "currency": "NGN",
            "lines": [
                {
                    "product_id": str(product.id),
                    "quantity": 1,
                    "recipient_user_id": str(recipient.id),
                }
            ],
            "device": {"supports_esim": True, "is_unlocked": True},
        },
        headers=_auth(api, buyer),
    )

    assert response.status_code == 403
    assert response.json()["error"] == "quote_not_yours"


def test_buying_an_expired_quote_is_refused_with_a_recoverable_error(
    api: FastAPI, client: TestClient, session_factory: type[Session], clock
) -> None:
    with session_factory() as session:
        product = _sellable(api, session)
        user = _user(session)
    headers = _auth(api, user)
    quote = _quote(client, headers, product)

    clock.advance(minutes=31)
    headers = _auth(api, user)

    response = client.post(
        "/v1/checkout", json={"quote_id": quote["quote_id"]}, headers=headers
    )
    assert response.status_code == 410
    assert response.json()["error"] == "quote_expired"


# --- checkout ---------------------------------------------------------------


def test_a_first_checkout_creates_an_order_and_a_repeat_returns_it(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    """The double tap, over HTTP, with the status codes that make it legible."""
    with session_factory() as session:
        product = _sellable(api, session)
        user = _user(session)
    headers = _auth(api, user)
    quote = _quote(client, headers, product)

    first = client.post(
        "/v1/checkout", json={"quote_id": quote["quote_id"]}, headers=headers
    )
    second = client.post(
        "/v1/checkout", json={"quote_id": quote["quote_id"]}, headers=headers
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert first.json()["resumed"] is False
    assert second.json()["resumed"] is True
    assert second.json()["order"]["order_id"] == first.json()["order"]["order_id"]

    orders = client.get("/v1/me/orders", headers=headers).json()["orders"]
    assert len(orders) == 1, "two orders would be two charges for one basket"


def test_a_replayed_quote_cannot_reveal_another_payers_order(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        product = _sellable(api, session)
        buyer = _user(session, "+2348010000015")
        stranger = _user(session, "+2348010000016")
    quote = _quote(client, _auth(api, buyer), product)
    assert (
        client.post(
            "/v1/checkout",
            json={"quote_id": quote["quote_id"]},
            headers=_auth(api, buyer),
        ).status_code
        == 201
    )

    replay = client.post(
        "/v1/checkout",
        json={"quote_id": quote["quote_id"]},
        headers=_auth(api, stranger),
    )

    assert replay.status_code == 403
    assert replay.json()["error"] == "quote_not_yours"


def test_checkout_with_no_processor_selected_still_places_a_recoverable_order(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    """D4's current state, expressed as an outcome the app can act on.

    No adapter is registered, so there is nowhere to send the customer. The
    order exists, is unpaid, and appears in their order list — which is what
    makes it recoverable when a processor is selected, rather than a basket
    that silently evaporated.
    """
    with session_factory() as session:
        product = _sellable(api, session)
        user = _user(session)
    headers = _auth(api, user)
    quote = _quote(client, headers, product)

    body = client.post(
        "/v1/checkout", json={"quote_id": quote["quote_id"]}, headers=headers
    ).json()

    assert body["outcome"] == "awaiting_processor"
    assert body["redirect_url"] is None
    assert body["order"]["payment_state"] == "unpaid"
    assert body["order"]["fulfilment_state"] == "not_started"


def test_checkout_is_refused_while_collection_is_switched_off(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    """A sandbox that works is not merchant approval (D3/D4).

    409 rather than 500: nothing is broken, and the app has to be able to say
    "we cannot take payments yet" without implying an outage.
    """
    with session_factory() as session:
        product = _sellable(api, session, live_enabled=False)
        user = _user(session)
    headers = _auth(api, user)
    quote = _quote(client, headers, product)

    response = client.post(
        "/v1/checkout", json={"quote_id": quote["quote_id"]}, headers=headers
    )

    assert response.status_code == 409
    assert response.json()["error"] == "live_collection_disabled"
    assert client.get("/v1/me/orders", headers=headers).json()["orders"] == []


def test_payment_methods_report_why_each_wallet_is_unavailable(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    """Four separate conditions, and the first true one is the useful answer."""
    with session_factory() as session:
        _sellable(api, session)
        user = _user(session)

    body = client.get(
        "/v1/checkout/methods",
        params={
            "country": "NG",
            "currency": "NGN",
            "device_offers_apple_pay": True,
        },
        headers=_auth(api, user),
    ).json()

    assert body["methods"] == []
    assert body["collection_enabled"] is False
    assert body["card_fallback_required"] is True
    reasons = {option["wallet"]: option["reason"] for option in body["wallets"]}
    # Not "your device does not offer Apple Pay" — the device does. D4 has not
    # selected a processor, and that is what has to be fixed.
    assert reasons["apple_pay"] == "no_processor_selected"
    assert reasons["google_pay"] == "no_processor_selected"


def test_payment_methods_only_offer_explicit_rails_for_the_selected_processor(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        _sellable(api, session)
        user = _user(session)
    api.state.payment_processor_adapter = SimpleNamespace(name="fakepay")
    try:
        body = client.get(
            "/v1/checkout/methods",
            params={"country": "NG", "currency": "NGN"},
            headers=_auth(api, user),
        ).json()
    finally:
        api.state.payment_processor_adapter = None

    assert body["collection_enabled"] is True
    assert body["methods"] == ["card"]
    assert "bank_transfer" not in body["methods"]


# --- orders and recovery ----------------------------------------------------


def test_an_order_is_visible_to_its_payer_and_to_nobody_else(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        product = _sellable(api, session)
        buyer = _user(session, "+2348010000002")
        stranger = _user(session, "+2348010000003")
    buyer_headers = _auth(api, buyer)
    quote = _quote(client, buyer_headers, product)
    order_id = client.post(
        "/v1/checkout", json={"quote_id": quote["quote_id"]}, headers=buyer_headers
    ).json()["order"]["order_id"]

    assert (
        client.get(f"/v1/me/orders/{order_id}", headers=buyer_headers).status_code
        == 200
    )
    other = client.get(f"/v1/me/orders/{order_id}", headers=_auth(api, stranger))
    # 404, not 403: the difference between "does not exist" and "is not yours"
    # is an oracle for whether a reference is real.
    assert other.status_code == 404
    assert other.json()["error"] == "order_not_found"


def test_an_order_survives_the_app_being_killed_and_reopened(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    """The recovery path AC-37.5 asks for, from the server's side.

    The app kept nothing but the order id. Everything the status screen needs
    comes back from the server, because the only trustworthy record of what was
    paid is the one that took the money.
    """
    with session_factory() as session:
        product = _sellable(api, session)
        user = _user(session)
    headers = _auth(api, user)
    quote = _quote(client, headers, product)
    placed = client.post(
        "/v1/checkout", json={"quote_id": quote["quote_id"]}, headers=headers
    ).json()

    recovered = client.get(
        f"/v1/me/orders/{placed['order']['order_id']}", headers=headers
    ).json()

    assert recovered["reference"] == placed["order"]["reference"]
    assert recovered["payment_state"] == "unpaid"
    assert recovered["quote_id"] == quote["quote_id"]
    assert recovered["payment_attempt_state"] == "created"
    assert recovered["total_amount"] == "10000.00"
    assert len(recovered["items"]) == 1


def test_order_recovery_reports_a_definitive_failed_attempt(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        product = _sellable(api, session)
        user = _user(session)
    headers = _auth(api, user)
    quote = _quote(client, headers, product)
    placed = client.post(
        "/v1/checkout", json={"quote_id": quote["quote_id"]}, headers=headers
    ).json()
    with session_factory() as session:
        attempt = session.exec(select(PaymentAttempt)).one()
        attempt.status = AttemptStatus.FAILED
        session.add(attempt)
        session.commit()

    recovered = client.get(
        f"/v1/me/orders/{placed['order']['order_id']}", headers=headers
    ).json()

    assert recovered["payment_attempt_state"] == "failed"


def test_a_quote_line_for_three_produces_three_visible_lines(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        product = _sellable(api, session)
        user = _user(session)
    headers = _auth(api, user)
    quote = _quote(client, headers, product, quantity=3)

    order = client.post(
        "/v1/checkout", json={"quote_id": quote["quote_id"]}, headers=headers
    ).json()["order"]

    assert len(order["items"]) == 3
    assert order["total_amount"] == "30000.00"
    # Each line recovers on its own, which is why they are separate rows.
    assert {item["provisioning_state"] for item in order["items"]} == {"not_started"}


def test_every_purchase_route_requires_a_session(client: TestClient) -> None:
    checkout = client.post("/v1/checkout", json={"quote_id": str(uuid4())})
    assert checkout.status_code == 401
    assert client.get("/v1/me/orders").status_code == 401
    assert client.get(f"/v1/me/orders/{uuid4()}").status_code == 401
    assert (
        client.get(
            "/v1/checkout/methods", params={"country": "NG", "currency": "NGN"}
        ).status_code
        == 401
    )
