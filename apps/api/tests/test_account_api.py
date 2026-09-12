"""US-38 chunk 21 — the account area over HTTP.

The service tests prove the rules; these prove the API does not leak around
them. Three properties, and all three are about what the endpoints refuse:

**One customer's id is never an oracle.** Every not-yours case answers 404 with
the same body as a never-existed case. A 403 would confirm the id is real, which
is all somebody needs to enumerate other customers' sessions, orders and tickets.

**A refusal explains itself.** The deletion preflight returns codes, so the app
can say "your organization still has three members" instead of "you cannot do
that" — but it returns *codes*, not the internal detail, because that detail can
name another member's line.

**A receipt is what was recorded.** Amounts cross as strings, so the number on
the screen is the number that was charged.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from app.account.models import SessionPlatform
from app.auth.models import (
    Locale,
    Organization,
    OrganizationType,
    RefreshToken,
    User,
    UserStatus,
)
from app.catalog.models import LegalEntity, Product, ProductKind
from app.orders.models import Order, OrderItem, PaymentState
from app.organizations.models import (
    MembershipStatus,
    OrganizationMember,
    OrganizationRole,
)

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="the account tables carry PostgreSQL-only partial indexes",
)


@pytest.fixture
def session_factory():
    """The app on real PostgreSQL, in a schema of its own."""
    url = os.environ["TEST_DATABASE_URL"]
    schema = f"account_{uuid4().hex}"
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


def _user(api: FastAPI, suffix: str = "0001", locale: Locale = Locale.EN) -> User:
    with api.state.session_factory() as session:
        user = User(
            phone_number=f"+234801900{suffix}",
            email=f"account-{suffix}@example.test",
            first_name="Holder",
            last_name="Person",
            locale=locale,
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


def _order(api: FastAPI, user: User, amount: str = "5000.00") -> Order:
    with api.state.session_factory() as session:
        entity = LegalEntity(
            code=f"E{uuid4().hex[:6]}", name="Seller", country="NG"
        )
        product = Product(
            sku=f"sku-{uuid4().hex[:8]}", name="Nigeria 5GB", kind=ProductKind.DATA
        )
        session.add(entity)
        session.add(product)
        session.flush()
        order = Order(
            reference=f"ORD-{uuid4().hex[:8].upper()}",
            seller_legal_entity_id=entity.id,
            payer_user_id=user.id,
            currency="NGN",
            total_amount=Decimal(amount),
            payment_state=PaymentState.PAID,
            placed_at=NOW,
        )
        session.add(order)
        session.flush()
        session.add(
            OrderItem(
                order_id=order.id,
                product_id=product.id,
                recipient_user_id=user.id,
                quantity=1,
                unit_currency="NGN",
                unit_amount=Decimal(amount),
            )
        )
        session.commit()
        session.refresh(order)
        session.expunge(order)
    return order


def _session_row(api: FastAPI, user: User, label: str = "Pixel 7"):
    with api.state.session_factory() as session:
        token = RefreshToken(
            user_id=user.id,
            token_hash=uuid4().hex,
            expires_at=NOW + timedelta(days=30),
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(token)
        session.flush()
        record = api.state.account_service.record_session(
            session,
            session.get(User, user.id),
            token,
            platform=SessionPlatform.ANDROID,
            device_label=label,
            city="Lagos",
            country="NG",
        )
        session.commit()
        session.refresh(record)
        session.expunge(record)
    return record


class TestSessions:
    def test_the_device_list_describes_each_signed_in_device(self, api, client):
        user = _user(api)
        _session_row(api, user, "Pixel 7")

        response = client.get("/v1/me/sessions", headers=_auth(api, user))

        assert response.status_code == 200
        sessions = response.json()["sessions"]
        assert len(sessions) == 1
        assert sessions[0]["device_label"] == "Pixel 7"
        assert sessions[0]["last_seen_country"] == "NG"
        assert sessions[0]["revoked_at"] is None

    def test_revoking_a_device_returns_no_content_and_kills_the_token(
        self, api, client
    ):
        user = _user(api)
        record = _session_row(api, user, "Old phone")

        response = client.delete(
            f"/v1/me/sessions/{record.id}", headers=_auth(api, user)
        )

        assert response.status_code == 204
        with api.state.session_factory() as session:
            token = session.get(RefreshToken, record.refresh_token_id)
            assert token.revoked_at is not None

    def test_another_customers_session_is_404_not_403(self, api, client):
        """A 403 would confirm the id is real."""
        owner = _user(api, "0001")
        stranger = _user(api, "0002")
        record = _session_row(api, owner)

        response = client.delete(
            f"/v1/me/sessions/{record.id}", headers=_auth(api, stranger)
        )

        assert response.status_code == 404
        assert response.json()["error"] == "session_not_found"

    def test_a_session_id_that_never_existed_answers_the_same_way(
        self, api, client
    ):
        user = _user(api)
        response = client.delete(
            f"/v1/me/sessions/{uuid4()}", headers=_auth(api, user)
        )
        assert response.status_code == 404
        assert response.json()["error"] == "session_not_found"

    def test_signing_out_everywhere_reports_how_many_it_signed_out(
        self, api, client
    ):
        user = _user(api)
        _session_row(api, user, "Phone one")
        _session_row(api, user, "Phone two")

        response = client.post(
            "/v1/me/sessions/revoke-all",
            json={},
            headers=_auth(api, user),
        )

        assert response.status_code == 200
        assert response.json()["revoked"] == 2

    def test_the_named_device_is_spared(self, api, client):
        user = _user(api)
        keep = _session_row(api, user, "This phone")
        _session_row(api, user, "Lost phone")

        response = client.post(
            "/v1/me/sessions/revoke-all",
            json={"keep_session_id": str(keep.id)},
            headers=_auth(api, user),
        )

        assert response.json()["revoked"] == 1
        listed = client.get("/v1/me/sessions", headers=_auth(api, user)).json()
        spared = [s for s in listed["sessions"] if s["revoked_at"] is None]
        assert [s["device_label"] for s in spared] == ["This phone"]

    def test_naming_another_customers_session_spares_nothing(self, api, client):
        """There is no id a client can send that reaches outside its account."""
        owner = _user(api, "0001")
        stranger = _user(api, "0002")
        strangers_device = _session_row(api, stranger, "Stranger phone")
        _session_row(api, owner, "My phone")

        response = client.post(
            "/v1/me/sessions/revoke-all",
            json={"keep_session_id": str(strangers_device.id)},
            headers=_auth(api, owner),
        )

        assert response.json()["revoked"] == 1
        with api.state.session_factory() as session:
            from app.account.models import AccountSession

            theirs = session.get(AccountSession, strangers_device.id)
            assert theirs.revoked_at is None


class TestReceipts:
    def test_a_receipt_carries_its_amounts_as_strings(self, api, client):
        """A price that travels as a float can come back a hundredth different."""
        user = _user(api)
        order = _order(api, user, "5000.00")

        response = client.get(
            f"/v1/me/receipts/{order.id}", headers=_auth(api, user)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total_amount"] == "5000.000000"
        assert body["currency"] == "NGN"
        assert body["lines"][0]["description"] == "Nigeria 5GB"

    def test_another_customers_receipt_is_404(self, api, client):
        owner = _user(api, "0001")
        stranger = _user(api, "0002")
        order = _order(api, owner)

        response = client.get(
            f"/v1/me/receipts/{order.id}", headers=_auth(api, stranger)
        )

        assert response.status_code == 404
        assert response.json()["error"] == "receipt_not_found"

    def test_the_list_holds_only_this_customers_orders(self, api, client):
        owner = _user(api, "0001")
        stranger = _user(api, "0002")
        _order(api, owner)
        _order(api, stranger)

        response = client.get("/v1/me/receipts", headers=_auth(api, owner))

        assert response.status_code == 200
        assert len(response.json()["receipts"]) == 1


class TestSupport:
    def test_opening_a_request_returns_a_reference_the_customer_can_quote(
        self, api, client
    ):
        user = _user(api)
        order = _order(api, user)

        response = client.post(
            "/v1/me/support-requests",
            json={
                "category": "billing",
                "subject": "Charged twice",
                "body": "I think I paid for this twice.",
                "order_id": str(order.id),
            },
            headers=_auth(api, user),
        )

        assert response.status_code == 201
        body = response.json()
        assert body["reference"].startswith("S-")
        assert body["order_id"] == str(order.id)
        assert order.reference in body["subject_summary"]

    def test_a_request_cannot_name_another_customers_order(self, api, client):
        owner = _user(api, "0001")
        stranger = _user(api, "0002")
        order = _order(api, owner)

        response = client.post(
            "/v1/me/support-requests",
            json={
                "category": "billing",
                "subject": "About this",
                "body": "...",
                "order_id": str(order.id),
            },
            headers=_auth(api, stranger),
        )

        assert response.status_code == 404
        assert response.json()["error"] == "order_not_found"

    def test_an_empty_subject_is_refused_before_it_reaches_the_service(
        self, api, client
    ):
        user = _user(api)
        response = client.post(
            "/v1/me/support-requests",
            json={"category": "other", "subject": "", "body": "..."},
            headers=_auth(api, user),
        )
        assert response.status_code == 422

    def test_the_list_is_scoped_to_the_caller(self, api, client):
        owner = _user(api, "0001")
        stranger = _user(api, "0002")
        client.post(
            "/v1/me/support-requests",
            json={"category": "other", "subject": "Mine", "body": "..."},
            headers=_auth(api, owner),
        )

        response = client.get(
            "/v1/me/support-requests", headers=_auth(api, stranger)
        )

        assert response.status_code == 200
        assert response.json()["requests"] == []


class TestNotificationPreferences:
    def test_nothing_is_stored_until_somebody_decides(self, api, client):
        user = _user(api)
        response = client.get(
            "/v1/me/notification-preferences", headers=_auth(api, user)
        )
        assert response.status_code == 200
        assert response.json()["preferences"] == []

    def test_turning_a_category_off_is_stored_and_read_back(self, api, client):
        user = _user(api)
        headers = _auth(api, user)

        put = client.put(
            "/v1/me/notification-preferences",
            json={
                "category": "low_balance",
                "channel": "push",
                "enabled": False,
            },
            headers=headers,
        )
        assert put.status_code == 200
        assert put.json()["enabled"] is False

        listed = client.get("/v1/me/notification-preferences", headers=headers)
        assert listed.json()["preferences"] == [
            {"category": "low_balance", "channel": "push", "enabled": False}
        ]

    def test_a_retired_category_is_not_accepted(self, api, client):
        """Safety alerts stay retired. A preference for one is a feature."""
        user = _user(api)
        response = client.put(
            "/v1/me/notification-preferences",
            json={"category": "sos", "channel": "push", "enabled": True},
            headers=_auth(api, user),
        )
        assert response.status_code == 422


class TestDeletionPreflight:
    def test_an_ordinary_account_is_told_it_may_delete(self, api, client):
        user = _user(api)
        response = client.get(
            "/v1/me/account/deletion-preflight", headers=_auth(api, user)
        )
        assert response.status_code == 200
        assert response.json() == {"may_delete": True, "blockers": []}

    def test_an_owner_with_colleagues_is_told_why_not(self, api, client):
        owner = _user(api, "0001")
        colleague = _user(api, "0002")
        with api.state.session_factory() as session:
            organization = Organization(
                name=f"Org {uuid4().hex[:6]}",
                primary_contact_name="Contact",
                phone_number=f"+23490{uuid4().int % 10**8:08d}",
                email=f"org-{uuid4().hex[:8]}@example.test",
                password_hash="x",
                org_type=OrganizationType.ENTERPRISE,
            )
            session.add(organization)
            session.flush()
            for member, role in (
                (owner, OrganizationRole.OWNER),
                (colleague, OrganizationRole.MEMBER),
            ):
                session.add(
                    OrganizationMember(
                        organization_id=organization.id,
                        user_id=member.id,
                        role=role,
                        status=MembershipStatus.ACTIVE,
                    )
                )
            session.commit()

        response = client.get(
            "/v1/me/account/deletion-preflight", headers=_auth(api, owner)
        )

        body = response.json()
        assert body["may_delete"] is False
        assert body["blockers"][0]["code"] == "organization_has_other_members"

    def test_the_internal_detail_never_reaches_the_customer(self, api, client):
        """It can name another member's line. The code is what the app shows."""
        user = _user(api)
        response = client.get(
            "/v1/me/account/deletion-preflight", headers=_auth(api, user)
        )
        assert "detail" not in str(response.json())


class TestExport:
    def test_requesting_an_export_is_accepted_and_idempotent(self, api, client):
        user = _user(api)
        headers = _auth(api, user)

        first = client.post("/v1/me/account/export", headers=headers)
        second = client.post("/v1/me/account/export", headers=headers)

        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["export_id"] == second.json()["export_id"]

    def test_an_export_belongs_to_the_caller(self, api, client):
        first = _user(api, "0001")
        second = _user(api, "0002")

        one = client.post("/v1/me/account/export", headers=_auth(api, first))
        two = client.post("/v1/me/account/export", headers=_auth(api, second))

        assert one.json()["export_id"] != two.json()["export_id"]


class TestEveryAccountEndpointNeedsASession:
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/v1/me/sessions"),
            ("get", "/v1/me/receipts"),
            ("get", "/v1/me/support-requests"),
            ("get", "/v1/me/notification-preferences"),
            ("get", "/v1/me/account/deletion-preflight"),
            ("post", "/v1/me/account/export"),
        ],
    )
    def test_anonymous_requests_are_refused(self, client, method, path):
        response = getattr(client, method)(path)
        assert response.status_code in (401, 403)
