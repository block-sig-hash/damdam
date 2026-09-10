"""US-37 chunk 18 — the consumer service read, against PostgreSQL.

The HTTP contract is in `test_consumer_session_api.py`. This file exists for the
two things SQLite cannot answer honestly:

- the read runs against the **real enum types and real foreign keys** the
  migrations create, so a summary that only assembles under SQLite's permissive
  typing is caught here rather than in staging;
- the **reassignment case**, where the person who was sold a line and the person
  who holds it are different rows. An enterprise line assigned to an employee has
  `order_items.recipient_user_id` naming the employee and
  `entitlements.holder_user_id` naming them too -- but a *later* reassignment
  moves only the holder. A customer whose line was reassigned to them must still
  see it, and the buyer must not keep seeing it as theirs to install.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from app import model_registry  # noqa: F401  -- completes SQLModel.metadata
from app.auth.models import (
    Locale,
    Organization,
    OrganizationType,
    User,
    UserStatus,
)
from app.catalog.models import LegalEntity, Product, ProductKind
from app.connectivity.models import (
    ActivationState,
    CarrierLine,
    Entitlement,
    EsimInstallation,
    InstallationState,
)
from app.consumer.schemas import ServiceDelivery, ServiceOwner, ServiceState
from app.consumer.service import ConsumerService
from app.orders.models import Order, OrderItem, PaymentState, ProvisioningState

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="the consumer service read is validated against real enum types",
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
TABLES = (
    "carrier_lines, esim_installations, entitlements, order_items, orders, "
    "products, legal_entities, organizations, users"
)


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


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
def service() -> ConsumerService:
    return ConsumerService(clock=Clock())


def _user(session: Session, phone: str) -> User:
    user = User(phone_number=phone, locale=Locale.EN, status=UserStatus.ACTIVE)
    session.add(user)
    session.flush()
    return user


def _organization(session: Session, name: str) -> Organization:
    organization = Organization(
        org_type=OrganizationType.ENTERPRISE,
        name=name,
        primary_contact_name="Contact",
        email=f"{uuid4().hex[:10]}@example.test",
        password_hash="unused",
        phone_number="+2348000000000",
        locale=Locale.EN,
    )
    session.add(organization)
    session.flush()
    return organization


def _sold(
    session: Session,
    *,
    recipient: User,
    payer_user: User | None = None,
    payer_organization: Organization | None = None,
    reference: str = "ORD-1",
    kind: ProductKind = ProductKind.BUNDLE,
    provisioning_state: ProvisioningState = ProvisioningState.PROVISIONED,
) -> OrderItem:
    seller = LegalEntity(code=uuid4().hex[:8], name="Seller", country="NG")
    product = Product(sku=uuid4().hex[:12], name="Travel 5GB", kind=kind)
    session.add(seller)
    session.add(product)
    session.flush()
    order = Order(
        reference=reference,
        seller_legal_entity_id=seller.id,
        payer_user_id=payer_user.id if payer_user else None,
        payer_organization_id=(
            payer_organization.id if payer_organization else None
        ),
        currency="NGN",
        total_amount=Decimal("10000.00"),
        payment_state=PaymentState.PAID,
        placed_at=NOW,
    )
    session.add(order)
    session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        recipient_user_id=recipient.id,
        unit_currency="NGN",
        unit_amount=Decimal("10000.00"),
        provisioning_state=provisioning_state,
    )
    session.add(item)
    session.flush()
    return item


def _grant(
    session: Session,
    item: OrderItem,
    holder: User,
    *,
    expires_at: datetime | None = None,
) -> Entitlement:
    entitlement = Entitlement(
        order_item_id=item.id,
        holder_user_id=holder.id,
        product_id=item.product_id,
        data_bytes_total=5_368_709_120,
        voice_seconds_total=3_600,
        granted_at=NOW,
        expires_at=expires_at,
    )
    session.add(entitlement)
    session.flush()
    return entitlement


def _install(
    session: Session,
    entitlement: Entitlement,
    *,
    installed: bool,
    activation: ActivationState,
) -> None:
    session.add(
        EsimInstallation(
            entitlement_id=entitlement.id,
            installation_state=(
                InstallationState.INSTALLED
                if installed
                else InstallationState.NOT_INSTALLED
            ),
            installed_at=NOW if installed else None,
        )
    )
    session.add(
        CarrierLine(
            entitlement_id=entitlement.id,
            carrier="telnyx",
            carrier_line_reference=uuid4().hex,
            activation_state=activation,
            created_at=NOW,
        )
    )
    session.flush()


def test_a_reassigned_line_follows_its_holder_not_its_buyer(
    session: Session, service: ConsumerService
) -> None:
    """The employee who now holds the line sees it; nobody else gains a copy.

    `recipient_user_id` records who the line was bought for and never changes --
    it is what an invoice and an audit trail are read against. `holder_user_id`
    is who has it now. Reading only the first would hide a reassigned line from
    the person actually carrying it, and reading only the second would drop a
    paid-but-unprovisioned item from the buyer's own order list, because an
    entitlement does not exist until provisioning grants one.
    """
    buyer = _user(session, "+2348011111111")
    holder = _user(session, "+2348022222222")
    organization = _organization(session, "Acme Logistics")
    item = _sold(
        session,
        recipient=buyer,
        payer_organization=organization,
        reference="ORD-REASSIGN",
    )
    entitlement = _grant(session, item, buyer)
    _install(session, entitlement, installed=True, activation=ActivationState.ACTIVE)
    session.commit()

    # The reassignment: only the holder moves.
    entitlement.holder_user_id = holder.id
    session.add(entitlement)
    session.commit()

    holder_view = service.services(session, holder)
    buyer_view = service.services(session, buyer)

    assert holder_view.state is ServiceState.ACTIVE
    assert [summary.order_reference for summary in holder_view.services] == [
        "ORD-REASSIGN"
    ]
    assert holder_view.services[0].owner is ServiceOwner.ORGANIZATION
    assert holder_view.services[0].organization_name == "Acme Logistics"

    # The buyer keeps the purchase record -- the order item still names them --
    # which is what makes the receipt and the support conversation possible.
    assert [summary.order_reference for summary in buyer_view.services] == [
        "ORD-REASSIGN"
    ]


def test_an_internet_grant_and_a_carrier_line_on_one_account_stay_separate(
    session: Session, service: ConsumerService
) -> None:
    """Both delivery modes at once, which is the account shape the amendment creates.

    Internet calling is sellable without an eSIM, so a customer can hold a
    usable internet grant while their carrier line is still uninstalled. The
    account is `ACTIVE` -- something works -- and the carrier line must still
    report `requires_installation`, or the app will never offer the install step.
    """
    user = _user(session, "+2348033333333")
    internet_item = _sold(
        session,
        recipient=user,
        payer_user=user,
        reference="ORD-INTERNET",
        kind=ProductKind.VOICE,
    )
    _grant(session, internet_item, user)

    carrier_item = _sold(
        session,
        recipient=user,
        payer_user=user,
        reference="ORD-CARRIER",
    )
    carrier_entitlement = _grant(session, carrier_item, user)
    _install(
        session,
        carrier_entitlement,
        installed=False,
        activation=ActivationState.PENDING,
    )
    session.commit()

    view = service.services(session, user)
    by_reference = {summary.order_reference: summary for summary in view.services}

    assert view.state is ServiceState.ACTIVE
    assert by_reference["ORD-INTERNET"].delivery is ServiceDelivery.INTERNET
    assert by_reference["ORD-INTERNET"].requires_installation is False
    assert by_reference["ORD-INTERNET"].ready_to_use is True
    assert by_reference["ORD-CARRIER"].delivery is ServiceDelivery.CARRIER_ESIM
    assert by_reference["ORD-CARRIER"].requires_installation is True
    assert by_reference["ORD-CARRIER"].ready_to_use is False

    # Usable service first: the account's own working line should not sort below
    # an order it is still waiting on.
    assert view.services[0].order_reference == "ORD-INTERNET"


def test_an_expired_grant_stops_being_usable_without_being_deleted(
    session: Session, service: ConsumerService
) -> None:
    user = _user(session, "+2348044444444")
    item = _sold(session, recipient=user, payer_user=user, reference="ORD-EXPIRED")
    entitlement = _grant(
        session, item, user, expires_at=NOW - timedelta(seconds=1)
    )
    _install(session, entitlement, installed=True, activation=ActivationState.ACTIVE)
    session.commit()

    view = service.services(session, user)

    assert view.state is ServiceState.NONE
    (summary,) = view.services
    assert summary.expired is True
    assert summary.ready_to_use is False
    # Still installed and still active with the carrier: the profile has not
    # gone anywhere, and telling the customer otherwise would send them to
    # reinstall something that is already on the phone.
    assert summary.installation_state == InstallationState.INSTALLED.value
    assert summary.activation_state == ActivationState.ACTIVE.value


def test_a_suspended_line_is_not_reported_as_ready(
    session: Session, service: ConsumerService
) -> None:
    """Suspension is chunk 17's answer to an exhausted allowance.

    It is not an installation problem and not a payment problem, and the
    customer's route out is a top-up. Reporting it as ready would send them to a
    line that will not carry traffic.
    """
    user = _user(session, "+2348055555555")
    item = _sold(session, recipient=user, payer_user=user, reference="ORD-SUSPENDED")
    entitlement = _grant(session, item, user)
    _install(
        session, entitlement, installed=True, activation=ActivationState.SUSPENDED
    )
    session.commit()

    view = service.services(session, user)

    assert view.state is ServiceState.PENDING
    assert view.services[0].ready_to_use is False
    assert view.services[0].activation_state == ActivationState.SUSPENDED.value
