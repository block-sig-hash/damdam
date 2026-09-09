"""US-28 -- core domain identities and their invariants, against real PostgreSQL.

Every assertion here is about a constraint the database enforces, not one the
application promises. A CHECK that only exists in Python is not an invariant:
the migration, a fixture, a backfill script or a future service can all write
around it. These tests therefore run against PostgreSQL and expect the write to
be refused.
"""

import os
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.exc import DataError, IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.models import Organization, OrganizationType, User
from app.catalog.models import LegalEntity, Product, ProductKind, ProductPrice
from app.connectivity.models import (
    ActivationState,
    AssignedNumber,
    CarrierLine,
    Entitlement,
    EsimInstallation,
    InstallationState,
    NetworkState,
)
from app.orders.models import Order, OrderItem, PaymentState, ProvisioningState

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="core domain invariants require PostgreSQL",
)


@pytest.fixture
def session():
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
        session.rollback()


def _seller(session: Session) -> LegalEntity:
    entity = LegalEntity(code=f"E{uuid4().hex[:8]}", name="Undecided Ltd", country="NG")
    session.add(entity)
    session.flush()
    return entity


def _user(session: Session) -> User:
    user = User(phone_number=f"+234801{uuid4().hex[:7]}", platform="android")
    session.add(user)
    session.flush()
    return user


def _product(session: Session) -> Product:
    product = Product(
        sku=f"SKU-{uuid4().hex[:8]}", name="Global 5GB", kind=ProductKind.DATA
    )
    session.add(product)
    session.flush()
    return product


def _organization(session: Session) -> Organization:
    organization = Organization(
        org_type=OrganizationType.ENTERPRISE,
        name="Ministry",
        primary_contact_name="Procurement",
        email=f"{uuid4().hex[:8]}@example.test",
        password_hash="x",
        phone_number=f"+234802{uuid4().hex[:7]}",
    )
    session.add(organization)
    session.flush()
    return organization


def _order(session: Session, **overrides) -> Order:
    defaults = dict(
        reference=f"ORD-{uuid4().hex[:10]}",
        seller_legal_entity_id=_seller(session).id,
        payer_user_id=_user(session).id,
        currency="NGN",
        total_amount=Decimal("15000.00"),
    )
    defaults.update(overrides)
    order = Order(**defaults)
    session.add(order)
    return order


# --- money -----------------------------------------------------------------


def test_money_is_currency_explicit_and_rejects_a_non_iso_code(session) -> None:
    """No amount exists without the currency it is denominated in."""
    _order(session, currency="NGN")
    session.commit()

    session.add(_order(session, currency="ngn"))
    with pytest.raises((IntegrityError, DataError)):
        session.commit()


def test_amounts_keep_exact_decimal_precision(session) -> None:
    """A rate or a metered amount must not be rounded on the way in."""
    product = _product(session)
    price = ProductPrice(
        product_id=product.id,
        legal_entity_id=_seller(session).id,
        currency="USD",
        amount=Decimal("3.141593"),
        version=1,
        effective_from=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    session.add(price)
    session.commit()
    session.refresh(price)

    assert price.amount == Decimal("3.141593")


def test_a_negative_catalog_price_is_refused(session) -> None:
    """A price cannot create a credit by using a negative sale amount."""
    session.add(
        ProductPrice(
            product_id=_product(session).id,
            legal_entity_id=_seller(session).id,
            currency="USD",
            amount=Decimal("-0.000001"),
            version=1,
            effective_from=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_order_item_currency_must_match_its_order(session) -> None:
    """An item cannot silently add NGN to a USD order total."""
    order = _order(session, currency="USD", total_amount=Decimal("12.00"))
    session.flush()
    session.add(
        OrderItem(
            order_id=order.id,
            product_id=_product(session).id,
            recipient_user_id=_user(session).id,
            quantity=1,
            unit_currency="NGN",
            unit_amount=Decimal("12.00"),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_settlement_is_separate_from_charge_currency(session) -> None:
    """A USD charge may settle in NGN without overwriting either amount."""
    order = _order(
        session,
        currency="USD",
        total_amount=Decimal("10.00"),
        settlement_currency="NGN",
        settlement_amount=Decimal("15000.00"),
    )
    session.commit()
    session.refresh(order)

    assert order.currency == "USD"
    assert order.total_amount == Decimal("10.000000")
    assert order.settlement_currency == "NGN"
    assert order.settlement_amount == Decimal("15000.000000")


@pytest.mark.parametrize(
    ("settlement_currency", "settlement_amount"),
    [("NGN", None), (None, Decimal("15000.00"))],
)
def test_settlement_currency_and_amount_are_an_atomic_pair(
    session, settlement_currency, settlement_amount
) -> None:
    session.add(
        _order(
            session,
            settlement_currency=settlement_currency,
            settlement_amount=settlement_amount,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_a_negative_settlement_amount_is_refused(session) -> None:
    session.add(
        _order(
            session,
            settlement_currency="NGN",
            settlement_amount=Decimal("-0.000001"),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_settlement_rejects_a_non_iso_currency(session) -> None:
    session.add(
        _order(
            session,
            settlement_currency="ngn",
            settlement_amount=Decimal("15000.00"),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


# --- seller, payer, recipient ---------------------------------------------


def test_an_order_has_exactly_one_payer(session) -> None:
    """Payer is a role, and a payment with two payers has none."""
    organization = _organization(session)

    order = _order(session)
    order.payer_organization_id = organization.id
    session.add(order)
    with pytest.raises(IntegrityError):
        session.commit()


def test_an_order_with_no_payer_is_refused(session) -> None:
    order = _order(session, payer_user_id=None)
    session.add(order)
    with pytest.raises(IntegrityError):
        session.commit()


def test_an_organization_may_pay_for_another_persons_service(session) -> None:
    """Payer and recipient are separate parties, which is the whole point."""
    organization = _organization(session)
    recipient = _user(session)
    order = _order(session, payer_user_id=None, payer_organization_id=organization.id)
    session.add(order)
    session.flush()
    session.add(
        OrderItem(
            order_id=order.id,
            product_id=_product(session).id,
            recipient_user_id=recipient.id,
            quantity=1,
            unit_currency="NGN",
            unit_amount=Decimal("15000.00"),
        )
    )
    session.commit()

    item = session.exec(select(OrderItem).where(OrderItem.order_id == order.id)).one()
    assert item.recipient_user_id == recipient.id
    assert order.payer_user_id is None


def test_order_reference_is_unique(session) -> None:
    reference = f"ORD-{uuid4().hex[:10]}"
    session.add(_order(session, reference=reference))
    session.commit()
    session.add(_order(session, reference=reference))
    with pytest.raises(IntegrityError):
        session.commit()


# --- separated states ------------------------------------------------------


def test_payment_and_provisioning_are_separate_states(session) -> None:
    """A paid order may be pending provisioning; neither implies the other."""
    order = _order(session)
    order.payment_state = PaymentState.PAID
    session.add(order)
    session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=_product(session).id,
        recipient_user_id=_user(session).id,
        quantity=1,
        unit_currency="NGN",
        unit_amount=Decimal("15000.00"),
    )
    session.add(item)
    session.commit()
    session.refresh(item)

    assert order.payment_state is PaymentState.PAID
    assert item.provisioning_state is ProvisioningState.NOT_STARTED


def test_installation_activation_and_network_are_three_separate_states(session) -> None:
    """Installing a profile does not activate a line, and neither proves attachment."""
    order = _order(session)
    session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=_product(session).id,
        recipient_user_id=_user(session).id,
        quantity=1,
        unit_currency="NGN",
        unit_amount=Decimal("15000.00"),
    )
    session.add(item)
    session.flush()
    entitlement = Entitlement(
        order_item_id=item.id,
        holder_user_id=item.recipient_user_id,
        product_id=item.product_id,
        data_bytes_total=5 * 1024**3,
        voice_seconds_total=3600,
    )
    session.add(entitlement)
    session.flush()
    installation = EsimInstallation(
        entitlement_id=entitlement.id,
        installation_state=InstallationState.INSTALLED,
    )
    line = CarrierLine(
        entitlement_id=entitlement.id,
        carrier="telnyx",
        carrier_line_reference=f"line-{uuid4().hex[:8]}",
    )
    session.add(installation)
    session.add(line)
    session.commit()
    session.refresh(line)

    assert installation.installation_state is InstallationState.INSTALLED
    assert line.activation_state is ActivationState.PENDING
    assert line.network_state is NetworkState.UNKNOWN


def test_entitlement_units_are_exact_integers(session) -> None:
    """Bytes and seconds, not gigabytes and minutes -- no rounding at rest."""
    order = _order(session)
    session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=_product(session).id,
        recipient_user_id=_user(session).id,
        quantity=1,
        unit_currency="NGN",
        unit_amount=Decimal("1.00"),
    )
    session.add(item)
    session.flush()
    entitlement = Entitlement(
        order_item_id=item.id,
        holder_user_id=item.recipient_user_id,
        product_id=item.product_id,
        data_bytes_total=10_737_418_240,
        voice_seconds_total=5400,
    )
    session.add(entitlement)
    session.commit()
    session.refresh(entitlement)

    assert entitlement.data_bytes_total == 10_737_418_240
    assert entitlement.voice_seconds_total == 5400


def test_a_negative_entitlement_is_refused(session) -> None:
    order = _order(session)
    session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=_product(session).id,
        recipient_user_id=_user(session).id,
        quantity=1,
        unit_currency="NGN",
        unit_amount=Decimal("1.00"),
    )
    session.add(item)
    session.flush()
    session.add(
        Entitlement(
            order_item_id=item.id,
            holder_user_id=item.recipient_user_id,
            product_id=item.product_id,
            data_bytes_total=-1,
            voice_seconds_total=0,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


# --- numbers ---------------------------------------------------------------


def test_a_number_cannot_be_assigned_to_two_lines_at_once(session) -> None:
    """The invariant that matters: one live number, one line."""
    order = _order(session)
    session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=_product(session).id,
        recipient_user_id=_user(session).id,
        quantity=1,
        unit_currency="NGN",
        unit_amount=Decimal("1.00"),
    )
    session.add(item)
    session.flush()
    entitlement = Entitlement(
        order_item_id=item.id,
        holder_user_id=item.recipient_user_id,
        product_id=item.product_id,
        data_bytes_total=0,
        voice_seconds_total=0,
    )
    session.add(entitlement)
    session.flush()
    lines = []
    for _ in range(2):
        line = CarrierLine(
            entitlement_id=entitlement.id,
            carrier="telnyx",
            carrier_line_reference=f"line-{uuid4().hex[:8]}",
        )
        session.add(line)
        lines.append(line)
    session.flush()

    number = f"+1555{uuid4().int % 10_000_000:07d}"
    session.add(AssignedNumber(carrier_line_id=lines[0].id, e164=number, country="US"))
    session.commit()
    session.add(AssignedNumber(carrier_line_id=lines[1].id, e164=number, country="US"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_a_released_number_can_be_assigned_again(session) -> None:
    """Uniqueness is over live assignments, not over history."""
    order = _order(session)
    session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=_product(session).id,
        recipient_user_id=_user(session).id,
        quantity=1,
        unit_currency="NGN",
        unit_amount=Decimal("1.00"),
    )
    session.add(item)
    session.flush()
    entitlement = Entitlement(
        order_item_id=item.id,
        holder_user_id=item.recipient_user_id,
        product_id=item.product_id,
        data_bytes_total=0,
        voice_seconds_total=0,
    )
    session.add(entitlement)
    session.flush()
    first = CarrierLine(
        entitlement_id=entitlement.id,
        carrier="telnyx",
        carrier_line_reference=f"line-{uuid4().hex[:8]}",
    )
    second = CarrierLine(
        entitlement_id=entitlement.id,
        carrier="telnyx",
        carrier_line_reference=f"line-{uuid4().hex[:8]}",
    )
    session.add(first)
    session.add(second)
    session.flush()

    number = f"+1555{uuid4().int % 10_000_000:07d}"
    released = AssignedNumber(
        carrier_line_id=first.id,
        e164=number,
        country="US",
        released_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    session.add(released)
    session.commit()

    session.add(AssignedNumber(carrier_line_id=second.id, e164=number, country="US"))
    session.commit()

    rows = session.exec(
        select(AssignedNumber).where(AssignedNumber.e164 == number)
    ).all()
    assert len(rows) == 2


# --- referential integrity -------------------------------------------------


def test_an_order_item_cannot_reference_a_missing_order(session) -> None:
    session.add(
        OrderItem(
            order_id=uuid4(),
            product_id=_product(session).id,
            recipient_user_id=_user(session).id,
            quantity=1,
            unit_currency="NGN",
            unit_amount=Decimal("1.00"),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
