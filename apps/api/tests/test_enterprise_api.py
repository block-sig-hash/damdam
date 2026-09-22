"""US-40 chunk 24 — enterprise funding, reports and offboarding over HTTP.

The service suite proves the rules. This proves the routes apply them and adds
the three properties that only exist at the boundary:

**Financial permissions are separate.** Funding and reports are `billing:read`
and `report:read`; the export is `report:export`; offboarding is
`member:revoke`. A plain member reaches none of it.

**The export is audited and safe to open.** A tenant's staff spend leaving on a
laptop writes an audit row, and every cell passes `csv_safe`.

**The freshness travels with the file.** A CSV outlives the screen it came from,
so "as of" is written into it rather than rendered beside it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.audit.models import AuditLog
from app.auth.models import Locale, Organization, OrganizationType, Platform, User
from app.ledger.models import AccountKind, Direction, OwnerKind
from app.ledger.service import LedgerService, Posting
from app.mfa.totp import generate
from app.organizations.models import OrganizationRole
from app.organizations.service import MembershipService
from app.people.models import OrganizationPerson, OrganizationTeam, PersonStatus

NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)


@pytest.fixture
def client(api):
    return TestClient(api, raise_server_exceptions=False)


def _user(session: Session, label: str) -> UUID:
    user = User(
        phone_number=f"+23487{abs(hash(label)) % 10**8:08d}",
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



def _stepped_up(api, client, user_id: UUID, organization_id: UUID, clock):
    """A session that has completed a second factor.

    `member:revoke` is on chunk 07's step-up list, and offboarding sits behind
    it: ending somebody's access is exactly what a stolen session must not be
    able to do. Tests that offboard therefore have to step up, the same as a
    real administrator does.
    """
    import base64

    headers = _auth(api, user_id)
    enrolled = client.post("/v1/auth/mfa/enroll", headers=headers)
    assert enrolled.status_code == 200, enrolled.text
    secret = enrolled.json()["secret"]
    raw = base64.b32decode(secret + "=" * (-len(secret) % 8))
    confirmed = client.post(
        "/v1/auth/mfa/enroll/confirm",
        headers=headers,
        json={"code": generate(raw, clock.value)},
    )
    assert confirmed.status_code == 200, confirmed.text
    clock.advance(seconds=30)
    stepped = client.post(
        f"/v1/organizations/{organization_id}/step-up",
        headers=headers,
        json={"code": generate(raw, clock.value)},
    )
    assert stepped.status_code == 200, stepped.text
    return headers


@pytest.fixture
def world(api, session_factory, clock):
    memberships = MembershipService(clock=clock)
    with session_factory() as session:
        acme = _organization(session, "Acme")
        other = _organization(session, "Other")
        roles = {
            role.value: _user(session, f"acme-{role.value}")
            for role in OrganizationRole
        }
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

        team = OrganizationTeam(
            organization_id=acme.id,
            # A name that a spreadsheet would evaluate, so the export test is
            # about a real value rather than an invented one.
            name="=Field Ops",
            created_at=NOW,
        )
        session.add(team)
        session.flush()
        person = OrganizationPerson(
            organization_id=acme.id,
            full_name="Ada Obi",
            email=f"ada-{uuid4().hex[:6]}@example.test",
            team_id=team.id,
            status=PersonStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
        )
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
                Posting(clearing, Direction.DEBIT, Decimal("25000.00")),
                Posting(credit, Direction.CREDIT, Decimal("25000.00")),
            ],
        )
        session.commit()
        return {
            "acme": acme.id,
            "other": other.id,
            "person": person.id,
            "team": team.id,
            **roles,
        }


class TestFinancialPermissions:
    @pytest.mark.parametrize(
        ("path", "role", "expected"),
        [
            ("funding", "billing", 200),
            ("funding", "member", 403),
            ("reports/departments", "billing", 200),
            ("reports/departments", "member", 403),
            ("reports/departments.csv", "billing", 403),
            ("reports/departments.csv", "administrator", 200),
            ("offboardings", "member", 403),
            ("offboardings", "billing", 403),
        ],
    )
    def test_each_surface_asks_for_its_own_permission(
        self, client, api, world, path, role, expected
    ):
        """Reading money, reading reports and exporting them are three rights.

        Billing may read a report and may **not** export one: a download leaves
        the building, and chunk 07 put that behind `report:export`, which only
        administrators and owners hold.
        """
        response = client.get(
            f"/v1/organizations/{world['acme']}/{path}",
            headers=_auth(api, world[role]),
        )
        assert response.status_code == expected, response.text


class TestFunding:
    def test_credit_and_pooling_are_reported_apart(self, client, api, world):
        response = client.get(
            f"/v1/organizations/{world['acme']}/funding",
            headers=_auth(api, world["billing"]),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["balance"] == "25000.00"
        assert body["available"] == "25000.00"
        assert body["pooling"] is False
        assert "pooling" in body["pooling_note"]

    def test_an_unset_cap_is_null_rather_than_a_number(self, client, api, world):
        """A missing cap rendered as infinity is a commitment nobody made."""
        body = client.get(
            f"/v1/organizations/{world['acme']}/funding",
            headers=_auth(api, world["billing"]),
        ).json()

        assert body["period_cap"] is None
        assert body["headroom"] is None

    def test_another_organizations_funding_is_refused(self, client, api, world):
        response = client.get(
            f"/v1/organizations/{world['other']}/funding",
            headers=_auth(api, world["billing"]),
        )
        assert response.status_code in (403, 404)


class TestDepartmentalReport:
    def test_a_report_with_no_usage_says_it_observed_nothing(
        self, client, api, world
    ):
        body = client.get(
            f"/v1/organizations/{world['acme']}/reports/departments",
            headers=_auth(api, world["billing"]),
        ).json()

        assert body["observed_through"] is None
        assert body["usage_total"] == "0.00"

    def test_grouping_can_be_asked_for_by_cost_centre(self, client, api, world):
        response = client.get(
            f"/v1/organizations/{world['acme']}/reports/departments?by=cost_centre",
            headers=_auth(api, world["billing"]),
        )
        assert response.status_code == 200

    def test_an_unknown_grouping_is_refused_before_it_reaches_the_service(
        self, client, api, world
    ):
        response = client.get(
            f"/v1/organizations/{world['acme']}/reports/departments?by=whatever",
            headers=_auth(api, world["billing"]),
        )
        assert response.status_code == 422


class TestAuditedExport:
    def test_a_team_name_that_looks_like_a_formula_is_defused(
        self, client, api, world
    ):
        """The team is literally called `=Field Ops`. Names like that exist."""
        response = client.get(
            f"/v1/organizations/{world['acme']}/reports/departments.csv",
            headers=_auth(api, world["administrator"]),
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert not any(
            line.startswith("=Field") for line in response.text.splitlines()
        )
        assert "'=Field Ops" in response.text

    def test_the_file_carries_its_own_freshness(self, client, api, world):
        """A CSV outlives the screen; a total with no "as of" becomes current."""
        text = client.get(
            f"/v1/organizations/{world['acme']}/reports/departments.csv",
            headers=_auth(api, world["administrator"]),
        ).text

        assert "Usage observed through" in text
        assert "no usage has been observed" in text

    def test_the_download_is_recorded(self, client, api, world):
        client.get(
            f"/v1/organizations/{world['acme']}/reports/departments.csv",
            headers=_auth(api, world["administrator"]),
        )

        with api.state.session_factory() as session:
            entries = session.exec(
                select(AuditLog).where(
                    AuditLog.outcome == "enterprise_report_exported"
                )
            ).all()
        assert len(entries) == 1
        assert str(world["acme"]) in (entries[0].reference or "")

    def test_another_organizations_export_is_refused(self, client, api, world):
        response = client.get(
            f"/v1/organizations/{world['other']}/reports/departments.csv",
            headers=_auth(api, world["administrator"]),
        )
        assert response.status_code in (403, 404)


class TestOffboardingOverHttp:
    def test_offboarding_reports_each_action_and_what_is_pending(
        self, client, api, world, clock
    ):
        headers = _stepped_up(api, client, world["administrator"], world["acme"], clock)
        response = client.post(
            f"/v1/organizations/{world['acme']}/offboardings",
            headers=headers,
            json={"person_id": str(world["person"]), "reason": "left the company"},
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["state"] == "completed"
        assert body["pending_carrier"] == 0
        # Every kind is recorded, including the ones with nothing to do, so the
        # record answers "was their line suspended?" with "they had none".
        kinds = {action["kind"] for action in body["actions"]}
        assert "suspend_line" in kinds
        assert "revoke_membership" in kinds

    def test_offboarding_twice_returns_the_same_record(self, client, api, world, clock):
        headers = _stepped_up(api, client, world["administrator"], world["acme"], clock)
        first = client.post(
            f"/v1/organizations/{world['acme']}/offboardings",
            headers=headers,
            json={"person_id": str(world["person"])},
        )
        second = client.post(
            f"/v1/organizations/{world['acme']}/offboardings",
            headers=headers,
            json={"person_id": str(world["person"])},
        )

        assert first.json()["offboarding_id"] == second.json()["offboarding_id"]

    def test_another_organizations_person_is_not_found(self, client, api, world, clock):
        headers = _stepped_up(api, client, world["administrator"], world["acme"], clock)
        response = client.post(
            f"/v1/organizations/{world['acme']}/offboardings",
            headers=headers,
            json={"person_id": str(uuid4())},
        )
        assert response.status_code == 404
        assert response.json()["error"] == "person_not_found"

    def test_a_member_cannot_offboard_anybody(self, client, api, world):
        response = client.post(
            f"/v1/organizations/{world['acme']}/offboardings",
            headers=_auth(api, world["member"]),
            json={"person_id": str(world["person"])},
        )
        assert response.status_code == 403

    def test_the_history_lists_past_departures(self, client, api, world, clock):
        headers = _stepped_up(api, client, world["administrator"], world["acme"], clock)
        client.post(
            f"/v1/organizations/{world['acme']}/offboardings",
            headers=headers,
            json={"person_id": str(world["person"])},
        )

        listed = client.get(
            f"/v1/organizations/{world['acme']}/offboardings",
            headers=_auth(api, world["administrator"]),
        )

        assert listed.status_code == 200
        assert len(listed.json()["offboardings"]) == 1
