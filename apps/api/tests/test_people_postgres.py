"""Organization people and imports on real PostgreSQL — US-39, chunk 22.

Two strict-TDD categories apply: **tenant isolation** (`AGENTS.md` calls a
cross-tenant read a breach, not a bug) and **idempotency** (the same file
uploaded twice must not double an organization's staff). Both are database
guarantees here — three partial unique indexes and a digest index — so a SQLite
run would prove none of them.

The test this file exists for is
`test_importing_an_email_grants_no_access_at_all`. Everything else is the
supporting cast: the assignment's rule is that importing somebody must not make
them an administrator, and a chunk that got that wrong would hand an enterprise
customer's dashboard to two thousand people.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app import model_registry  # noqa: F401
from app.auth.models import Organization, OrganizationType, Platform, User
from app.csv_export import csv_safe
from app.organizations.models import (
    OrganizationMember,
)
from app.people.models import (
    ImportRowState,
    ImportState,
    OrganizationPerson,
    PeopleImport,
    PersonStatus,
)
from app.people.service import PeopleError, PeopleService

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="duplicate identity and tenant scope are database guarantees",
)

NOW = datetime(2026, 9, 13, 10, 0, tzinfo=timezone.utc)
TABLES = (
    "people_import_rows, people_imports, organization_people, "
    "organization_teams, organization_cost_centres, organization_members, "
    "organizations, users"
)


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: float) -> None:
        self.value += timedelta(**kwargs)


@pytest.fixture
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
def clock():
    return Clock()


@pytest.fixture
def service(clock):
    return PeopleService(clock=clock)


def _organization(session: Session, kind=OrganizationType.ENTERPRISE) -> Organization:
    organization = Organization(
        name=f"Org {uuid4().hex[:6]}",
        primary_contact_name="Contact",
        phone_number=f"+23490{uuid4().int % 10**8:08d}",
        email=f"org-{uuid4().hex[:8]}@example.test",
        password_hash="x",
        org_type=kind,
    )
    session.add(organization)
    session.flush()
    return organization


def _user(session: Session) -> User:
    user = User(
        phone_number=f"+23480{uuid4().int % 10**8:08d}",
        first_name="Admin",
        platform=Platform.ANDROID,
    )
    session.add(user)
    session.flush()
    return user


def csv_bytes(*lines: str) -> bytes:
    return "\r\n".join(lines).encode("utf-8")


class TestImportingGrantsNothing:
    def test_importing_an_email_grants_no_access_at_all(
        self, session, service, clock
    ):
        """The rule this chunk exists to hold.

        A file naming two colleagues produces two *recipients*. Neither becomes
        a member, neither can sign in to the dashboard, and there is no code
        path from an import to `organization_members` for a later chunk to
        find and use by accident.
        """
        organization = _organization(session)
        uploader = _user(session)
        record, _ = service.preview_import(
            session,
            organization.id,
            filename="staff.csv",
            content=csv_bytes(
                "Full Name,Email",
                "Ada Obi,ada@example.test",
                "Ben Musa,ben@example.test",
            ),
            uploaded_by_user_id=uploader.id,
        )
        service.apply_import(session, organization.id, record.id)

        assert len(service.people(session, organization.id)) == 2
        members = session.exec(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == organization.id
            )
        ).all()
        assert members == []

    def test_an_imported_person_is_not_bound_to_any_account(
        self, session, service
    ):
        """An imported email is a claim about somebody, not their account."""
        organization = _organization(session)
        existing_user = _user(session)
        existing_user.email = "ada@example.test"
        session.add(existing_user)
        session.flush()

        record, _ = service.preview_import(
            session,
            organization.id,
            filename="staff.csv",
            content=csv_bytes("Full Name,Email", "Ada Obi,ada@example.test"),
            uploaded_by_user_id=None,
        )
        service.apply_import(session, organization.id, record.id)

        person = service.people(session, organization.id)[0]
        assert person.user_id is None

    def test_a_government_organization_gets_no_extra_reach(
        self, session, service
    ):
        """Generalized as a category, not as a privilege.

        The assignment is explicit: government is an organization category
        *without* claims of certification or automatic additional data access.
        So the same import produces the same result and reads nothing further.
        """
        government = _organization(session, OrganizationType.GOVERNMENT)
        enterprise = _organization(session, OrganizationType.ENTERPRISE)
        for organization in (government, enterprise):
            record, _ = service.preview_import(
                session,
                organization.id,
                filename="staff.csv",
                content=csv_bytes("Full Name,Email", "Ada Obi,ada@example.test"),
                uploaded_by_user_id=None,
            )
            service.apply_import(session, organization.id, record.id)

        assert len(service.people(session, government.id)) == 1
        assert len(service.people(session, enterprise.id)) == 1
        # And neither can see the other's person.
        assert (
            service.people(session, government.id)[0].id
            != service.people(session, enterprise.id)[0].id
        )


class TestTenantScope:
    def test_one_organizations_person_does_not_exist_for_another(
        self, session, service
    ):
        first = _organization(session)
        second = _organization(session)
        record, _ = service.preview_import(
            session,
            first.id,
            filename="staff.csv",
            content=csv_bytes("Full Name,Email", "Ada Obi,ada@example.test"),
            uploaded_by_user_id=None,
        )
        service.apply_import(session, first.id, record.id)
        person = service.people(session, first.id)[0]

        with pytest.raises(PeopleError) as excinfo:
            service.person(session, second.id, person.id)
        assert excinfo.value.code == "person_not_found"

    def test_another_organizations_import_cannot_be_applied(
        self, session, service
    ):
        first = _organization(session)
        second = _organization(session)
        record, _ = service.preview_import(
            session,
            first.id,
            filename="staff.csv",
            content=csv_bytes("Full Name,Email", "Ada Obi,ada@example.test"),
            uploaded_by_user_id=None,
        )

        with pytest.raises(PeopleError) as excinfo:
            service.apply_import(session, second.id, record.id)
        assert excinfo.value.code == "import_not_found"

    def test_two_organizations_may_employ_the_same_contractor(
        self, session, service
    ):
        """The uniqueness is per organization. Neither customer blocks the other."""
        first = _organization(session)
        second = _organization(session)
        for organization in (first, second):
            record, _ = service.preview_import(
                session,
                organization.id,
                filename="staff.csv",
                content=csv_bytes(
                    "Full Name,Email", "Ada Obi,contractor@example.test"
                ),
                uploaded_by_user_id=None,
            )
            service.apply_import(session, organization.id, record.id)

        assert len(service.people(session, first.id)) == 1
        assert len(service.people(session, second.id)) == 1

    def test_a_team_from_another_organization_cannot_be_attached(
        self, session, service
    ):
        first = _organization(session)
        second = _organization(session)
        centre = service.create_cost_centre(
            session, first.id, code="CC-1", name="Operations"
        )

        with pytest.raises(PeopleError) as excinfo:
            service.create_team(
                session, second.id, name="Field", cost_centre_id=centre.id
            )
        assert excinfo.value.code == "cost_centre_not_found"


class TestDuplicateAndReplayedImports:
    def test_the_same_file_twice_returns_the_same_import(self, session, service):
        organization = _organization(session)
        content = csv_bytes("Full Name,Email", "Ada Obi,ada@example.test")
        first, _ = service.preview_import(
            session,
            organization.id,
            filename="staff.csv",
            content=content,
            uploaded_by_user_id=None,
        )
        second, parsed = service.preview_import(
            session,
            organization.id,
            filename="staff-again.csv",
            content=content,
            uploaded_by_user_id=None,
        )
        assert first.id == second.id
        assert parsed is None

    def test_concurrent_uploads_of_the_same_file_converge(
        self, session, engine, service
    ):
        organization = _organization(session)
        organization_id = organization.id
        session.commit()
        content = csv_bytes("Full Name,Email", "Ada Obi,ada@example.test")

        def upload() -> UUID:
            with Session(engine) as concurrent_session:
                record, _ = service.preview_import(
                    concurrent_session,
                    organization_id,
                    filename="staff.csv",
                    content=content,
                    uploaded_by_user_id=None,
                )
                record_id = record.id
                concurrent_session.commit()
                return record_id

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.map(lambda _: upload(), range(2))

        assert first == second

    def test_applying_the_same_import_twice_does_not_double_the_staff(
        self, session, service
    ):
        organization = _organization(session)
        record, _ = service.preview_import(
            session,
            organization.id,
            filename="staff.csv",
            content=csv_bytes(
                "Full Name,Email",
                "Ada Obi,ada@example.test",
                "Ben Musa,ben@example.test",
            ),
            uploaded_by_user_id=None,
        )
        service.apply_import(session, organization.id, record.id)
        summary = service.apply_import(session, organization.id, record.id)

        assert len(service.people(session, organization.id)) == 2
        assert summary.created_count == 2

    def test_a_corrected_file_updates_rather_than_duplicating(
        self, session, service
    ):
        """The second upload is a different file — and the same people."""
        organization = _organization(session)
        first, _ = service.preview_import(
            session,
            organization.id,
            filename="staff.csv",
            content=csv_bytes(
                "Full Name,Employee ID,Email",
                "Ada Obi,E-1,ada@example.test",
            ),
            uploaded_by_user_id=None,
        )
        service.apply_import(session, organization.id, first.id)

        second, _ = service.preview_import(
            session,
            organization.id,
            filename="staff-v2.csv",
            content=csv_bytes(
                "Full Name,Employee ID,Email",
                "Ada Obi-Musa,E-1,ada@example.test",
            ),
            uploaded_by_user_id=None,
        )
        summary = service.apply_import(session, organization.id, second.id)

        people = service.people(session, organization.id)
        assert len(people) == 1
        assert people[0].full_name == "Ada Obi-Musa"
        assert summary.updated_count == 1
        assert summary.created_count == 0

    def test_the_database_refuses_a_duplicate_even_if_code_asks(
        self, session, service
    ):
        """The index is the last line, and it is tested as one."""
        organization = _organization(session)
        session.add(
            OrganizationPerson(
                organization_id=organization.id,
                full_name="Ada Obi",
                email="ada@example.test",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()
        session.add(
            OrganizationPerson(
                organization_id=organization.id,
                full_name="Somebody Else",
                email="ada@example.test",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    def test_a_person_with_nothing_to_identify_them_is_refused(
        self, session, service
    ):
        organization = _organization(session)
        session.add(
            OrganizationPerson(
                organization_id=organization.id,
                full_name="Nobody",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


class TestPreviewThenApply:
    def test_a_preview_writes_no_people(self, session, service):
        organization = _organization(session)
        service.preview_import(
            session,
            organization.id,
            filename="staff.csv",
            content=csv_bytes("Full Name,Email", "Ada Obi,ada@example.test"),
            uploaded_by_user_id=None,
        )
        assert service.people(session, organization.id) == []

    def test_the_preview_counts_what_the_apply_then_does(self, session, service):
        organization = _organization(session)
        record, _ = service.preview_import(
            session,
            organization.id,
            filename="staff.csv",
            content=csv_bytes(
                "Full Name,Email",
                "Ada Obi,ada@example.test",
                ",broken@example.test",
                "Ben Musa,not-an-email",
            ),
            uploaded_by_user_id=None,
        )
        assert record.valid_count == 1
        assert record.invalid_count == 2

        summary = service.apply_import(session, organization.id, record.id)
        assert summary.created_count == record.valid_count

    def test_the_preview_distinguishes_creates_from_updates(self, session, service):
        organization = _organization(session)
        session.add(
            OrganizationPerson(
                organization_id=organization.id,
                full_name="Ada Obi",
                email="ada@example.test",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()

        record, _ = service.preview_import(
            session,
            organization.id,
            filename="staff.csv",
            content=csv_bytes(
                "Full Name,Email",
                "Ada Obi-Musa,ada@example.test",
                "Ben Musa,ben@example.test",
            ),
            uploaded_by_user_id=None,
        )

        assert record.created_count == 1
        assert record.updated_count == 1

    def test_a_row_that_resolves_to_two_people_is_invalid(self, session, service):
        organization = _organization(session)
        session.add_all(
            [
                OrganizationPerson(
                    organization_id=organization.id,
                    full_name="Ada Obi",
                    email="ada@example.test",
                    external_reference="E-1",
                    created_at=NOW,
                    updated_at=NOW,
                ),
                OrganizationPerson(
                    organization_id=organization.id,
                    full_name="Ben Musa",
                    email="ben@example.test",
                    external_reference="E-2",
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
        )
        session.flush()

        record, _ = service.preview_import(
            session,
            organization.id,
            filename="staff.csv",
            content=csv_bytes(
                "Full Name,Employee ID,Email",
                "Wrong Merge,E-1,ben@example.test",
            ),
            uploaded_by_user_id=None,
        )
        rows = service.import_rows(session, organization.id, record.id)

        assert record.valid_count == 0
        assert record.invalid_count == 1
        assert rows[0].state is ImportRowState.INVALID
        assert rows[0].error_codes == ["identity_collision"]

    def test_invalid_rows_keep_their_reasons_for_the_administrator(
        self, session, service
    ):
        organization = _organization(session)
        record, _ = service.preview_import(
            session,
            organization.id,
            filename="staff.csv",
            content=csv_bytes("Full Name,Email,Phone", ",bad,12345"),
            uploaded_by_user_id=None,
        )
        rows = service.import_rows(
            session, organization.id, record.id, only_invalid=True
        )
        assert len(rows) == 1
        assert rows[0].row_number == 2
        assert set(rows[0].error_codes) >= {
            "missing_name",
            "invalid_email",
            "invalid_phone",
        }

    def test_a_cancelled_import_applies_nothing_and_frees_the_file(
        self, session, service
    ):
        organization = _organization(session)
        content = csv_bytes("Full Name,Email", "Ada Obi,ada@example.test")
        record, _ = service.preview_import(
            session,
            organization.id,
            filename="staff.csv",
            content=content,
            uploaded_by_user_id=None,
        )
        service.cancel_import(session, organization.id, record.id)

        with pytest.raises(PeopleError) as excinfo:
            service.apply_import(session, organization.id, record.id)
        assert excinfo.value.code == "import_not_applicable"

        # Cancelled means the administrator may upload the same file again.
        again, parsed = service.preview_import(
            session,
            organization.id,
            filename="staff.csv",
            content=content,
            uploaded_by_user_id=None,
        )
        assert again.id != record.id
        assert parsed is not None

    def test_an_unreadable_file_is_recorded_rather_than_thrown_away(
        self, session, service
    ):
        """An administrator needs to know *why* their upload did nothing."""
        organization = _organization(session)
        record, parsed = service.preview_import(
            session,
            organization.id,
            filename="notes.txt",
            content=csv_bytes("Email,Phone", "ada@example.test,+2348031234567"),
            uploaded_by_user_id=None,
        )
        assert record.state is ImportState.REJECTED
        assert record.rejection_code == "no_identifying_column"
        assert parsed is None

    def test_an_apply_interrupted_halfway_resumes_after_a_new_session(
        self, session, engine, service, monkeypatch
    ):
        """Committed row outcomes survive the process transaction that dies."""
        organization = _organization(session)
        organization_id = organization.id
        record, _ = service.preview_import(
            session,
            organization.id,
            filename="staff.csv",
            content=csv_bytes(
                "Full Name,Email",
                "Ada Obi,ada@example.test",
                "Ben Musa,ben@example.test",
                "Chi Eze,chi@example.test",
            ),
            uploaded_by_user_id=None,
        )
        import_id = record.id
        original = service._upsert_person
        calls = 0

        def crash_on_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated process death")
            return original(*args, **kwargs)

        monkeypatch.setattr(service, "_upsert_person", crash_on_second)
        with pytest.raises(RuntimeError, match="simulated process death"):
            service.apply_import(session, organization_id, import_id)
        session.rollback()

        with Session(engine) as resumed_session:
            interrupted = resumed_session.get(PeopleImport, import_id)
            assert interrupted is not None
            assert interrupted.state is ImportState.APPLYING
            assert interrupted.created_count == 1

            summary = service.apply_import(
                resumed_session, organization_id, import_id
            )
            assert len(service.people(resumed_session, organization_id)) == 3
            assert summary.created_count == 3
            assert summary.state is ImportState.APPLIED


class TestTeamsAndCostCentres:
    def test_a_person_inherits_their_teams_cost_centre(self, session, service):
        organization = _organization(session)
        centre = service.create_cost_centre(
            session, organization.id, code="CC-1", name="Operations"
        )
        service.create_team(
            session, organization.id, name="Field", cost_centre_id=centre.id
        )
        record, _ = service.preview_import(
            session,
            organization.id,
            filename="staff.csv",
            content=csv_bytes(
                "Full Name,Email,Department", "Ada Obi,ada@example.test,Field"
            ),
            uploaded_by_user_id=None,
        )
        service.apply_import(session, organization.id, record.id)

        person = service.people(session, organization.id)[0]
        assert person.cost_centre_id == centre.id

    def test_a_person_billed_elsewhere_keeps_their_own_cost_centre(
        self, session, service
    ):
        """A secondment is not a reorganization."""
        organization = _organization(session)
        team_centre = service.create_cost_centre(
            session, organization.id, code="CC-1", name="Operations"
        )
        other_centre = service.create_cost_centre(
            session, organization.id, code="CC-2", name="Projects"
        )
        service.create_team(
            session, organization.id, name="Field", cost_centre_id=team_centre.id
        )
        record, _ = service.preview_import(
            session,
            organization.id,
            filename="staff.csv",
            content=csv_bytes(
                "Full Name,Email,Department,Cost Code",
                "Ada Obi,ada@example.test,Field,CC-2",
            ),
            uploaded_by_user_id=None,
        )
        service.apply_import(session, organization.id, record.id)

        assert service.people(session, organization.id)[0].cost_centre_id == (
            other_centre.id
        )

    def test_a_duplicate_cost_centre_code_is_refused(self, session, service):
        organization = _organization(session)
        service.create_cost_centre(
            session, organization.id, code="CC-1", name="Operations"
        )
        with pytest.raises(PeopleError) as excinfo:
            service.create_cost_centre(
                session, organization.id, code="CC-1", name="Something else"
            )
        assert excinfo.value.code == "cost_centre_exists"

    def test_a_team_name_is_unique_however_it_is_cased(self, session, service):
        organization = _organization(session)
        service.create_team(session, organization.id, name="Field")
        with pytest.raises(PeopleError) as excinfo:
            service.create_team(session, organization.id, name="field")
        assert excinfo.value.code == "team_exists"


class TestLeaving:
    def test_archiving_keeps_the_person_and_their_history(self, session, service):
        organization = _organization(session)
        record, _ = service.preview_import(
            session,
            organization.id,
            filename="staff.csv",
            content=csv_bytes("Full Name,Email", "Ada Obi,ada@example.test"),
            uploaded_by_user_id=None,
        )
        service.apply_import(session, organization.id, record.id)
        person = service.people(session, organization.id)[0]

        service.archive_person(session, organization.id, person.id)

        assert service.people(session, organization.id) == []
        kept = service.person(session, organization.id, person.id)
        assert kept.status is PersonStatus.ARCHIVED
        assert kept.archived_at is not None


class TestExportsAreSafeToOpen:
    def test_the_supported_import_size_is_not_truncated_on_read(
        self, session, service
    ):
        organization = _organization(session)
        session.add_all(
            [
                OrganizationPerson(
                    organization_id=organization.id,
                    full_name=f"Person {index:03d}",
                    external_reference=f"E-{index:03d}",
                    created_at=NOW,
                    updated_at=NOW,
                )
                for index in range(501)
            ]
        )
        session.flush()

        assert len(service.people(session, organization.id)) == 501

    def test_a_formula_in_a_name_is_defused_on_the_way_out(self):
        """The name imported as written; the export is where it is neutralised."""
        assert csv_safe('=HYPERLINK("http://x","click")').startswith("'=")
        assert csv_safe("+1").startswith("'+")
        assert csv_safe("-1").startswith("'-")
        assert csv_safe("@SUM(A1)").startswith("'@")

    def test_an_ordinary_name_is_untouched(self):
        assert csv_safe("Ada Obi") == "Ada Obi"

    def test_a_newline_cannot_split_one_person_into_two_rows(self):
        assert "\n" not in csv_safe("Ada\nObi")

    def test_defusing_is_not_applied_twice(self):
        once = csv_safe("=Ada")
        assert csv_safe(once) == once
