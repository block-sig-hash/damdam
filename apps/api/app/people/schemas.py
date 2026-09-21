"""Request and response shapes for organization people (US-39, chunk 22)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.people.models import ImportState, PersonStatus


class CostCentreCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)


class CostCentreView(BaseModel):
    cost_centre_id: UUID
    code: str
    name: str
    archived_at: datetime | None = None


class CostCentreListResponse(BaseModel):
    cost_centres: list[CostCentreView]


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    cost_centre_id: UUID | None = None


class TeamView(BaseModel):
    team_id: UUID
    name: str
    cost_centre_id: UUID | None = None
    archived_at: datetime | None = None


class TeamListResponse(BaseModel):
    teams: list[TeamView]


class PersonView(BaseModel):
    """A service recipient.

    Carries no role and no permissions, because a person has none — the field
    would be the first step towards an import that grants access.
    """

    person_id: UUID
    full_name: str
    email: str | None = None
    phone_number: str | None = None
    external_reference: str | None = None
    job_title: str | None = None
    team_id: UUID | None = None
    cost_centre_id: UUID | None = None
    status: PersonStatus
    #: Whether this person has claimed an account. Never a claim that the
    #: address we hold belongs to them.
    has_account: bool = False


class PersonListResponse(BaseModel):
    people: list[PersonView]


class ImportRowView(BaseModel):
    row_number: int
    state: str
    #: Stable codes the dashboard localizes — one row can fail several ways and
    #: an administrator fixing a file needs all of them.
    error_codes: list[str]
    payload: dict[str, object]


class ImportSummaryView(BaseModel):
    import_id: UUID
    state: ImportState
    filename: str
    row_count: int
    valid_count: int
    invalid_count: int
    created_count: int
    updated_count: int
    #: Set only when the whole file was refused. Row problems live on the rows.
    rejection_code: str | None = None
    created_at: datetime
    applied_at: datetime | None = None


class ImportPreviewResponse(BaseModel):
    summary: ImportSummaryView
    #: A sample, not the file. A five-thousand-row preview rendered whole is a
    #: page nobody can read and a response nobody should have to download.
    sample_rows: list[ImportRowView]
    ignored_columns: list[str] = []


class ImportListResponse(BaseModel):
    imports: list[ImportSummaryView]


class ImportRowListResponse(BaseModel):
    rows: list[ImportRowView]
