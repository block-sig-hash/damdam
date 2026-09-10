"""US-29 chunk 07 outcome 5 — personal lines, organization lines, and reassignment.

Written before the implementation, per the strict-TDD policy for tenant
isolation and object-level authorization.

The attack these tests describe is one request parameter: an administrator of
organization A sending organization B's `order_item_id`, or sending a
`recipient_user_id` belonging to somebody outside their tenant. Both move a
purchased line -- and the service, usage and personal data attached to it -- to
the wrong person, and neither is caught by any check that reads the item first
and trusts the body second.
"""

import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from app.auth.models import (
    Locale,
    Organization,
    OrganizationType,
    Platform,
    User,
)
from app.catalog.models import LegalEntity, Product, ProductKind
from app.orders.models import Order, OrderItem
from app.organizations.models import OrganizationRole
from app.organizations.ownership import (
    OwnershipError,
    assign_recipient,
    resolve_order,
)
from app.organizations.service import MembershipService

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="order constraints and the payer XOR require PostgreSQL",
)


@pytest.fixture
def engine():
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        session.exec(
            text(
                "TRUNCATE order_items, orders, product_prices, products, "
                "legal_entities, organization_members, organizations, "
                "account_identifiers, refresh_tokens, users "
                "RESTART IDENTITY CASCADE"
            )
        )
        session.commit()
        yield session
        session.rollback()


@pytest.fixture
def memberships():
    return MembershipService()


def _user(session: Session, label: str) -> User:
    user = User(
        phone_number=f"+23484{abs(hash(label)) % 10**8:08d}",
        first_name=label,
        platform=Platform.ANDROID,
    )
    session.add(user)
    session.flush()
    return user


def _organization(session: Session, name: str) -> Organization:
    organization = Organization(
        org_type=OrganizationType.ENTERPRISE,
        name=name,
        primary_contact_name="Contact",
        email=f"{name.lower()}-{uuid4().hex[:8]}@example.test",
        password_hash="unused",
        phone_number="+2348000000000",
        locale=Locale.EN,
    )
    session.add(organization)
    session.flush()
    return organization


def _catalog(session: Session) -> tuple[LegalEntity, Product]:
    entity = LegalEntity(code=f"E{uuid4().hex[:6]}", name="Seller", country="NG")
    product = Product(
        sku=f"sku-{uuid4().hex[:8]}",
        name="Connectivity",
        kind=ProductKind.BUNDLE,
    )
    session.add(entity)
    session.add(product)
    session.flush()
    return entity, product


def _order(
    session: Session,
    entity: LegalEntity,
    product: Product,
    *,
    organization: Organization | None = None,
    user: User | None = None,
) -> tuple[Order, OrderItem]:
    order = Order(
        reference=f"ord-{uuid4().hex[:12]}",
        seller_legal_entity_id=entity.id,
        payer_organization_id=None if organization is None else organization.id,
        payer_user_id=None if user is None else user.id,
        currency="NGN",
        total_amount=Decimal("1000.00"),
    )
    session.add(order)
    session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        unit_currency="NGN",
        unit_amount=Decimal("1000.00"),
    )
    session.add(item)
    session.flush()
    return order, item


# --- reaching a resource through the wrong tenant --------------------------


def test_another_tenants_order_reads_as_absent(session):
    acme = _organization(session, "Acme")
    other = _organization(session, "Other")
    entity, product = _catalog(session)
    order, _ = _order(session, entity, product, organization=other)
    session.commit()

    with pytest.raises(OwnershipError) as excinfo:
        resolve_order(session, acme.id, order.id)
    # Absent, not forbidden: "forbidden" would confirm the id exists elsewhere.
    assert excinfo.value.code == "order_not_found"


def test_an_order_id_that_does_not_exist_is_indistinguishable(session):
    acme = _organization(session, "Acme")
    session.commit()
    with pytest.raises(OwnershipError) as excinfo:
        resolve_order(session, acme.id, uuid4())
    assert excinfo.value.code == "order_not_found"


def test_a_personal_order_is_not_reachable_by_any_organization(session):
    """An employer must not be able to take over a line an employee bought."""
    acme = _organization(session, "Acme")
    buyer = _user(session, "buyer")
    entity, product = _catalog(session)
    order, _ = _order(session, entity, product, user=buyer)
    session.commit()

    with pytest.raises(OwnershipError) as excinfo:
        resolve_order(session, acme.id, order.id)
    assert excinfo.value.code == "order_not_found"


# --- reassignment by request parameter ------------------------------------


def test_an_item_from_another_tenant_cannot_be_reassigned(session, memberships):
    acme = _organization(session, "Acme")
    other = _organization(session, "Other")
    staff = _user(session, "acme-staff")
    memberships.seed_member(session, acme, staff, OrganizationRole.MEMBER)
    entity, product = _catalog(session)
    _, foreign_item = _order(session, entity, product, organization=other)
    session.commit()

    with pytest.raises(OwnershipError) as excinfo:
        assign_recipient(session, acme.id, foreign_item.id, staff.id)
    assert excinfo.value.code == "order_item_not_found"
    session.rollback()
    assert session.get(OrderItem, foreign_item.id).recipient_user_id is None


def test_a_recipient_outside_the_organization_is_refused(session, memberships):
    acme = _organization(session, "Acme")
    other = _organization(session, "Other")
    outsider = _user(session, "outsider")
    memberships.seed_member(session, other, outsider, OrganizationRole.MEMBER)
    entity, product = _catalog(session)
    _, item = _order(session, entity, product, organization=acme)
    session.commit()

    with pytest.raises(OwnershipError) as excinfo:
        assign_recipient(session, acme.id, item.id, outsider.id)
    assert excinfo.value.code == "recipient_not_in_organization"


def test_a_private_individual_is_refused_as_a_recipient(session):
    """Nobody is enrolled into an organization by being named on its order."""
    acme = _organization(session, "Acme")
    stranger = _user(session, "stranger")
    entity, product = _catalog(session)
    _, item = _order(session, entity, product, organization=acme)
    session.commit()

    with pytest.raises(OwnershipError) as excinfo:
        assign_recipient(session, acme.id, item.id, stranger.id)
    assert excinfo.value.code == "recipient_not_in_organization"


def test_a_revoked_member_is_refused_as_a_recipient(session, memberships):
    acme = _organization(session, "Acme")
    owner = _user(session, "owner")
    leaver = _user(session, "leaver")
    owner_membership = memberships.seed_member(
        session, acme, owner, OrganizationRole.OWNER
    )
    memberships.seed_member(session, acme, leaver, OrganizationRole.MEMBER)
    entity, product = _catalog(session)
    _, item = _order(session, entity, product, organization=acme)
    session.commit()
    memberships.revoke(session, actor=owner_membership, target_user_id=leaver.id)
    session.commit()

    with pytest.raises(OwnershipError) as excinfo:
        assign_recipient(session, acme.id, item.id, leaver.id)
    assert excinfo.value.code == "recipient_not_in_organization"


def test_a_member_of_the_paying_organization_is_assigned(session, memberships):
    acme = _organization(session, "Acme")
    staff = _user(session, "staff")
    memberships.seed_member(session, acme, staff, OrganizationRole.MEMBER)
    entity, product = _catalog(session)
    _, item = _order(session, entity, product, organization=acme)
    session.commit()

    assigned = assign_recipient(session, acme.id, item.id, staff.id)
    session.commit()
    assert assigned.recipient_user_id == staff.id
