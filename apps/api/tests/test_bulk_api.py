"""US-40 chunk 23 — bulk provisioning over HTTP.

The service suite proves the rules; this proves the routes apply them, and adds
the two properties that only exist at the HTTP boundary:

**Buying for fifty people is buying.** Every administrator endpoint takes
`order:place` or `order:read`, so a billing or member session reaches none of
it — chunk 07's matrix doing the work rather than a check per handler.

**Redeeming is not an administrator action.** The person claiming a work line is
an employee with a phone, not a member of the tenant that bought it. That
endpoint deliberately takes an ordinary session and no organization permission,
and the test below proves a complete outsider can still claim the line bought
for them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.auth.models import Locale, Organization, OrganizationType, Platform, User
from app.bulk.models import ActivationRequest, ActivationRequestState, BulkJobItem
from app.catalog.market import PublicationStatus, SalesMarket
from app.catalog.models import (
    LegalEntity,
    Product,
    ProductAllowance,
    ProductKind,
    ProductPrice,
)
from app.ledger.models import AccountKind, Direction, OwnerKind
from app.ledger.service import LedgerService, Posting
from app.organizations.models import OrganizationRole
from app.organizations.service import MembershipService
from app.people.models import OrganizationPerson, PersonStatus

#: Before the shared test clock (2026-07-13), so the market is published and
#: the price window is open by the time a request is served. A fixture dated
#: after the clock produces `price_unavailable`, which reads like a missing row
#: rather than a window that has not opened.
NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)


@pytest.fixture
def client(api):
    return TestClient(api, raise_server_exceptions=True)


def _user(session: Session, label: str) -> UUID:
    user = User(
        phone_number=f"+23485{abs(hash(label)) % 10**8:08d}",
        first_name=label,
        platform=Platform.ANDROID,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user.id


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
    session.commit()
    session.refresh(organization)
    return organization


def _auth(api, user_id: UUID) -> dict[str, str]:
    with api.state.session_factory() as session:
        pair = api.state.otp_service.tokens.issue(
            session, session.get(User, user_id), api.state.clock()
        )
        session.commit()
    return {"Authorization": f"Bearer {pair.access_token}"}


@pytest.fixture
def world(api, session_factory, clock):
    """One organization with every role, a market, a priced product, people."""
    memberships = MembershipService(clock=clock)
    with session_factory() as session:
        acme = _organization(session, "Acme")
        other = _organization(session, "Other")
        roles = {
            role.value: _user(session, f"acme-{role.value}")
            for role in OrganizationRole
        }
        outsider = _user(session, "outsider")
        for role in OrganizationRole:
            memberships.seed_member(
                session, acme, session.get(User, roles[role.value]), role
            )
        memberships.seed_member(
            session,
            other,
            session.get(User, _user(session, "other-owner")),
            OrganizationRole.OWNER,
        )

        entity = LegalEntity(code=f"E{uuid4().hex[:6]}", name="Seller", country="NG")
        session.add(entity)
        session.flush()
        market = SalesMarket(
            country="NG",
            currency="NGN",
            status=PublicationStatus.PUBLISHED,
            legal_entity_id=entity.id,
            evidence_reference="test fixture",
            verified_at=NOW,
            published_at=NOW,
            created_at=NOW,
        )
        product = Product(
            sku=f"sku-{uuid4().hex[:8]}", name="Work data", kind=ProductKind.VOICE
        )
        session.add(market)
        session.add(product)
        session.flush()
        session.add(
            ProductAllowance(
                product_id=product.id,
                data_bytes=0,
                voice_seconds=3600,
                validity_days=30,
            )
        )
        session.add(
            ProductPrice(
                product_id=product.id,
                legal_entity_id=entity.id,
                currency="NGN",
                amount=Decimal("1000.00"),
                version=1,
                effective_from=NOW,
            )
        )
        people = [
            OrganizationPerson(
                organization_id=acme.id,
                full_name=f"Person {index}",
                email=f"p{index}-{uuid4().hex[:6]}@example.test",
                status=PersonStatus.ACTIVE,
                created_at=NOW,
                updated_at=NOW,
            )
            for index in range(3)
        ]
        for person in people:
            session.add(person)
        session.flush()

        ledger = LedgerService(clock=clock)
        credit = ledger.account(
            session,
            "NGN",
            AccountKind.SERVICE_CREDIT,
            OwnerKind.ORGANIZATION,
            owner_organization_id=acme.id,
        )
        clearing = ledger.account(session, "NGN", AccountKind.SETTLEMENT_CLEARING)
        ledger.post(
            session,
            f"funding:{uuid4()}",
            [
                Posting(clearing, Direction.DEBIT, Decimal("10000.00")),
                Posting(credit, Direction.CREDIT, Decimal("10000.00")),
            ],
        )
        session.commit()
        return {
            "acme": acme.id,
            "other": other.id,
            "outsider": outsider,
            "product": product.id,
            "people": [person.id for person in people],
            **roles,
        }


def _plan(client, api, world, role="owner", key="bulk-http-1"):
    return client.post(
        f"/v1/organizations/{world['acme']}/bulk-jobs",
        headers=_auth(api, world[role]),
        json={
            "idempotency_key": key,
            "product_id": str(world["product"]),
            "country": "NG",
            "currency": "NGN",
            "person_ids": [str(person_id) for person_id in world["people"]],
        },
    )


class TestOnlyBuyersMayBuy:
    @pytest.mark.parametrize("role", ["billing", "member"])
    def test_a_billing_or_member_session_cannot_plan_a_bulk_order(
        self, client, api, world, role
    ):
        assert _plan(client, api, world, role=role).status_code == 403

    @pytest.mark.parametrize("role", ["billing", "member"])
    def test_a_member_session_cannot_read_bulk_orders(
        self, client, api, world, role
    ):
        response = client.get(
            f"/v1/organizations/{world['acme']}/bulk-jobs",
            headers=_auth(api, world[role]),
        )
        # Billing may read orders; a plain member may not.
        expected = 200 if role == "billing" else 403
        assert response.status_code == expected

    def test_an_administrator_may_plan(self, client, api, world):
        response = _plan(client, api, world, role="administrator")
        assert response.status_code == 201, response.text


class TestTenantScope:
    def test_another_organizations_job_is_not_found(self, client, api, world):
        created = _plan(client, api, world)
        job_id = created.json()["job_id"]

        response = client.get(
            f"/v1/organizations/{world['other']}/bulk-jobs/{job_id}",
            headers=_auth(api, world["owner"]),
        )
        assert response.status_code in (403, 404)

    def test_a_recipient_from_another_organization_is_invalid_not_an_error(
        self, client, api, world, session_factory
    ):
        with session_factory() as session:
            outsider_person = OrganizationPerson(
                organization_id=world["other"],
                full_name="Outsider",
                email=f"out-{uuid4().hex[:6]}@example.test",
                status=PersonStatus.ACTIVE,
                created_at=NOW,
                updated_at=NOW,
            )
            session.add(outsider_person)
            session.commit()
            session.refresh(outsider_person)
            outsider_id = outsider_person.id

        response = client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs",
            headers=_auth(api, world["owner"]),
            json={
                "idempotency_key": "bulk-outsider",
                "product_id": str(world["product"]),
                "country": "NG",
                "currency": "NGN",
                "person_ids": [str(outsider_id)],
            },
        )

        assert response.status_code == 201
        assert response.json()["invalid"] == 1


class TestTheFlow:
    def test_planning_holds_nothing_and_funding_holds_per_line(
        self, client, api, world
    ):
        planned = _plan(client, api, world)
        assert planned.status_code == 201
        body = planned.json()
        assert body["recipient_count"] == 3
        assert body["reserved"] == 0

        funded = client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{body['job_id']}/fund",
            headers=_auth(api, world["owner"]),
        )
        assert funded.json()["reserved"] == 3

    def test_a_replayed_submission_returns_the_same_job(self, client, api, world):
        first = _plan(client, api, world, key="same-key")
        second = _plan(client, api, world, key="same-key")
        assert first.json()["job_id"] == second.json()["job_id"]

    def test_reusing_a_key_for_a_different_request_is_a_conflict(
        self, client, api, world
    ):
        first = _plan(client, api, world, key="conflicting-key")
        assert first.status_code == 201

        second = client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs",
            headers=_auth(api, world["owner"]),
            json={
                "idempotency_key": "conflicting-key",
                "product_id": str(world["product"]),
                "country": "NG",
                "currency": "NGN",
                "person_ids": [str(world["people"][0])],
            },
        )

        assert second.status_code == 409
        assert second.json()["error"] == "idempotency_conflict"

    def test_the_item_list_shows_each_recipients_own_state(
        self, client, api, world
    ):
        planned = _plan(client, api, world)
        job_id = planned.json()["job_id"]

        response = client.get(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}/items",
            headers=_auth(api, world["owner"]),
        )

        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 3
        assert {item["state"] for item in items} == {"pending"}

    def test_provisioning_an_internet_line_needs_no_carrier_profile(
        self, client, api, world
    ):
        """The product here is VOICE: the grant is the service."""
        planned = _plan(client, api, world)
        job_id = planned.json()["job_id"]
        headers = _auth(api, world["owner"])
        client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}/fund",
            headers=headers,
        )

        provisioned = client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}/provision",
            headers=headers,
        )

        assert provisioned.status_code == 200
        assert provisioned.json()["provisioned"] == 3

    def test_provisioning_twice_is_a_question_not_a_second_purchase(
        self, client, api, world
    ):
        planned = _plan(client, api, world)
        job_id = planned.json()["job_id"]
        headers = _auth(api, world["owner"])
        client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}/fund",
            headers=headers,
        )
        first = client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}/provision",
            headers=headers,
        )
        second = client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}/provision",
            headers=headers,
        )

        assert second.status_code == 200
        assert second.json() == first.json()


class TestActivationHandoff:
    def _provisioned(self, client, api, world):
        planned = _plan(client, api, world)
        job_id = planned.json()["job_id"]
        headers = _auth(api, world["owner"])
        client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}/fund",
            headers=headers,
        )
        client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}/provision",
            headers=headers,
        )
        items = client.get(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}/items",
            headers=headers,
        ).json()["items"]
        return job_id, items[0]["item_id"], headers

    def test_the_token_crosses_the_wire_exactly_once(self, client, api, world):
        job_id, item_id, headers = self._provisioned(client, api, world)

        issued = client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}"
            f"/items/{item_id}/activation-request",
            headers=headers,
        )

        assert issued.status_code == 201
        assert issued.json()["token"]
        # And a second issue for the same line is refused, because two live
        # tokens is two people who can claim one line.
        again = client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}"
            f"/items/{item_id}/activation-request",
            headers=headers,
        )
        assert again.status_code == 409

    def test_an_outsider_can_claim_the_line_bought_for_them(
        self, client, api, world
    ):
        """Requiring tenant membership to accept a work SIM would be backwards."""
        job_id, item_id, headers = self._provisioned(client, api, world)
        token = client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}"
            f"/items/{item_id}/activation-request",
            headers=headers,
        ).json()["token"]

        redeemed = client.post(
            "/v1/me/activation-requests/redeem",
            headers=_auth(api, world["outsider"]),
            json={"token": token},
        )

        assert redeemed.status_code == 200, redeemed.text
        assert redeemed.json()["state"] == "redeemed"

    def test_a_token_cannot_be_claimed_twice(self, client, api, world):
        job_id, item_id, headers = self._provisioned(client, api, world)
        token = client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}"
            f"/items/{item_id}/activation-request",
            headers=headers,
        ).json()["token"]
        client.post(
            "/v1/me/activation-requests/redeem",
            headers=_auth(api, world["outsider"]),
            json={"token": token},
        )

        second = client.post(
            "/v1/me/activation-requests/redeem",
            headers=_auth(api, world["member"]),
            json={"token": token},
        )

        assert second.status_code == 409
        assert second.json()["error"] == "activation_request_spent"

    def test_an_expired_token_is_durably_marked_expired(
        self, client, api, world, session_factory
    ):
        job_id, item_id, headers = self._provisioned(client, api, world)
        token = client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}"
            f"/items/{item_id}/activation-request",
            headers=headers,
        ).json()["token"]
        with session_factory() as session:
            request = session.exec(
                select(ActivationRequest).where(
                    ActivationRequest.bulk_job_item_id == UUID(item_id)
                )
            ).one()
            request.expires_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
            session.add(request)
            session.commit()
            request_id = request.id

        response = client.post(
            "/v1/me/activation-requests/redeem",
            headers=_auth(api, world["outsider"]),
            json={"token": token},
        )

        assert response.status_code == 410
        with session_factory() as session:
            persisted = session.get(ActivationRequest, request_id)
            assert persisted is not None
            assert persisted.state is ActivationRequestState.EXPIRED

    def test_a_made_up_token_is_not_found(self, client, api, world):
        response = client.post(
            "/v1/me/activation-requests/redeem",
            headers=_auth(api, world["outsider"]),
            json={"token": "x" * 43},
        )
        assert response.status_code == 404

    def test_redeeming_needs_a_session(self, client, api, world):
        response = client.post(
            "/v1/me/activation-requests/redeem", json={"token": "x" * 43}
        )
        assert response.status_code in (401, 403)

    def test_an_activation_request_is_not_an_installation(
        self, client, api, world, session_factory
    ):
        """A claimed invitation says nothing about a profile on a handset."""
        job_id, item_id, headers = self._provisioned(client, api, world)
        token = client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}"
            f"/items/{item_id}/activation-request",
            headers=headers,
        ).json()["token"]
        client.post(
            "/v1/me/activation-requests/redeem",
            headers=_auth(api, world["outsider"]),
            json={"token": token},
        )

        with session_factory() as session:
            from app.connectivity.models import CarrierLine, EsimInstallation

            assert session.exec(select(EsimInstallation)).all() == []
            assert session.exec(select(CarrierLine)).all() == []
            item = session.get(BulkJobItem, UUID(item_id))
            assert item.provisioned_at is not None


class TestCancellation:
    def test_a_reserved_line_can_be_withdrawn(self, client, api, world):
        planned = _plan(client, api, world)
        job_id = planned.json()["job_id"]
        headers = _auth(api, world["owner"])
        client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}/fund",
            headers=headers,
        )
        item_id = client.get(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}/items",
            headers=headers,
        ).json()["items"][0]["item_id"]

        response = client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}"
            f"/items/{item_id}/cancel",
            headers=headers,
            json={"reason": "left_before_start"},
        )

        assert response.status_code == 200
        assert response.json()["state"] == "cancelled"

    def test_a_provisioned_line_is_refused_with_a_reason(self, client, api, world):
        planned = _plan(client, api, world)
        job_id = planned.json()["job_id"]
        headers = _auth(api, world["owner"])
        client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}/fund",
            headers=headers,
        )
        client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}/provision",
            headers=headers,
        )
        item_id = client.get(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}/items",
            headers=headers,
        ).json()["items"][0]["item_id"]

        response = client.post(
            f"/v1/organizations/{world['acme']}/bulk-jobs/{job_id}"
            f"/items/{item_id}/cancel",
            headers=headers,
            json={"reason": "changed_mind"},
        )

        assert response.status_code == 409
        assert response.json()["error"] == "item_already_provisioned"
