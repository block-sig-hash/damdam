"""Organization people, teams, cost centres and imports (US-39, chunk 22).

Every handler takes its authority from `require(...)`, the same dependency the
membership routes use, and every one of them reads the organization id from the
**resolved tenant context** rather than from the path. The path segment is
retained for a readable URL and deliberately discarded: a handler that trusted
it would be one `organization_id` away from serving another customer's staff
list to whoever guessed a UUID.

`PEOPLE_READ` and `PEOPLE_MANAGE` were declared by chunk 07 and granted to
owners and administrators only. Billing and member roles reach none of this,
which is the acceptance criterion — *billing/member roles cannot perform
administrator actions* — held by the matrix rather than by a check per route.

The export is a `csv_safe` pass over data the customer typed. It is the reason
that helper is shared rather than copied: a people file is almost entirely
untrusted text, and it is downloaded specifically to be opened in a spreadsheet.
"""

from __future__ import annotations

import csv
import io
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.csv_export import csv_safe
from app.organizations.dependencies import TenantContext, require
from app.organizations.permissions import Permission
from app.people.models import (
    ImportState,
    OrganizationPerson,
    PeopleImport,
    PeopleImportRow,
)
from app.people.schemas import (
    CostCentreCreate,
    CostCentreListResponse,
    CostCentreView,
    ImportListResponse,
    ImportPreviewResponse,
    ImportRowListResponse,
    ImportRowView,
    ImportSummaryView,
    PersonListResponse,
    PersonView,
    TeamCreate,
    TeamListResponse,
    TeamView,
)
from app.people.service import PeopleService

router = APIRouter(prefix="/organizations", tags=["Organization people"])

#: How much of a preview crosses the wire. A five-thousand-row response is a
#: page nobody reads and a payload nobody should have to download to decide.
PREVIEW_SAMPLE = 25

#: Upload ceiling enforced before the body is parsed. The parser has its own,
#: lower limit; this one exists so an enormous file is refused without being
#: read into memory twice.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def _service(request: Request) -> PeopleService:
    return cast(PeopleService, request.app.state.people_service)


def _person_view(person: OrganizationPerson) -> PersonView:
    return PersonView(
        person_id=person.id,
        full_name=person.full_name,
        email=person.email,
        phone_number=person.phone_number,
        external_reference=person.external_reference,
        job_title=person.job_title,
        team_id=person.team_id,
        cost_centre_id=person.cost_centre_id,
        status=person.status,
        has_account=person.user_id is not None,
    )


def _import_view(record: PeopleImport) -> ImportSummaryView:
    return ImportSummaryView(
        import_id=record.id,
        state=record.state,
        filename=record.filename,
        row_count=record.row_count,
        valid_count=record.valid_count,
        invalid_count=record.invalid_count,
        created_count=record.created_count,
        updated_count=record.updated_count,
        rejection_code=record.rejection_code,
        created_at=record.created_at,
        applied_at=record.applied_at,
    )


def _row_view(row: PeopleImportRow) -> ImportRowView:
    return ImportRowView(
        row_number=row.row_number,
        state=row.state.value,
        error_codes=list(row.error_codes),
        payload=dict(row.payload),
    )


# --- cost centres and teams -------------------------------------------------


@router.get(
    "/{organization_id}/cost-centres", response_model=CostCentreListResponse
)
def list_cost_centres(
    organization_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.PEOPLE_READ)],
) -> CostCentreListResponse:
    del organization_id
    with request.app.state.session_factory() as session:
        return CostCentreListResponse(
            cost_centres=[
                CostCentreView(
                    cost_centre_id=centre.id,
                    code=centre.code,
                    name=centre.name,
                    archived_at=centre.archived_at,
                )
                for centre in _service(request).cost_centres(
                    session, context.organization_id
                )
            ]
        )


@router.post(
    "/{organization_id}/cost-centres",
    response_model=CostCentreView,
    status_code=201,
)
def create_cost_centre(
    organization_id: UUID,
    payload: CostCentreCreate,
    request: Request,
    context: Annotated[TenantContext, require(Permission.PEOPLE_MANAGE)],
) -> CostCentreView:
    del organization_id
    with request.app.state.session_factory() as session:
        centre = _service(request).create_cost_centre(
            session, context.organization_id, code=payload.code, name=payload.name
        )
        view = CostCentreView(
            cost_centre_id=centre.id,
            code=centre.code,
            name=centre.name,
            archived_at=centre.archived_at,
        )
        session.commit()
        return view


@router.get("/{organization_id}/teams", response_model=TeamListResponse)
def list_teams(
    organization_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.PEOPLE_READ)],
) -> TeamListResponse:
    del organization_id
    with request.app.state.session_factory() as session:
        return TeamListResponse(
            teams=[
                TeamView(
                    team_id=team.id,
                    name=team.name,
                    cost_centre_id=team.cost_centre_id,
                    archived_at=team.archived_at,
                )
                for team in _service(request).teams(session, context.organization_id)
            ]
        )


@router.post(
    "/{organization_id}/teams", response_model=TeamView, status_code=201
)
def create_team(
    organization_id: UUID,
    payload: TeamCreate,
    request: Request,
    context: Annotated[TenantContext, require(Permission.PEOPLE_MANAGE)],
) -> TeamView:
    del organization_id
    with request.app.state.session_factory() as session:
        team = _service(request).create_team(
            session,
            context.organization_id,
            name=payload.name,
            cost_centre_id=payload.cost_centre_id,
        )
        view = TeamView(
            team_id=team.id,
            name=team.name,
            cost_centre_id=team.cost_centre_id,
            archived_at=team.archived_at,
        )
        session.commit()
        return view


# --- people -----------------------------------------------------------------


@router.get("/{organization_id}/people", response_model=PersonListResponse)
def list_people(
    organization_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.PEOPLE_READ)],
    team_id: Annotated[UUID | None, Query()] = None,
    include_archived: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> PersonListResponse:
    del organization_id
    with request.app.state.session_factory() as session:
        return PersonListResponse(
            people=[
                _person_view(person)
                for person in _service(request).people(
                    session,
                    context.organization_id,
                    team_id=team_id,
                    include_archived=include_archived,
                    limit=limit,
                )
            ]
        )


@router.get("/{organization_id}/people.csv")
def export_people(
    organization_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.REPORT_EXPORT)],
    include_archived: Annotated[bool, Query()] = False,
) -> StreamingResponse:
    """This organization's people, as a file that is safe to open.

    Every cell goes through `csv_safe`. The values here are, almost without
    exception, text a customer typed into a spreadsheet and uploaded — and this
    file exists to be opened in a spreadsheet, which is precisely the
    combination that makes formula injection work.
    """
    del organization_id
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Full name",
            "Email",
            "Phone number",
            "Employee reference",
            "Job title",
            "Team",
            "Cost centre",
            "Status",
        ]
    )
    with request.app.state.session_factory() as session:
        service = _service(request)
        teams = {
            team.id: team.name
            for team in service.teams(
                session, context.organization_id, include_archived=True
            )
        }
        centres = {
            centre.id: centre.code
            for centre in service.cost_centres(
                session, context.organization_id, include_archived=True
            )
        }
        for person in service.people(
            session,
            context.organization_id,
            include_archived=include_archived,
            limit=500,
        ):
            writer.writerow(
                [
                    csv_safe(person.full_name),
                    csv_safe(person.email or ""),
                    csv_safe(person.phone_number or ""),
                    csv_safe(person.external_reference or ""),
                    csv_safe(person.job_title or ""),
                    csv_safe(teams.get(person.team_id, "") if person.team_id else ""),
                    csv_safe(
                        centres.get(person.cost_centre_id, "")
                        if person.cost_centre_id
                        else ""
                    ),
                    person.status.value,
                ]
            )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="people.csv"'},
    )


# --- imports ----------------------------------------------------------------


@router.post(
    "/{organization_id}/people/imports",
    response_model=ImportPreviewResponse,
    status_code=201,
)
async def upload_import(
    organization_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.PEOPLE_MANAGE)],
    file: Annotated[UploadFile, File()],
) -> ImportPreviewResponse:
    """Parse and record. **Writes no people.**

    The response is what *would* happen, produced by the same code that will do
    it. An administrator approving a preview is approving a computation, not an
    estimate.
    """
    del organization_id
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    service = _service(request)
    with request.app.state.session_factory() as session:
        record, parsed = service.preview_import(
            session,
            context.organization_id,
            filename=file.filename or "upload.csv",
            content=content,
            uploaded_by_user_id=context.actor_user_id,
        )
        rows = service.import_rows(
            session, context.organization_id, record.id, limit=PREVIEW_SAMPLE
        )
        response = ImportPreviewResponse(
            summary=_import_view(record),
            sample_rows=[_row_view(row) for row in rows],
            ignored_columns=list(parsed.ignored_columns) if parsed else [],
        )
        session.commit()
        return response


@router.get(
    "/{organization_id}/people/imports", response_model=ImportListResponse
)
def list_imports(
    organization_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.PEOPLE_READ)],
) -> ImportListResponse:
    del organization_id
    from sqlmodel import col, select

    with request.app.state.session_factory() as session:
        records = session.exec(
            select(PeopleImport)
            .where(PeopleImport.organization_id == context.organization_id)
            .order_by(col(PeopleImport.created_at).desc())
            .limit(50)
        ).all()
        return ImportListResponse(
            imports=[_import_view(record) for record in records]
        )


@router.get(
    "/{organization_id}/people/imports/{import_id}/rows",
    response_model=ImportRowListResponse,
)
def list_import_rows(
    organization_id: UUID,
    import_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.PEOPLE_READ)],
    only_invalid: Annotated[bool, Query()] = False,
) -> ImportRowListResponse:
    """What happened to each line, so "row 3,412" has an answer."""
    del organization_id
    with request.app.state.session_factory() as session:
        rows = _service(request).import_rows(
            session,
            context.organization_id,
            import_id,
            only_invalid=only_invalid,
        )
        return ImportRowListResponse(rows=[_row_view(row) for row in rows])


@router.post(
    "/{organization_id}/people/imports/{import_id}/apply",
    response_model=ImportSummaryView,
)
def apply_import(
    organization_id: UUID,
    import_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.PEOPLE_MANAGE)],
) -> ImportSummaryView:
    del organization_id
    with request.app.state.session_factory() as session:
        service = _service(request)
        service.apply_import(session, context.organization_id, import_id)
        record = session.get(PeopleImport, import_id)
        assert record is not None  # noqa: S101 - apply_import proved ownership
        view = _import_view(record)
        session.commit()
        return view


@router.post(
    "/{organization_id}/people/imports/{import_id}/cancel",
    response_model=ImportSummaryView,
)
def cancel_import(
    organization_id: UUID,
    import_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.PEOPLE_MANAGE)],
) -> ImportSummaryView:
    del organization_id
    with request.app.state.session_factory() as session:
        record = _service(request).cancel_import(
            session, context.organization_id, import_id
        )
        view = _import_view(record)
        session.commit()
        return view



# --- one person -------------------------------------------------------------
#
# Declared **after** the import routes on purpose. FastAPI matches in
# declaration order, and `/people/{person_id}` declared first would swallow
# `/people/imports` and then fail to parse "imports" as a UUID — a 422 on a
# route that exists, which is the kind of bug that survives review because the
# handler it should have reached looks perfectly correct.

@router.get("/{organization_id}/people/{person_id}", response_model=PersonView)
def get_person(
    organization_id: UUID,
    person_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.PEOPLE_READ)],
) -> PersonView:
    del organization_id
    with request.app.state.session_factory() as session:
        return _person_view(
            _service(request).person(session, context.organization_id, person_id)
        )


@router.post(
    "/{organization_id}/people/{person_id}/archive", response_model=PersonView
)
def archive_person(
    organization_id: UUID,
    person_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.PEOPLE_MANAGE)],
) -> PersonView:
    """Somebody left. Their orders and receipts still name them."""
    del organization_id
    with request.app.state.session_factory() as session:
        person = _service(request).archive_person(
            session, context.organization_id, person_id
        )
        view = _person_view(person)
        session.commit()
        return view


__all__ = ["ImportState", "router"]
