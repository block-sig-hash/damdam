"""US-37 chunk 18 — the consumer session, service and invitation-preview reads.

Three questions this file exists to answer, because getting any of them wrong
produces a screen that lies to the customer:

1. **Does an internet-only account have service?** Yes, with no eSIM installed
   and no carrier line, because there is nothing to install. The calling
   amendment requires the internet-only journey to reach account/services
   without forced installation, and an API that reports `pending` until a
   profile appears would make that journey impossible in the app regardless of
   what the app draws.

2. **Does a paid, provisioned, *uninstalled* carrier line count as active?**
   No. Payment, provisioning, installation and activation are separate states
   (`AGENTS.md`), and the customer whose phone is not yet attached needs the
   installation route, not a green tick.

3. **Can an invitation link be read by the wrong account?** It can be *read* --
   the recipient has to be able to see whose it is -- but it must say so, and it
   must not leak the address to a caller who does not already hold it.

The service reads run against PostgreSQL in
`test_consumer_services_postgres.py`; this file is the HTTP contract, including
the authorization boundary on every route.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.auth.models import Locale, Organization, OrganizationType, User, UserStatus
from app.catalog.market import DeviceEligibilityRule
from app.catalog.models import LegalEntity, Product, ProductKind
from app.connectivity.models import (
    ActivationState,
    CarrierLine,
    Entitlement,
    EsimInstallation,
    InstallationState,
)
from app.identity.models import AccountIdentifier, IdentifierKind
from app.orders.models import Order, OrderItem, PaymentState, ProvisioningState
from app.organizations.models import (
    InvitationStatus,
    MembershipStatus,
    OrganizationInvitation,
    OrganizationMember,
    OrganizationRole,
)

NOW = datetime(2026, 7, 13, tzinfo=timezone.utc)


@pytest.fixture
def client(api: FastAPI) -> TestClient:
    return TestClient(api)


def _user(session: Session, phone: str = "+2348012345670") -> User:
    user = User(
        phone_number=phone,
        locale=Locale.EN,
        status=UserStatus.ACTIVE,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    session.expunge(user)
    return user


def _token(api: FastAPI, user: User) -> str:
    """Mint a real access token through the app's own token service."""
    with api.state.session_factory() as session:
        pair = api.state.otp_service.tokens.issue(
            session, session.get(User, user.id), api.state.clock()
        )
        session.commit()
    return str(pair.access_token)


def _auth(api: FastAPI, user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(api, user)}"}


def _organization(session: Session, name: str) -> Organization:
    organization = Organization(
        org_type=OrganizationType.ENTERPRISE,
        name=name,
        primary_contact_name="Contact",
        email=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:8]}@example.test",
        password_hash="unused",
        phone_number="+2348000000000",
        locale=Locale.EN,
    )
    session.add(organization)
    session.commit()
    session.refresh(organization)
    session.expunge(organization)
    return organization


def _seller(session: Session) -> LegalEntity:
    entity = LegalEntity(code="TEST", name="Test Seller Ltd", country="NG")
    session.add(entity)
    session.commit()
    session.refresh(entity)
    session.expunge(entity)
    return entity


def _product(
    session: Session,
    kind: ProductKind,
    name: str,
    sku: str,
    *,
    requires_esim: bool = True,
) -> Product:
    product = Product(sku=sku, name=name, kind=kind)
    session.add(product)
    session.commit()
    session.refresh(product)
    session.add(
        DeviceEligibilityRule(
            product_id=product.id,
            requires_esim=requires_esim,
            requires_unlocked_device=requires_esim,
        )
    )
    session.commit()
    session.refresh(product)
    session.expunge(product)
    return product


def _order(
    session: Session,
    seller: LegalEntity,
    *,
    reference: str,
    payer_user_id: UUID | None = None,
    payer_organization_id: UUID | None = None,
    payment_state: PaymentState = PaymentState.PAID,
) -> Order:
    order = Order(
        reference=reference,
        seller_legal_entity_id=seller.id,
        payer_user_id=payer_user_id,
        payer_organization_id=payer_organization_id,
        currency="NGN",
        total_amount=Decimal("10000.00"),
        payment_state=payment_state,
        placed_at=NOW,
    )
    session.add(order)
    session.commit()
    session.refresh(order)
    session.expunge(order)
    return order


def _item(
    session: Session,
    order: Order,
    product: Product,
    recipient: User | None,
    *,
    provisioning_state: ProvisioningState = ProvisioningState.PROVISIONED,
) -> OrderItem:
    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        recipient_user_id=recipient.id if recipient else None,
        unit_currency="NGN",
        unit_amount=Decimal("10000.00"),
        provisioning_state=provisioning_state,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    session.expunge(item)
    return item


def _entitlement(
    session: Session,
    item: OrderItem,
    holder: User | None,
    *,
    expires_at: datetime | None = None,
) -> Entitlement:
    entitlement = Entitlement(
        order_item_id=item.id,
        holder_user_id=holder.id if holder else None,
        product_id=item.product_id,
        data_bytes_total=5_368_709_120,
        voice_seconds_total=0,
        granted_at=NOW,
        expires_at=expires_at,
    )
    session.add(entitlement)
    session.commit()
    session.refresh(entitlement)
    session.expunge(entitlement)
    return entitlement


# --- authorization ---------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/v1/me/session"),
        ("get", "/v1/me/services"),
        ("post", "/v1/invitations/preview"),
    ],
)
def test_every_consumer_route_requires_a_bearer_token(
    client: TestClient, method: str, path: str
) -> None:
    kwargs = {"json": {"token": "x" * 32}} if method == "post" else {}
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 401


# --- service state ---------------------------------------------------------


def test_an_account_with_nothing_reports_no_service_rather_than_an_empty_error(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        user = _user(session)

    response = client.get("/v1/me/services", headers=_auth(api, user))

    assert response.status_code == 200
    body = response.json()
    assert body["service_state"] == "none"
    assert body["services"] == []


def test_an_internet_only_grant_is_active_with_no_esim_and_no_carrier_line(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    """The calling amendment's requirement, expressed as an assertion.

    There is no `esim_installations` row and no `carrier_lines` row, because
    internet calling creates neither. If this returned `pending`, the app would
    have to invent an installation step for a product that has no profile.
    """
    with session_factory() as session:
        user = _user(session)
        seller = _seller(session)
        product = _product(
            session,
            ProductKind.VOICE,
            "Calling 100",
            "CALL-100",
            requires_esim=False,
        )
        order = _order(session, seller, reference="ORD-INT-1", payer_user_id=user.id)
        item = _item(session, order, product, user)
        _entitlement(session, item, user)

    response = client.get("/v1/me/services", headers=_auth(api, user))

    body = response.json()
    assert body["service_state"] == "active"
    (service,) = body["services"]
    assert service["delivery"] == "internet"
    assert service["requires_installation"] is False
    assert service["ready_to_use"] is True
    assert service["installation_state"] is None
    assert service["activation_state"] is None


def test_a_provisioned_but_uninstalled_carrier_line_is_pending_not_active(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        user = _user(session)
        seller = _seller(session)
        product = _product(session, ProductKind.BUNDLE, "Travel 5GB", "TRV-5")
        order = _order(session, seller, reference="ORD-ESIM-1", payer_user_id=user.id)
        item = _item(session, order, product, user)
        entitlement = _entitlement(session, item, user)
        session.add(
            EsimInstallation(
                entitlement_id=entitlement.id,
                installation_state=InstallationState.NOT_INSTALLED,
            )
        )
        session.add(
            CarrierLine(
                entitlement_id=entitlement.id,
                carrier="telnyx",
                carrier_line_reference="line-1",
                activation_state=ActivationState.PENDING,
                created_at=NOW,
            )
        )
        session.commit()

    body = client.get("/v1/me/services", headers=_auth(api, user)).json()

    assert body["service_state"] == "pending"
    (service,) = body["services"]
    assert service["delivery"] == "carrier_esim"
    assert service["requires_installation"] is True
    assert service["ready_to_use"] is False
    assert service["installation_state"] == "not_installed"
    assert service["activation_state"] == "pending"


def test_an_installed_and_activated_line_is_the_only_carrier_case_that_is_ready(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        user = _user(session)
        seller = _seller(session)
        product = _product(session, ProductKind.BUNDLE, "Travel 5GB", "TRV-5")
        order = _order(session, seller, reference="ORD-ESIM-2", payer_user_id=user.id)
        item = _item(session, order, product, user)
        entitlement = _entitlement(session, item, user)
        session.add(
            EsimInstallation(
                entitlement_id=entitlement.id,
                installation_state=InstallationState.INSTALLED,
                installed_at=NOW,
            )
        )
        session.add(
            CarrierLine(
                entitlement_id=entitlement.id,
                carrier="telnyx",
                carrier_line_reference="line-2",
                activation_state=ActivationState.ACTIVE,
                created_at=NOW,
            )
        )
        session.commit()

    body = client.get("/v1/me/services", headers=_auth(api, user)).json()

    assert body["service_state"] == "active"
    assert body["services"][0]["ready_to_use"] is True


def test_a_failed_item_does_not_leave_the_account_waiting_for_it(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    """AC-37.5: a failure needs a route out, not a permanent "coming soon".

    `pending` tells Home to show progress. A provisioning failure is not
    progress, so the account state falls back to `none` -- the customer is
    offered a way to buy or retry -- while the failed item stays in the list
    with its own state so the failure is still visible and actionable.
    """
    with session_factory() as session:
        user = _user(session)
        seller = _seller(session)
        product = _product(session, ProductKind.DATA, "Travel 1GB", "TRV-1")
        order = _order(session, seller, reference="ORD-FAIL-1", payer_user_id=user.id)
        _item(
            session,
            order,
            product,
            user,
            provisioning_state=ProvisioningState.FAILED,
        )

    body = client.get("/v1/me/services", headers=_auth(api, user)).json()

    assert body["service_state"] == "none"
    (service,) = body["services"]
    assert service["provisioning_state"] == "failed"


def test_an_expired_entitlement_is_not_reported_as_usable(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        user = _user(session)
        seller = _seller(session)
        product = _product(
            session,
            ProductKind.VOICE,
            "Calling 100",
            "CALL-100",
            requires_esim=False,
        )
        order = _order(session, seller, reference="ORD-EXP-1", payer_user_id=user.id)
        item = _item(session, order, product, user)
        _entitlement(session, item, user, expires_at=NOW - timedelta(days=1))

    body = client.get("/v1/me/services", headers=_auth(api, user)).json()

    assert body["service_state"] == "none"
    assert body["services"][0]["expired"] is True
    assert body["services"][0]["ready_to_use"] is False


def test_personal_and_organization_services_stay_distinguishable(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    """AC-37: "Keep personal and organization services clearly identified."

    Same account, two lines, two payers. The app cannot label them without the
    API saying which is which, and a work line silently presented as personal is
    a line the customer may cancel without realizing whose it is.
    """
    with session_factory() as session:
        user = _user(session)
        seller = _seller(session)
        organization = _organization(session, "Acme Logistics")

        personal_product = _product(session, ProductKind.DATA, "Personal 1GB", "P-1")
        work_product = _product(session, ProductKind.DATA, "Work 5GB", "W-5")
        personal_order = _order(
            session, seller, reference="ORD-P-1", payer_user_id=user.id
        )
        work_order = _order(
            session,
            seller,
            reference="ORD-W-1",
            payer_organization_id=organization.id,
        )
        personal_item = _item(session, personal_order, personal_product, user)
        work_item = _item(session, work_order, work_product, user)
        _entitlement(session, personal_item, user)
        _entitlement(session, work_item, user)

    body = client.get("/v1/me/services", headers=_auth(api, user)).json()

    owners = {
        service["order_reference"]: (
            service["owner"],
            service["organization_name"],
        )
        for service in body["services"]
    }
    assert owners["ORD-P-1"] == ("personal", None)
    assert owners["ORD-W-1"] == ("organization", "Acme Logistics")


def test_one_account_never_sees_another_accounts_services(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        owner = _user(session, phone="+2348012345671")
        stranger = _user(session, phone="+2348012345672")
        seller = _seller(session)
        product = _product(session, ProductKind.DATA, "Travel 1GB", "TRV-1")
        order = _order(session, seller, reference="ORD-ISO-1", payer_user_id=owner.id)
        item = _item(session, order, product, owner)
        _entitlement(session, item, owner)

    body = client.get("/v1/me/services", headers=_auth(api, stranger)).json()

    assert body["service_state"] == "none"
    assert body["services"] == []


# --- session ---------------------------------------------------------------


def test_the_session_read_returns_verified_identifiers_only(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    """An unverified claim is not an identity.

    Showing one in the account header would tell the customer they can sign in
    with an address they have never proved, and -- worse -- suggest an
    invitation addressed to it would be theirs to accept.
    """
    with session_factory() as session:
        user = _user(session)
        session.add(
            AccountIdentifier(
                user_id=user.id,
                kind=IdentifierKind.EMAIL,
                value="verified@example.test",
                verified_at=NOW,
            )
        )
        session.add(
            AccountIdentifier(
                user_id=user.id,
                kind=IdentifierKind.EMAIL,
                value="unproven@example.test",
            )
        )
        session.commit()

    body = client.get("/v1/me/session", headers=_auth(api, user)).json()

    assert body["verified_emails"] == ["verified@example.test"]
    assert body["service_state"] == "none"
    assert body["organizations"] == []


def test_the_session_read_lists_active_memberships_and_pending_invitations(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        user = _user(session)
        session.add(
            AccountIdentifier(
                user_id=user.id,
                kind=IdentifierKind.EMAIL,
                value="member@acme.test",
                verified_at=NOW,
            )
        )
        joined = _organization(session, "Acme Logistics")
        inviting = _organization(session, "Beta Freight")
        session.add(
            OrganizationMember(
                organization_id=joined.id,
                user_id=user.id,
                role=OrganizationRole.MEMBER,
                status=MembershipStatus.ACTIVE,
            )
        )
        session.add(
            OrganizationInvitation(
                organization_id=inviting.id,
                invited_kind=IdentifierKind.EMAIL,
                invited_value="member@acme.test",
                role=OrganizationRole.MEMBER,
                status=InvitationStatus.PENDING,
                token_hash="a" * 64,
                expires_at=NOW + timedelta(days=7),
            )
        )
        session.commit()

    body = client.get("/v1/me/session", headers=_auth(api, user)).json()

    assert body["organizations"] == [
        {
            "organization_id": str(joined.id),
            "name": "Acme Logistics",
            "role": "member",
        }
    ]
    assert body["pending_invitations"] == 1


# --- invitation preview ----------------------------------------------------


def test_a_preview_tells_the_wrong_account_that_the_link_is_not_theirs(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    """AC-37.4, before anything is bound.

    The caller holds a valid token and a valid session, and the two do not
    belong together. Accepting would create a membership on the wrong account;
    the preview says so first, and never reveals the address it was sent to.
    """
    with session_factory() as session:
        stranger = _user(session, phone="+2348012345673")
        organization = _organization(session, "Acme Logistics")
        session.add(
            OrganizationInvitation(
                organization_id=organization.id,
                invited_kind=IdentifierKind.EMAIL,
                invited_value="intended@acme.test",
                role=OrganizationRole.MEMBER,
                status=InvitationStatus.PENDING,
                token_hash=api.state.invitation_service._hash("token-" + "z" * 26),
                expires_at=NOW + timedelta(days=7),
            )
        )
        session.commit()

    response = client.post(
        "/v1/invitations/preview",
        json={"token": "token-" + "z" * 26},
        headers=_auth(api, stranger),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "pending"
    assert body["recipient_matches"] is False
    assert body["organization_name"] == "Acme Logistics"
    assert "intended@acme.test" not in response.text
    assert body["invited_value_masked"] == "i•••d@acme.test"


def test_a_preview_confirms_the_link_belongs_to_the_signed_in_account(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        user = _user(session, phone="+2348012345674")
        session.add(
            AccountIdentifier(
                user_id=user.id,
                kind=IdentifierKind.EMAIL,
                value="intended@acme.test",
                verified_at=NOW,
            )
        )
        organization = _organization(session, "Acme Logistics")
        session.add(
            OrganizationInvitation(
                organization_id=organization.id,
                invited_kind=IdentifierKind.EMAIL,
                invited_value="intended@acme.test",
                role=OrganizationRole.MEMBER,
                status=InvitationStatus.PENDING,
                token_hash=api.state.invitation_service._hash("token-" + "y" * 26),
                expires_at=NOW + timedelta(days=7),
            )
        )
        session.commit()

    body = client.post(
        "/v1/invitations/preview",
        json={"token": "token-" + "y" * 26},
        headers=_auth(api, user),
    ).json()

    assert body["recipient_matches"] is True
    assert body["already_a_member"] is False


def test_an_expired_link_previews_as_expired_rather_than_failing_the_request(
    api: FastAPI, client: TestClient, session_factory: type[Session], clock
) -> None:
    """AC-37.3: an expired code has to *behave correctly*, not merely fail.

    A 4xx here would leave the app with an error toast and no way to explain
    which link expired or who to ask for a new one.
    """
    with session_factory() as session:
        user = _user(session, phone="+2348012345675")
        organization = _organization(session, "Acme Logistics")
        session.add(
            OrganizationInvitation(
                organization_id=organization.id,
                invited_kind=IdentifierKind.EMAIL,
                invited_value="intended@acme.test",
                role=OrganizationRole.MEMBER,
                status=InvitationStatus.PENDING,
                token_hash=api.state.invitation_service._hash("token-" + "x" * 26),
                expires_at=NOW - timedelta(seconds=1),
            )
        )
        session.commit()

    response = client.post(
        "/v1/invitations/preview",
        json={"token": "token-" + "x" * 26},
        headers=_auth(api, user),
    )

    assert response.status_code == 200
    assert response.json()["state"] == "expired"


def test_an_already_accepted_link_previews_as_accepted(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        accepter = _user(session, phone="+2348012345676")
        organization = _organization(session, "Acme Logistics")
        session.add(
            OrganizationInvitation(
                organization_id=organization.id,
                invited_kind=IdentifierKind.EMAIL,
                invited_value="intended@acme.test",
                role=OrganizationRole.MEMBER,
                status=InvitationStatus.ACCEPTED,
                accepted_at=NOW,
                accepted_by_user_id=accepter.id,
                token_hash=api.state.invitation_service._hash("token-" + "w" * 26),
                expires_at=NOW + timedelta(days=7),
            )
        )
        session.commit()

    body = client.post(
        "/v1/invitations/preview",
        json={"token": "token-" + "w" * 26},
        headers=_auth(api, accepter),
    ).json()

    assert body["state"] == "accepted"


def test_an_unknown_token_is_rejected_without_saying_why(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    with session_factory() as session:
        user = _user(session, phone="+2348012345677")

    response = client.post(
        "/v1/invitations/preview",
        json={"token": "token-" + "v" * 26},
        headers=_auth(api, user),
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invitation_invalid"


def test_a_replayed_token_cannot_be_accepted_twice(
    api: FastAPI, client: TestClient, session_factory: type[Session]
) -> None:
    """AC-37.3's "already used" case, at the endpoint the app actually calls.

    The second POST is the same request the first one was -- a cold-launched
    deep link that the app retried, or a customer tapping the WhatsApp message
    again. It must not produce a second membership and must not 500.
    """
    token = "token-" + "u" * 26
    with session_factory() as session:
        user = _user(session, phone="+2348012345678")
        session.add(
            AccountIdentifier(
                user_id=user.id,
                kind=IdentifierKind.EMAIL,
                value="intended@acme.test",
                verified_at=NOW,
            )
        )
        organization = _organization(session, "Acme Logistics")
        session.add(
            OrganizationInvitation(
                organization_id=organization.id,
                invited_kind=IdentifierKind.EMAIL,
                invited_value="intended@acme.test",
                role=OrganizationRole.MEMBER,
                status=InvitationStatus.PENDING,
                token_hash=api.state.invitation_service._hash(token),
                expires_at=NOW + timedelta(days=7),
            )
        )
        session.commit()

    headers = _auth(api, user)
    first = client.post(
        "/v1/invitations/accept", json={"token": token}, headers=headers
    )
    second = client.post(
        "/v1/invitations/accept", json={"token": token}, headers=headers
    )

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["error"] == "invitation_invalid"

    preview = client.post(
        "/v1/invitations/preview", json={"token": token}, headers=headers
    ).json()
    assert preview["state"] == "accepted"
    assert preview["already_a_member"] is True


def test_masking_never_returns_the_address_it_was_given() -> None:
    """A unit check on the masking rule itself, including the short-local case.

    `ab@x.test` has no interior character to hide. Returning `a•••b@x.test`
    would be the whole local part with decoration; the rule collapses it to a
    single leading character instead.
    """
    from app.consumer.service import mask_identifier

    assert mask_identifier(IdentifierKind.EMAIL, "intended@acme.test") == (
        "i•••d@acme.test"
    )
    assert mask_identifier(IdentifierKind.EMAIL, "ab@x.test") == "a•••@x.test"
    assert mask_identifier(IdentifierKind.PHONE, "+2348012345678") == (
        "••••••••••••78"
    )
