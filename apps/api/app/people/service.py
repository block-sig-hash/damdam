"""People, teams, cost centres and the import that fills them (US-39, chunk 22).

Every method takes an `organization_id` and puts it in the query. Not as a
check after the fetch — in the query — because `AGENTS.md` calls a cross-tenant
read a breach rather than a bug, and the difference between the two styles is
one forgotten `if` on a Friday.

## The import is three separate acts

`preview` parses and records, and writes **nothing** to `organization_people`.
`apply` turns a recorded preview into people. `cancel` closes it. Splitting them
is what makes a preview worth showing: an administrator looking at "412 new, 18
updated, 6 errors" is looking at what *will* happen, computed by the same code
that will do it, not at an estimate.

An apply is resumable by construction. Each row records its own outcome as it is
applied, so a process that dies halfway leaves an import in `APPLYING` whose rows
say exactly which people already exist. Re-running it skips them — it matches on
the same natural keys the database enforces — rather than creating a second Ada
Obi.

## What an import cannot do

It cannot grant access. There is no path from this module to
`organization_members`, and the format has no column that would feed one. An
organization importing two thousand staff creates two thousand **recipients**
and zero administrators; access is an invitation, which is a different table, a
different endpoint and a different permission.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.auth.models import utc_now
from app.people.importing import FileRejected, ParsedFile, ParsedRow, RowError, parse
from app.people.models import (
    ImportRowState,
    ImportState,
    OrganizationCostCentre,
    OrganizationPerson,
    OrganizationTeam,
    PeopleImport,
    PeopleImportRow,
    PersonStatus,
)


class PeopleError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ImportSummary:
    """What an import did, or would do. Same shape before and after."""

    import_id: UUID
    state: ImportState
    row_count: int
    valid_count: int
    invalid_count: int
    created_count: int
    updated_count: int


class PeopleService:
    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self.clock = clock

    # --- teams and cost centres -------------------------------------------

    def create_cost_centre(
        self, session: Session, organization_id: UUID, *, code: str, name: str
    ) -> OrganizationCostCentre:
        code = code.strip()
        if not code:
            raise PeopleError("cost_centre_code_required")
        existing = session.exec(
            select(OrganizationCostCentre).where(
                OrganizationCostCentre.organization_id == organization_id,
                OrganizationCostCentre.code == code,
            )
        ).first()
        if existing is not None:
            raise PeopleError("cost_centre_exists")
        centre = OrganizationCostCentre(
            organization_id=organization_id,
            code=code,
            name=name.strip(),
            created_at=self.clock(),
        )
        session.add(centre)
        session.flush()
        return centre

    def cost_centres(
        self, session: Session, organization_id: UUID, *, include_archived: bool = False
    ) -> Sequence[OrganizationCostCentre]:
        statement = select(OrganizationCostCentre).where(
            OrganizationCostCentre.organization_id == organization_id
        )
        if not include_archived:
            statement = statement.where(
                col(OrganizationCostCentre.archived_at).is_(None)
            )
        return session.exec(statement.order_by(col(OrganizationCostCentre.code))).all()

    def create_team(
        self,
        session: Session,
        organization_id: UUID,
        *,
        name: str,
        cost_centre_id: UUID | None = None,
    ) -> OrganizationTeam:
        name = name.strip()
        if not name:
            raise PeopleError("team_name_required")
        existing = session.exec(
            select(OrganizationTeam).where(
                OrganizationTeam.organization_id == organization_id,
                func.lower(col(OrganizationTeam.name)) == name.lower(),
            )
        ).first()
        if existing is not None:
            raise PeopleError("team_exists")
        if cost_centre_id is not None:
            self._own_cost_centre(session, organization_id, cost_centre_id)
        team = OrganizationTeam(
            organization_id=organization_id,
            name=name,
            cost_centre_id=cost_centre_id,
            created_at=self.clock(),
        )
        session.add(team)
        session.flush()
        return team

    def teams(
        self, session: Session, organization_id: UUID, *, include_archived: bool = False
    ) -> Sequence[OrganizationTeam]:
        statement = select(OrganizationTeam).where(
            OrganizationTeam.organization_id == organization_id
        )
        if not include_archived:
            statement = statement.where(col(OrganizationTeam.archived_at).is_(None))
        return session.exec(statement.order_by(col(OrganizationTeam.name))).all()

    # --- people ------------------------------------------------------------

    def people(
        self,
        session: Session,
        organization_id: UUID,
        *,
        team_id: UUID | None = None,
        include_archived: bool = False,
        limit: int = 5_000,
    ) -> Sequence[OrganizationPerson]:
        statement = select(OrganizationPerson).where(
            OrganizationPerson.organization_id == organization_id
        )
        if team_id is not None:
            statement = statement.where(OrganizationPerson.team_id == team_id)
        if not include_archived:
            statement = statement.where(
                OrganizationPerson.status == PersonStatus.ACTIVE
            )
        return session.exec(
            statement.order_by(col(OrganizationPerson.full_name)).limit(limit)
        ).all()

    def person(
        self, session: Session, organization_id: UUID, person_id: UUID
    ) -> OrganizationPerson:
        """Scoped by construction. Somebody else's person does not exist."""
        found = session.exec(
            select(OrganizationPerson).where(
                OrganizationPerson.id == person_id,
                OrganizationPerson.organization_id == organization_id,
            )
        ).first()
        if found is None:
            raise PeopleError("person_not_found")
        return found

    def archive_person(
        self, session: Session, organization_id: UUID, person_id: UUID
    ) -> OrganizationPerson:
        """Leaving is a status change. Their orders still name them."""
        person = self.person(session, organization_id, person_id)
        if person.status is PersonStatus.ARCHIVED:
            return person
        now = self.clock()
        person.status = PersonStatus.ARCHIVED
        person.archived_at = now
        person.updated_at = now
        session.add(person)
        session.flush()
        return person

    # --- import ------------------------------------------------------------

    def preview_import(
        self,
        session: Session,
        organization_id: UUID,
        *,
        filename: str,
        content: bytes,
        uploaded_by_user_id: UUID | None,
    ) -> tuple[PeopleImport, ParsedFile | None]:
        """Parse, record and report. Writes no people.

        Re-uploading the same bytes returns the import that already exists —
        an administrator who lost the response, or clicked twice, gets their
        preview rather than a second one to choose between.
        """
        digest = hashlib.sha256(content).hexdigest()
        bind = session.get_bind()
        if bind.dialect.name == "postgresql":
            # Serialize the read-then-insert behind the partial unique index.
            # The index is still the invariant; this makes two identical live
            # uploads converge on one response instead of making one a 500.
            session.execute(
                select(
                    func.pg_advisory_xact_lock(
                        func.hashtextextended(f"{organization_id}:{digest}", 0)
                    )
                )
            )
        existing_import = session.exec(
            select(PeopleImport).where(
                PeopleImport.organization_id == organization_id,
                PeopleImport.content_digest == digest,
                PeopleImport.state != ImportState.CANCELLED,
            )
        ).first()
        if existing_import is not None:
            return existing_import, None

        teams = [team.name for team in self.teams(session, organization_id)]
        centres = [
            centre.code for centre in self.cost_centres(session, organization_id)
        ]
        try:
            parsed = parse(
                content, known_teams=teams, known_cost_centres=centres
            )
        except FileRejected as rejection:
            record = PeopleImport(
                organization_id=organization_id,
                uploaded_by_user_id=uploaded_by_user_id,
                filename=filename[:255],
                content_digest=digest,
                state=ImportState.REJECTED,
                row_count=0,
                rejection_code=rejection.code.value,
                created_at=self.clock(),
            )
            session.add(record)
            session.flush()
            return record, None

        created_count = 0
        updated_count = 0
        for row in parsed.valid_rows:
            try:
                existing_person = self._matching_person(
                    session, organization_id, _payload_of(row)
                )
            except PeopleError as exc:
                if exc.code != "identity_collision":
                    raise
                row.errors.append(RowError.IDENTITY_COLLISION)
                continue
            if existing_person is None:
                created_count += 1
            else:
                updated_count += 1

        record = PeopleImport(
            organization_id=organization_id,
            uploaded_by_user_id=uploaded_by_user_id,
            filename=filename[:255],
            content_digest=digest,
            state=ImportState.PREVIEWED,
            row_count=len(parsed.rows),
            valid_count=len(parsed.valid_rows),
            invalid_count=len(parsed.invalid_rows),
            created_count=created_count,
            updated_count=updated_count,
            created_at=self.clock(),
        )
        session.add(record)
        session.flush()
        for row in parsed.rows:
            session.add(
                PeopleImportRow(
                    import_id=record.id,
                    row_number=row.row_number,
                    state=(
                        ImportRowState.VALID if row.is_valid else ImportRowState.INVALID
                    ),
                    payload=_payload_of(row),
                    error_codes=[error.value for error in row.errors],
                )
            )
        session.flush()
        return record, parsed

    def apply_import(
        self, session: Session, organization_id: UUID, import_id: UUID
    ) -> ImportSummary:
        """Apply one durable row transaction at a time.

        Locking the import row serializes competing callers. Each person, row
        outcome and counter update commits together before the next row starts,
        so a process death loses at most the current row and a later call can
        continue from the remaining `VALID` rows.
        """

        teams = {
            team.name.casefold(): team
            for team in self.teams(session, organization_id)
        }
        centres = {
            centre.code.casefold(): centre
            for centre in self.cost_centres(session, organization_id)
        }

        while True:
            session.expire_all()
            record = session.exec(
                select(PeopleImport)
                .where(
                    PeopleImport.id == import_id,
                    PeopleImport.organization_id == organization_id,
                )
                .with_for_update()
            ).first()
            if record is None:
                raise PeopleError("import_not_found")
            if record.state is ImportState.APPLIED:
                return _summary(record)
            if record.state in {ImportState.CANCELLED, ImportState.REJECTED}:
                raise PeopleError("import_not_applicable")

            if record.state is ImportState.PREVIEWED:
                # Preview counts are a forecast. Once apply starts these fields
                # become the durable count of committed outcomes.
                record.state = ImportState.APPLYING
                record.created_count = 0
                record.updated_count = 0
                session.add(record)
                session.commit()
                continue

            row = session.exec(
                select(PeopleImportRow)
                .where(
                    PeopleImportRow.import_id == record.id,
                    PeopleImportRow.state == ImportRowState.VALID,
                )
                .order_by(col(PeopleImportRow.row_number))
                .limit(1)
            ).first()
            if row is None:
                record.state = ImportState.APPLIED
                record.applied_at = self.clock()
                session.add(record)
                summary = _summary(record)
                session.commit()
                return summary

            try:
                person, was_created = self._upsert_person(
                    session, organization_id, row.payload, teams, centres
                )
            except PeopleError as exc:
                if exc.code != "identity_collision":
                    session.rollback()
                    raise
                row.state = ImportRowState.INVALID
                row.error_codes = [*row.error_codes, RowError.IDENTITY_COLLISION.value]
                record.valid_count -= 1
                record.invalid_count += 1
            else:
                row.person_id = person.id
                row.state = (
                    ImportRowState.CREATED
                    if was_created
                    else ImportRowState.UPDATED
                )
                record.created_count += 1 if was_created else 0
                record.updated_count += 0 if was_created else 1
            session.add(row)
            session.add(record)
            session.commit()

    def cancel_import(
        self, session: Session, organization_id: UUID, import_id: UUID
    ) -> PeopleImport:
        record = self._own_import(session, organization_id, import_id)
        if record.state is ImportState.APPLIED:
            raise PeopleError("import_already_applied")
        record.state = ImportState.CANCELLED
        session.add(record)
        session.flush()
        return record

    def import_rows(
        self,
        session: Session,
        organization_id: UUID,
        import_id: UUID,
        *,
        only_invalid: bool = False,
        limit: int = 5_000,
    ) -> Sequence[PeopleImportRow]:
        self._own_import(session, organization_id, import_id)
        statement = select(PeopleImportRow).where(
            PeopleImportRow.import_id == import_id
        )
        if only_invalid:
            statement = statement.where(
                PeopleImportRow.state == ImportRowState.INVALID
            )
        return session.exec(
            statement.order_by(col(PeopleImportRow.row_number)).limit(limit)
        ).all()

    # --- internals ---------------------------------------------------------

    def _matching_person(
        self,
        session: Session,
        organization_id: UUID,
        payload: dict[str, object],
    ) -> OrganizationPerson | None:
        """Resolve every supplied identity, refusing a split identity.

        Priority ordering is unsafe here: if an employee reference belongs to
        Ada while the email belongs to Ben, choosing the first silently merges
        Ben into Ada and then collides at flush. The row is invalid instead.
        """
        matches: dict[UUID, OrganizationPerson] = {}
        for field_name, value in (
            ("external_reference", _text(payload.get("external_reference"))),
            ("email", _text(payload.get("email"))),
            ("phone_number", _text(payload.get("phone_number"))),
        ):
            if not value:
                continue
            existing = session.exec(
                select(OrganizationPerson).where(
                    OrganizationPerson.organization_id == organization_id,
                    getattr(OrganizationPerson, field_name) == value,
                )
            ).first()
            if existing is not None:
                matches[existing.id] = existing
        if len(matches) > 1:
            raise PeopleError("identity_collision")
        return next(iter(matches.values()), None)

    def _upsert_person(
        self,
        session: Session,
        organization_id: UUID,
        payload: dict[str, object],
        teams: dict[str, OrganizationTeam],
        centres: dict[str, OrganizationCostCentre],
    ) -> tuple[OrganizationPerson, bool]:
        """Match on every key the database enforces, or create one person."""
        email = _text(payload.get("email"))
        phone = _text(payload.get("phone_number"))
        reference = _text(payload.get("external_reference"))

        existing = self._matching_person(session, organization_id, payload)

        team = teams.get((_text(payload.get("team")) or "").casefold())
        centre = centres.get((_text(payload.get("cost_centre")) or "").casefold())
        if centre is None and team is not None:
            # A team's cost centre is the default for its people. A person
            # billed elsewhere says so on their own row.
            centre_id = team.cost_centre_id
        else:
            centre_id = centre.id if centre else None

        now = self.clock()
        if existing is not None:
            existing.full_name = _text(payload.get("full_name")) or existing.full_name
            existing.email = email or existing.email
            existing.phone_number = phone or existing.phone_number
            existing.external_reference = reference or existing.external_reference
            existing.job_title = _text(payload.get("job_title")) or existing.job_title
            existing.team_id = team.id if team else existing.team_id
            existing.cost_centre_id = centre_id or existing.cost_centre_id
            existing.updated_at = now
            session.add(existing)
            session.flush()
            return existing, False

        person = OrganizationPerson(
            organization_id=organization_id,
            full_name=_text(payload.get("full_name")) or "",
            email=email,
            phone_number=phone,
            external_reference=reference,
            job_title=_text(payload.get("job_title")),
            team_id=team.id if team else None,
            cost_centre_id=centre_id,
            status=PersonStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        session.add(person)
        session.flush()
        return person, True

    def _own_import(
        self, session: Session, organization_id: UUID, import_id: UUID
    ) -> PeopleImport:
        record = session.exec(
            select(PeopleImport).where(
                PeopleImport.id == import_id,
                PeopleImport.organization_id == organization_id,
            )
        ).first()
        if record is None:
            raise PeopleError("import_not_found")
        return record

    def _own_cost_centre(
        self, session: Session, organization_id: UUID, cost_centre_id: UUID
    ) -> OrganizationCostCentre:
        centre = session.exec(
            select(OrganizationCostCentre).where(
                OrganizationCostCentre.id == cost_centre_id,
                OrganizationCostCentre.organization_id == organization_id,
            )
        ).first()
        if centre is None:
            raise PeopleError("cost_centre_not_found")
        return centre


def _payload_of(row: ParsedRow) -> dict[str, object]:
    return {
        "full_name": row.full_name,
        "email": row.email,
        "phone_number": row.phone_number,
        "external_reference": row.external_reference,
        "job_title": row.job_title,
        "team": row.team,
        "cost_centre": row.cost_centre,
        "raw": row.raw,
    }


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _summary(record: PeopleImport) -> ImportSummary:
    return ImportSummary(
        import_id=record.id,
        state=record.state,
        row_count=record.row_count,
        valid_count=record.valid_count,
        invalid_count=record.invalid_count,
        created_count=record.created_count,
        updated_count=record.updated_count,
    )


__all__ = ["ImportSummary", "PeopleError", "PeopleService", "RowError"]
