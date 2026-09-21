"""US-39 chunk 22 — organization people over HTTP.

The service suite proves the rules; this proves the routes apply them. Three
properties, and each is an acceptance criterion rather than a nicety:

**Billing and member roles cannot perform administrator actions.** The matrix
grants `PEOPLE_READ`/`PEOPLE_MANAGE` to owners and administrators only, and the
test below walks every people route with a billing session to prove no handler
forgot to ask.

**Tenant scope holds in downloads and bulk selections.** A CSV export is the
easiest place to leak a whole customer's staff list, because it is the one
response nobody reads before shipping.

**An import grants nothing.** A file naming colleagues produces recipients, and
the members list is still empty afterwards.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.auth.models import Locale, Organization, OrganizationType, Platform, User
from app.organizations.models import OrganizationMember, OrganizationRole
from app.organizations.service import MembershipService

NOW = datetime(2026, 9, 13, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def client(api):
    return TestClient(api, raise_server_exceptions=False)


def _user(session: Session, label: str) -> UUID:
    user = User(
        phone_number=f"+23484{abs(hash(label)) % 10**8:08d}",
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
    """One organization with every role, plus a second organization's owner."""
    memberships = MembershipService(clock=clock)
    with session_factory() as session:
        acme = _organization(session, "Acme")
        other = _organization(session, "Other")
        people = {
            role.value: _user(session, f"acme-{role.value}")
            for role in OrganizationRole
        }
        other_owner = _user(session, "other-owner")
        for role in OrganizationRole:
            memberships.seed_member(
                session,
                acme,
                session.get(User, people[role.value]),
                role,
            )
        memberships.seed_member(
            session, other, session.get(User, other_owner), OrganizationRole.OWNER
        )
        session.commit()
        return {
            "acme": acme.id,
            "other": other.id,
            "other_owner": other_owner,
            **people,
        }


def _upload(client, api, world, user_key, content: bytes, filename="staff.csv"):
    return client.post(
        f"/v1/organizations/{world['acme']}/people/imports",
        headers=_auth(api, world[user_key]),
        files={"file": (filename, content, "text/csv")},
    )


CSV = b"Full Name,Email\r\nAda Obi,ada@example.test\r\nBen Musa,ben@example.test\r\n"


class TestOnlyAdministratorsReachPeople:
    @pytest.mark.parametrize("role", ["billing", "member"])
    @pytest.mark.parametrize(
        ("method", "suffix"),
        [
            ("get", "/people"),
            ("get", "/teams"),
            ("get", "/cost-centres"),
            ("get", "/people/imports"),
            ("get", "/people.csv"),
        ],
    )
    def test_a_billing_or_member_session_reads_nothing(
        self, client, api, world, role, method, suffix
    ):
        """The acceptance criterion, walked route by route."""
        response = getattr(client, method)(
            f"/v1/organizations/{world['acme']}{suffix}",
            headers=_auth(api, world[role]),
        )
        assert response.status_code == 403, f"{suffix} answered {response.status_code}"

    @pytest.mark.parametrize("role", ["billing", "member"])
    def test_a_billing_or_member_session_cannot_import(
        self, client, api, world, role
    ):
        response = _upload(client, api, world, role, CSV)
        assert response.status_code == 403

    @pytest.mark.parametrize("role", ["billing", "member"])
    def test_a_billing_or_member_session_cannot_create_a_team(
        self, client, api, world, role
    ):
        response = client.post(
            f"/v1/organizations/{world['acme']}/teams",
            headers=_auth(api, world[role]),
            json={"name": "Field"},
        )
        assert response.status_code == 403

    def test_an_administrator_may_do_all_of_it(self, client, api, world):
        assert (
            client.get(
                f"/v1/organizations/{world['acme']}/people",
                headers=_auth(api, world["administrator"]),
            ).status_code
            == 200
        )
        assert _upload(client, api, world, "administrator", CSV).status_code == 201


class TestTenantScope:
    def test_another_organizations_people_are_refused(self, client, api, world):
        """A valid session for one organization, asking about another by id."""
        response = client.get(
            f"/v1/organizations/{world['other']}/people",
            headers=_auth(api, world["owner"]),
        )
        assert response.status_code in (403, 404)

    def test_the_export_cannot_be_pointed_at_another_organization(
        self, client, api, world
    ):
        """The easiest place to leak a whole staff list is the one nobody reads."""
        response = client.get(
            f"/v1/organizations/{world['other']}/people.csv",
            headers=_auth(api, world["owner"]),
        )
        assert response.status_code in (403, 404)

    def test_an_import_id_from_another_organization_is_not_found(
        self, client, api, world
    ):
        created = _upload(client, api, world, "owner", CSV)
        import_id = created.json()["summary"]["import_id"]

        response = client.post(
            f"/v1/organizations/{world['other']}/people/imports/{import_id}/apply",
            headers=_auth(api, world["other_owner"]),
        )
        assert response.status_code == 404


class TestImportOverHttp:
    def test_a_preview_reports_what_would_happen_and_writes_nobody(
        self, client, api, world
    ):
        response = _upload(client, api, world, "owner", CSV)

        assert response.status_code == 201
        summary = response.json()["summary"]
        assert summary["row_count"] == 2
        assert summary["valid_count"] == 2
        assert summary["state"] == "previewed"

        listed = client.get(
            f"/v1/organizations/{world['acme']}/people",
            headers=_auth(api, world["owner"]),
        )
        assert listed.json()["people"] == []

    def test_applying_creates_the_people_and_no_members(self, client, api, world):
        """The rule this chunk exists for, proved through the routes."""
        created = _upload(client, api, world, "owner", CSV)
        import_id = created.json()["summary"]["import_id"]

        applied = client.post(
            f"/v1/organizations/{world['acme']}/people/imports/{import_id}/apply",
            headers=_auth(api, world["owner"]),
        )
        assert applied.status_code == 200
        assert applied.json()["created_count"] == 2

        people = client.get(
            f"/v1/organizations/{world['acme']}/people",
            headers=_auth(api, world["owner"]),
        ).json()["people"]
        assert len(people) == 2
        assert all(person["has_account"] is False for person in people)

        with api.state.session_factory() as session:
            members = session.exec(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == world["acme"]
                )
            ).all()
        # The four seeded roles, and not one more.
        assert len(members) == len(list(OrganizationRole))

    def test_a_rejected_file_says_why_rather_than_failing_silently(
        self, client, api, world
    ):
        response = _upload(
            client, api, world, "owner", b"Email\r\nada@example.test\r\n"
        )
        assert response.status_code == 201
        summary = response.json()["summary"]
        assert summary["state"] == "rejected"
        assert summary["rejection_code"] == "no_identifying_column"

    def test_invalid_rows_are_listed_with_every_reason(self, client, api, world):
        created = _upload(
            client,
            api,
            world,
            "owner",
            b"Full Name,Email,Phone\r\n,bad,12345\r\n",
        )
        import_id = created.json()["summary"]["import_id"]

        rows = client.get(
            f"/v1/organizations/{world['acme']}/people/imports/{import_id}/rows"
            "?only_invalid=true",
            headers=_auth(api, world["owner"]),
        ).json()["rows"]

        assert len(rows) == 1
        assert set(rows[0]["error_codes"]) >= {
            "missing_name",
            "invalid_email",
            "invalid_phone",
        }

    def test_the_imports_path_is_not_swallowed_by_the_person_route(
        self, client, api, world
    ):
        """`/people/imports` must not be parsed as `/people/{person_id}`.

        Declaration order is the only thing that decides this, and getting it
        wrong produces a 422 on a route that exists — a bug that survives review
        because the handler it should have reached looks correct.
        """
        response = client.get(
            f"/v1/organizations/{world['acme']}/people/imports",
            headers=_auth(api, world["owner"]),
        )
        assert response.status_code == 200
        assert "imports" in response.json()


class TestExport:
    def test_a_formula_in_an_imported_name_is_defused_in_the_download(
        self, client, api, world
    ):
        """Imported as written, neutralised on the way out."""
        hostile = (
            b"Full Name,Email\r\n"
            b'=HYPERLINK("http://x"),ada@example.test\r\n'
        )
        created = _upload(client, api, world, "owner", hostile)
        import_id = created.json()["summary"]["import_id"]
        client.post(
            f"/v1/organizations/{world['acme']}/people/imports/{import_id}/apply",
            headers=_auth(api, world["owner"]),
        )

        download = client.get(
            f"/v1/organizations/{world['acme']}/people.csv",
            headers=_auth(api, world["owner"]),
        )

        assert download.status_code == 200
        assert download.headers["content-type"].startswith("text/csv")
        assert '"\'=HYPERLINK' in download.text or "'=HYPERLINK" in download.text
        assert not any(
            line.startswith("=HYPERLINK") for line in download.text.splitlines()
        )
