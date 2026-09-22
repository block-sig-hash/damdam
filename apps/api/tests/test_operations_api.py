"""The internal operations surface over HTTP — US-41, chunk 25.

The service suite proves the rules on real PostgreSQL. This proves the boundary,
and the boundary is where this chunk's central claim lives:

**An enterprise administrator cannot reach any of it.** Not "is denied by a
permission check" — cannot reach it. Operations routes verify a token minted for
the `admin` audience, and a tenant token is a different audience entirely. The
owner of an organization, holding every permission chunk 07 can grant, gets the
same `401` as a stranger. There is no operations permission to grant, which is
the strongest form of the separation the assignment asks for.

The rest is what only exists at the edge: the reconciliation refusal surviving
as a `409` rather than being smoothed into a `200`, a replayed `POST` returning
the decision that already exists, a masked lookup that writes its own audit row,
and a tenant-scoped export whose scope is a join rather than a parameter.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.auth.models import (
    AdminUser,
    Locale,
    Organization,
    OrganizationType,
    Platform,
    User,
)
from app.catalog.models import LegalEntity, Product, ProductKind
from app.connectivity.models import (
    ActivationState,
    AssignedNumber,
    CarrierLine,
    Entitlement,
    NetworkState,
)
from app.fulfilment.models import AttemptOutcome, SupplierAttempt
from app.ledger.models import AccountKind, LedgerAccount, OwnerKind
from app.operations.models import OperatorAction, OperatorActionKind
from app.orders.models import Order, OrderItem, PaymentState, ProvisioningState
from app.organizations.models import OrganizationRole
from app.organizations.service import MembershipService
from app.refunds.models import (
    BankFundingStatus,
    BankTransferReceipt,
    ExceptionItem,
    ExceptionKind,
)

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)

#: A whole ICCID, only ever used to prove that the surface does not return it.
ICCID = "8923410000000012345"
E164 = "+2348011122233"


@pytest.fixture
def client(api):
    return TestClient(api, raise_server_exceptions=False)


def _admin_headers(settings, clock, admin_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": str(admin_id),
            "aud": "admin",
            "type": "access",
            "iat": clock(),
            "exp": clock() + timedelta(minutes=15),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _tenant_headers(api, user_id: UUID) -> dict[str, str]:
    with api.state.session_factory() as session:
        pair = api.state.otp_service.tokens.issue(
            session, session.get(User, user_id), api.state.clock()
        )
        session.commit()
    return {"Authorization": f"Bearer {pair.access_token}"}


@pytest.fixture
def world(api, session_factory, clock):
    """One organization that paid for one line whose outcome we lost.

    Deliberately an *organization's* order rather than a personal one: the
    tenant-scoped export has to have something to scope, and the privilege test
    needs a real administrator of a real organization to be turned away.
    """
    memberships = MembershipService(clock=clock)
    with session_factory() as session:
        admin = AdminUser(
            email=f"ops-{uuid4().hex[:8]}@example.test",
            password_hash="x",
            locale=Locale.EN,
        )
        organization = Organization(
            org_type=OrganizationType.ENTERPRISE,
            name="Acme",
            primary_contact_name="Contact",
            email=f"acme-{uuid4().hex[:8]}@example.test",
            password_hash="unused",
            phone_number="+2348000000000",
            locale=Locale.EN,
        )
        owner = User(
            phone_number=f"+23487{uuid4().int % 10**8:08d}",
            first_name="Owner",
            platform=Platform.ANDROID,
        )
        holder = User(
            phone_number=f"+23486{uuid4().int % 10**8:08d}",
            first_name="Holder",
            platform=Platform.ANDROID,
        )
        entity = LegalEntity(code=f"E{uuid4().hex[:6]}", name="Seller", country="NG")
        product = Product(
            sku=f"sku-{uuid4().hex[:8]}", name="Nigeria 5GB", kind=ProductKind.DATA
        )
        session.add_all([admin, organization, owner, holder, entity, product])
        session.commit()
        for obj in (admin, organization, owner, holder, entity, product):
            session.refresh(obj)

        memberships.seed_member(session, organization, owner, OrganizationRole.OWNER)
        session.commit()

        order = Order(
            reference=f"ORD-{uuid4().hex[:8].upper()}",
            seller_legal_entity_id=entity.id,
            payer_organization_id=organization.id,
            currency="NGN",
            total_amount=Decimal("5000.00"),
            payment_state=PaymentState.PAID,
            placed_at=NOW,
        )
        session.add(order)
        session.commit()
        session.refresh(order)

        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            recipient_user_id=holder.id,
            quantity=1,
            unit_currency="NGN",
            unit_amount=Decimal("5000.00"),
            provisioning_state=ProvisioningState.OUTCOME_UNKNOWN,
        )
        session.add(item)
        session.commit()
        session.refresh(item)

        attempt = SupplierAttempt(
            order_item_id=item.id,
            provider="telnyx",
            idempotency_key=f"item:{item.id}:1",
            attempt_number=1,
            outcome=AttemptOutcome.HELD_FOR_REVIEW,
            requested_at=NOW,
            created_at=NOW,
        )
        entitlement = Entitlement(
            order_item_id=item.id,
            holder_user_id=holder.id,
            product_id=product.id,
            data_bytes_total=5_368_709_120,
            voice_seconds_total=0,
            granted_at=NOW,
        )
        receipt = BankTransferReceipt(
            bank_account_reference="bank-ngn-1",
            statement_reference=f"stmt-{uuid4().hex}",
            currency="NGN",
            amount=Decimal("2500.00"),
            payer_reference=order.reference,
            value_date=NOW,
            status=BankFundingStatus.UNMATCHED,
            imported_at=NOW,
        )
        session.add(receipt)
        session.flush()
        exception = ExceptionItem(
            kind=ExceptionKind.UNMATCHED_BANK_TRANSFER,
            subject_reference=f"bank:{receipt.id}",
            detail="a reconciled bank line with no customer match",
            raised_at=NOW,
        )
        dismissible_exception = ExceptionItem(
            kind=ExceptionKind.USAGE_DISCREPANCY,
            subject_reference="line:manual-review",
            detail="usage evidence was reviewed and found to be a duplicate",
            raised_at=NOW,
        )
        session.add_all([attempt, entitlement, exception, dismissible_exception])
        session.commit()
        for obj in (attempt, entitlement, exception, dismissible_exception):
            session.refresh(obj)

        line = CarrierLine(
            entitlement_id=entitlement.id,
            carrier="telnyx",
            carrier_line_reference="SUP-REF-0001",
            iccid=ICCID,
            activation_state=ActivationState.ACTIVE,
            network_state=NetworkState.ATTACHED,
            provider_status="active",
        )
        session.add(line)
        session.commit()
        session.refresh(line)
        session.add(
            AssignedNumber(
                carrier_line_id=line.id,
                e164=E164,
                country="NG",
                assigned_at=NOW,
            )
        )

        credit = LedgerAccount(
            owner_kind=OwnerKind.ORGANIZATION,
            owner_organization_id=organization.id,
            kind=AccountKind.SERVICE_CREDIT,
            currency="NGN",
        )
        session.add(credit)
        session.commit()
        session.refresh(credit)

        return {
            "admin_id": admin.id,
            "organization_id": organization.id,
            "owner_id": owner.id,
            "holder_id": holder.id,
            "order_reference": order.reference,
            "item_id": item.id,
            "attempt_id": attempt.id,
            "exception_id": exception.id,
            "dismissible_exception_id": dismissible_exception.id,
            "receipt_id": receipt.id,
            "line_id": line.id,
            "credit_id": credit.id,
        }


class TestEnterpriseVersusInternal:
    """The claim this chunk exists to make.

    Chunk 24 gave enterprise administrators real financial reach inside their
    own tenant — funding, departmental spend, offboarding. None of it is a step
    towards this surface, and these tests are what keeps that true when somebody
    later wonders whether an owner should be allowed to dismiss their own
    exception item "since it is theirs anyway".
    """

    def test_an_organization_owner_cannot_read_the_operations_queue(
        self, api, client, world
    ):
        response = client.get(
            "/v1/operations/exceptions",
            headers=_tenant_headers(api, world["owner_id"]),
        )
        assert response.status_code == 401

    def test_an_organization_owner_cannot_resolve_a_supplier_attempt(
        self, api, client, world
    ):
        response = client.post(
            f"/v1/operations/supplier-attempts/{world['attempt_id']}/resolution",
            headers=_tenant_headers(api, world["owner_id"]),
            json={
                "succeeded": True,
                "provider_reference": "SUP-REF-0001",
                "reason": "it is our own line",
                "idempotency_key": "owner-1",
            },
        )
        assert response.status_code == 401

    def test_an_organization_owner_cannot_export_their_own_lines_from_here(
        self, api, client, world
    ):
        """Not because the data is secret from them — chunk 24 gives them their
        own exports. Because reaching it *through this surface* would mean the
        surface accepts tenant tokens, and then the only thing separating an
        administrator from a compensating ledger entry is a permission string.
        """
        response = client.get(
            f"/v1/operations/organizations/{world['organization_id']}/lines.csv",
            headers=_tenant_headers(api, world["owner_id"]),
            params={"reason": "audit", "idempotency_key": "owner-2"},
        )
        assert response.status_code == 401

    def test_no_token_reaches_nothing(self, client, world):
        assert client.get("/v1/operations/exceptions").status_code == 401
        assert (
            client.post(
                f"/v1/operations/exceptions/{world['dismissible_exception_id']}/dismissal",
                json={"reason": "no", "idempotency_key": "anon"},
            ).status_code
            == 401
        )


class TestThePaidUnknownSupplierCase:
    def test_resolving_without_reconciliation_is_refused_over_http(
        self, client, settings, clock, world, session_factory
    ):
        """The refusal has to survive the boundary as a refusal.

        A `409` and an unchanged attempt, not a `200` with a warning field a
        client is free to ignore.
        """
        with session_factory() as session:
            attempt = session.get(SupplierAttempt, world["attempt_id"])
            attempt.outcome = AttemptOutcome.OUTCOME_UNKNOWN
            session.add(attempt)
            session.commit()

        response = client.post(
            f"/v1/operations/supplier-attempts/{world['attempt_id']}/resolution",
            headers=_admin_headers(settings, clock, world["admin_id"]),
            json={
                "succeeded": True,
                "provider_reference": "SUP-REF-0001",
                "reason": "the customer says it works",
                "idempotency_key": "ops-1",
            },
        )

        assert response.status_code == 409
        assert response.json()["error"] == "reconciliation_required"
        with session_factory() as session:
            attempt = session.get(SupplierAttempt, world["attempt_id"])
            assert attempt.outcome is AttemptOutcome.OUTCOME_UNKNOWN
            assert session.exec(select(OperatorAction)).all() == []

    def test_a_confirmed_success_needs_the_suppliers_own_reference(
        self, client, settings, clock, world
    ):
        response = client.post(
            f"/v1/operations/supplier-attempts/{world['attempt_id']}/resolution",
            headers=_admin_headers(settings, clock, world["admin_id"]),
            json={
                "succeeded": True,
                "reason": "supplier confirmed by email",
                "idempotency_key": "ops-2",
            },
        )

        assert response.status_code == 409
        assert response.json()["error"] == "provider_reference_required"

    def test_a_reconciled_success_provisions_the_line_and_records_why(
        self, client, settings, clock, world, session_factory
    ):
        """The assignment's first named scenario, end to end over HTTP."""
        response = client.post(
            f"/v1/operations/supplier-attempts/{world['attempt_id']}/resolution",
            headers=_admin_headers(settings, clock, world["admin_id"]),
            json={
                "succeeded": True,
                "provider_reference": "SUP-REF-0001",
                "reason": "reconciled against telnyx, profile exists",
                "idempotency_key": "ops-3",
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["kind"] == OperatorActionKind.CONFIRM_SUPPLIER_SUCCESS.value
        assert body["actor_admin_id"] == str(world["admin_id"])
        assert body["reason"].startswith("reconciled against telnyx")
        assert body["before_state"]["attempt_outcome"] == "held_for_review"
        assert body["after_state"]["provider_reference"] == "SUP-REF-0001"
        # No money moved, so no entry is claimed. A populated field here would
        # be worse than an empty one: it would imply a posting nobody made.
        assert body["ledger_entry_id"] is None

        with session_factory() as session:
            item = session.get(OrderItem, world["item_id"])
            assert item.provisioning_state is ProvisioningState.PROVISIONED

    def test_a_replayed_resolution_is_the_same_resolution(
        self, client, settings, clock, world, session_factory
    ):
        """An operator who lost the response and clicked again.

        The second call must return the first decision rather than take a
        second one — and must not provision, charge or post anything twice.
        """
        headers = _admin_headers(settings, clock, world["admin_id"])
        payload = {
            "succeeded": True,
            "provider_reference": "SUP-REF-0001",
            "reason": "reconciled against telnyx",
            "idempotency_key": "ops-replay",
        }
        url = f"/v1/operations/supplier-attempts/{world['attempt_id']}/resolution"

        first = client.post(url, headers=headers, json=payload)
        second = client.post(url, headers=headers, json=payload)

        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        assert first.json()["id"] == second.json()["id"]
        with session_factory() as session:
            assert len(session.exec(select(OperatorAction)).all()) == 1

    def test_a_reason_is_not_optional(self, client, settings, clock, world):
        """Rejected by the schema, then by a database check if it ever got past.

        An action nobody explained is one nobody can review, and a blank reason
        is the form-shaped version of not explaining.
        """
        response = client.post(
            f"/v1/operations/supplier-attempts/{world['attempt_id']}/resolution",
            headers=_admin_headers(settings, clock, world["admin_id"]),
            json={
                "succeeded": False,
                "reason": "",
                "idempotency_key": "ops-4",
            },
        )
        assert response.status_code == 422


class TestThePaymentDiscrepancyCase:
    def test_a_discrepancy_is_settled_by_a_balanced_entry(
        self, client, settings, clock, world, session_factory
    ):
        """The assignment's second named scenario.

        Note what the response carries: a `ledger_entry_id`. There is no field
        anywhere on this surface that sets a balance, so the only way this
        number could exist is a posting chunk 10 accepted — and chunk 10 rejects
        anything that does not balance.
        """
        response = client.post(
            "/v1/operations/payment-discrepancies",
            headers=_admin_headers(settings, clock, world["admin_id"]),
            json={
                "customer_account_id": str(world["credit_id"]),
                "reason": "bank credit matched to order by statement line 44",
                "idempotency_key": "disc-1",
                "exception_item_id": str(world["exception_id"]),
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["ledger_entry_id"]
        assert body["after_state"]["compensating_entry"] == body["ledger_entry_id"]
        with session_factory() as session:
            assert session.get(ExceptionItem, world["exception_id"]).resolved_at

    def test_a_replayed_discrepancy_posts_once(
        self, client, settings, clock, world, session_factory
    ):
        headers = _admin_headers(settings, clock, world["admin_id"])
        payload = {
            "customer_account_id": str(world["credit_id"]),
            "reason": "bank credit matched to order",
            "idempotency_key": "disc-replay",
            "exception_item_id": str(world["exception_id"]),
        }

        first = client.post(
            "/v1/operations/payment-discrepancies", headers=headers, json=payload
        )
        second = client.post(
            "/v1/operations/payment-discrepancies", headers=headers, json=payload
        )

        assert first.status_code == 201, first.text
        assert first.json()["id"] == second.json()["id"]
        assert first.json()["ledger_entry_id"] == second.json()["ledger_entry_id"]

    def test_there_is_no_balance_setting_endpoint(self, api):
        """A structural assertion, and the honest way to test an absence.

        The assignment forbids unrestricted balance editing. Rather than trust
        that nobody adds one, check the generated schema: no operations route
        accepts a bare balance, and no operations method is a `PUT` or `PATCH`
        against an account.
        """
        paths = [path for path in api.openapi()["paths"] if "/operations" in path]
        assert paths
        for path in paths:
            assert "ledger-accounts" not in path
            methods = set(api.openapi()["paths"][path])
            assert methods <= {"get", "post"}


class TestSensitiveData:
    def test_a_lookup_masks_what_it_returns_and_records_the_look(
        self, client, settings, clock, world, session_factory
    ):
        response = client.post(
            "/v1/operations/lines/lookup",
            headers=_admin_headers(settings, clock, world["admin_id"]),
            json={
                "iccid": ICCID,
                "reason": "customer called about no service",
                "idempotency_key": "look-1",
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["line_id"] == str(world["line_id"])
        # The identifier is recognisable and unusable, and the whole value is
        # nowhere in the payload — including in a field somebody added later.
        assert body["iccid_masked"].endswith(ICCID[-6:])
        assert ICCID not in response.text
        assert E164 not in response.text
        assert body["e164_masked"].endswith(E164[-4:])
        assert body["organization_id"] == str(world["organization_id"])

        with session_factory() as session:
            action = session.get(OperatorAction, UUID(body["access_action_id"]))
            assert action.kind is OperatorActionKind.VIEW_SENSITIVE_RECORD
            assert action.subject_reference == f"carrier_line:{world['line_id']}"
            assert action.reason.startswith("customer called")

    def test_no_response_shape_can_carry_activation_material(self, api):
        """Installation credentials are absent by construction, not by masking.

        Chunk 15 stores the LPA string that actually installs a profile. If a
        future view added it, this fails — which is the point, because the
        review that would otherwise have to catch it is a human reading a diff.

        Only the **response** shapes are checked, and the distinction is real:
        `LineLookupRequest` accepts a whole ICCID because that is what a
        customer reads out over the phone. Accepting an identifier the caller
        already has is not disclosure; returning one they did not is.
        """
        schemas = api.openapi()["components"]["schemas"]
        operations_schemas = {
            name: schema
            for name, schema in schemas.items()
            if name.startswith(("LineSupport", "OperatorAction", "QueueEntry"))
            and not name.endswith("Request")
        }
        assert operations_schemas
        for name, schema in operations_schemas.items():
            fields = set(schema.get("properties", {}))
            assert not fields & {
                "activation_code_lpa",
                "activation_code",
                "iccid",
                "e164",
                "matching_id",
                "confirmation_code",
            }, name

    def test_a_lookup_needs_exactly_one_identifier(
        self, client, settings, clock, world
    ):
        headers = _admin_headers(settings, clock, world["admin_id"])
        neither = client.post(
            "/v1/operations/lines/lookup",
            headers=headers,
            json={"reason": "fishing", "idempotency_key": "look-2"},
        )
        both = client.post(
            "/v1/operations/lines/lookup",
            headers=headers,
            json={
                "iccid": ICCID,
                "e164": E164,
                "reason": "fishing",
                "idempotency_key": "look-3",
            },
        )
        assert neither.status_code == 400
        assert neither.json()["error"] == "one_identifier_required"
        assert both.status_code == 400


class TestTenantScopedExport:
    def test_the_export_covers_one_organization_and_is_masked(
        self, client, settings, clock, world, session_factory
    ):
        response = client.get(
            f"/v1/operations/organizations/{world['organization_id']}/lines.csv",
            headers=_admin_headers(settings, clock, world["admin_id"]),
            params={"reason": "support ticket 41", "idempotency_key": "exp-1"},
        )

        assert response.status_code == 200, response.text
        body = response.text
        assert "line_id,carrier,iccid_masked" in body
        assert str(world["line_id"]) in body
        assert ICCID not in body
        assert E164 not in body
        with session_factory() as session:
            action = session.exec(
                select(OperatorAction).where(
                    OperatorAction.subject_reference
                    == f"organization:{world['organization_id']}"
                )
            ).one()
            assert action.kind is OperatorActionKind.VIEW_SENSITIVE_RECORD

    def test_another_organizations_export_is_empty_rather_than_everybodys(
        self, client, settings, clock, world
    ):
        """The scope is a join through the paying order, not a filter.

        An unknown id therefore yields an empty file rather than an unscoped
        one, which is the failure mode a `WHERE` built from a caller-supplied
        string eventually produces.
        """
        response = client.get(
            f"/v1/operations/organizations/{uuid4()}/lines.csv",
            headers=_admin_headers(settings, clock, world["admin_id"]),
            params={"reason": "checking scope", "idempotency_key": "exp-2"},
        )

        assert response.status_code == 200
        assert str(world["line_id"]) not in response.text


class TestTheQueueOverHttp:
    def test_a_financial_exception_cannot_be_dismissed(
        self, client, settings, clock, world
    ):
        response = client.post(
            f"/v1/operations/exceptions/{world['exception_id']}/dismissal",
            headers=_admin_headers(settings, clock, world["admin_id"]),
            json={
                "reason": "ignore the unmatched money",
                "idempotency_key": "unsafe-dismissal",
            },
        )

        assert response.status_code == 409
        assert response.json()["error"] == "exception_requires_resolution"

    def test_the_queue_is_searchable_by_support_reference(
        self, client, settings, clock, world
    ):
        headers = _admin_headers(settings, clock, world["admin_id"])
        reference = f"bank:{world['receipt_id']}"

        matched = client.get(
            "/v1/operations/exceptions",
            headers=headers,
            params={"reference": "bank:"},
        )
        missed = client.get(
            "/v1/operations/exceptions",
            headers=headers,
            params={"reference": "refund:"},
        )

        assert matched.status_code == 200, matched.text
        assert [entry["subject_reference"] for entry in matched.json()["entries"]] == [
            reference
        ]
        assert missed.json()["entries"] == []

    def test_a_dismissal_resolves_rather_than_deletes(
        self, client, settings, clock, world, session_factory
    ):
        """An empty queue is not evidence of a quiet week.

        "Somebody read this and decided it was fine" is information; a deleted
        row is the absence of information that looks identical to nothing having
        happened.
        """
        headers = _admin_headers(settings, clock, world["admin_id"])
        response = client.post(
            f"/v1/operations/exceptions/{world['dismissible_exception_id']}/dismissal",
            headers=headers,
            json={
                "reason": "duplicate of ticket 40, already settled",
                "idempotency_key": "dis-1",
            },
        )

        assert response.status_code == 201, response.text
        with session_factory() as session:
            item = session.get(ExceptionItem, world["dismissible_exception_id"])
            assert item is not None
            assert item.resolved_at is not None

        still_there = client.get(
            "/v1/operations/exceptions",
            headers=headers,
            params={"include_resolved": True, "reference": "line:manual-review"},
        )
        assert [
            entry["exception_id"] for entry in still_there.json()["entries"]
        ] == [str(world["dismissible_exception_id"])]
        assert still_there.json()["entries"][0]["action_count"] == 1

    def test_history_carries_every_mandatory_audit_field(
        self, client, settings, clock, world
    ):
        headers = _admin_headers(settings, clock, world["admin_id"])
        client.post(
            f"/v1/operations/exceptions/{world['dismissible_exception_id']}/dismissal",
            headers=headers,
            json={"reason": "already settled", "idempotency_key": "dis-2"},
        )

        response = client.get("/v1/operations/actions", headers=headers)

        assert response.status_code == 200, response.text
        action = response.json()["actions"][0]
        for field in (
            "kind",
            "subject_kind",
            "subject_reference",
            "actor_admin_id",
            "reason",
            "idempotency_key",
            "before_state",
            "after_state",
            "created_at",
        ):
            assert action[field] is not None, field
