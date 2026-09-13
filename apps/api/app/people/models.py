"""Organization people, teams, cost centres and validated imports (US-39, chunk 22).

Five tables, and the first thing to understand is what is **not** here: a role.

`app/organizations/` owns membership — who may sign in to the dashboard and what
they may do there. This module owns *people*: the employees, officers and staff
an organization buys service **for**. The assignment states the rule plainly —
*importing an email must not grant organization privilege* — and separating the
tables is how that is enforced rather than remembered. A row here carries no
authority, and no code path turns one into a membership; granting access is an
invitation, which is a different table, a different endpoint and a different
permission.

That distinction is what the legacy schema got wrong. A manifest row was a
pilgrim, an organization had one shared password, and "in the file" and "may
administer the account" were the same fact. An enterprise customer uploading two
thousand staff must not thereby create two thousand administrators.

**`organization_people`** is the recipient. `user_id` is nullable and stays null
until that person actually claims an account — an imported email is a *claim
about* somebody, not an account, and treating it as one would let an importer
bind a colleague's identity by typing it.

**`organization_teams`** and **`organization_cost_centres`** are separate because
they answer different questions. A team is who somebody works with; a cost centre
is who pays. They correlate in most organizations and not in all, and collapsing
them means a customer who reorganizes a department has to re-cut their billing.

**`people_imports`** and **`people_import_rows`** make an import a durable
record rather than a request. A five-thousand-row file cannot be validated,
previewed, confirmed and applied inside one HTTP request, and an import that
fails halfway with no record leaves an administrator guessing which half. Every
row keeps its own outcome, so "what happened to line 3,412" has an answer.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now


def _enum(
    enum_type: type[Enum], name: str, default: Enum | None = None
) -> Column[Any]:
    return Column(
        SAEnum(
            enum_type,
            name=name,
            values_callable=lambda choices: [choice.value for choice in choices],
        ),
        nullable=False,
        server_default=None if default is None else default.value,
    )


def _json(nullable: bool = False) -> Column[Any]:
    return Column(JSON().with_variant(JSONB, "postgresql"), nullable=nullable)


class PersonStatus(str, Enum):
    ACTIVE = "active"
    #: Left the organization. Never deleted: their orders, lines and receipts
    #: still name them, and a deleted row cannot explain last quarter's invoice.
    ARCHIVED = "archived"


class ImportState(str, Enum):
    """Where an import is. Each state is somewhere a file can actually stop."""

    #: Parsed and validated; nothing has been written to `organization_people`.
    PREVIEWED = "previewed"
    #: Rows are being applied. A crash leaves the import here, and the applied
    #: rows say which ones already exist.
    APPLYING = "applying"
    APPLIED = "applied"
    #: The administrator looked at the preview and chose not to proceed.
    CANCELLED = "cancelled"
    #: The file could not be read at all — not valid CSV, or no usable header.
    REJECTED = "rejected"


class ImportRowState(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    #: Written to `organization_people` as a new person.
    CREATED = "created"
    #: Matched an existing person and updated them.
    UPDATED = "updated"
    #: Deliberately not applied — a duplicate of an earlier row in the same file.
    SKIPPED = "skipped"


class OrganizationCostCentre(SQLModel, table=True):
    """Who pays, inside one organization's own accounting vocabulary."""

    __tablename__ = "organization_cost_centres"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "code", name="uq_organization_cost_centres_code"
        ),
        Index("ix_organization_cost_centres_org", "organization_id", "archived_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(
        sa_column=Column(
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    #: The customer's own code, as they use it in their finance system. Unique
    #: per organization and never interpreted by us.
    code: str = Field(sa_column=Column(String(64), nullable=False))
    name: str = Field(sa_column=Column(String(200), nullable=False))
    archived_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class OrganizationTeam(SQLModel, table=True):
    """Who somebody works with. Separate from who pays for them."""

    __tablename__ = "organization_teams"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_organization_teams_name"),
        Index("ix_organization_teams_org", "organization_id", "archived_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(
        sa_column=Column(
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    name: str = Field(sa_column=Column(String(200), nullable=False))
    #: A team's usual cost centre, applied to new people as a default. A person
    #: may still be billed elsewhere — a secondment is not a reorganization.
    cost_centre_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("organization_cost_centres.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    archived_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class OrganizationPerson(SQLModel, table=True):
    """Somebody an organization buys service for. **Not** somebody who may sign in.

    The three partial unique indexes below are the duplicate-identity policy,
    held by the database rather than by whichever code path happens to be
    importing. Each is scoped to one organization: two customers may both employ
    the same contractor, and neither of them gets to block the other.
    """

    __tablename__ = "organization_people"
    __table_args__ = (
        # An employee number, where the customer uses one. The natural key for a
        # re-import: the same file uploaded twice updates rather than doubles.
        Index(
            "ux_organization_people_reference",
            "organization_id",
            "external_reference",
            unique=True,
            postgresql_where=text("external_reference IS NOT NULL"),
            sqlite_where=text("external_reference IS NOT NULL"),
        ),
        Index(
            "ux_organization_people_email",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
            sqlite_where=text("email IS NOT NULL"),
        ),
        Index(
            "ux_organization_people_phone",
            "organization_id",
            "phone_number",
            unique=True,
            postgresql_where=text("phone_number IS NOT NULL"),
            sqlite_where=text("phone_number IS NOT NULL"),
        ),
        Index("ix_organization_people_org", "organization_id", "status"),
        Index("ix_organization_people_team", "team_id"),
        CheckConstraint(
            "email IS NOT NULL OR phone_number IS NOT NULL "
            "OR external_reference IS NOT NULL",
            name="ck_organization_people_identifiable",
        ),
        CheckConstraint(
            "(status = 'archived' AND archived_at IS NOT NULL) "
            "OR (status = 'active' AND archived_at IS NULL)",
            name="ck_organization_people_archived_at",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(
        sa_column=Column(
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    #: **Nullable, and null is the normal case.** An imported email is a claim
    #: about somebody, not an account. This is set only when that person has
    #: actually authenticated and claimed the record — anything else would let
    #: an importer bind a colleague's identity by typing their address.
    user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    full_name: str = Field(sa_column=Column(String(200), nullable=False))
    email: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    phone_number: str | None = Field(
        default=None, sa_column=Column(String(20), nullable=True)
    )
    #: The customer's own identifier — staff number, service number, file
    #: reference. Opaque to us.
    external_reference: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    job_title: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    team_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("organization_teams.id", ondelete="SET NULL"), nullable=True
        ),
    )
    cost_centre_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("organization_cost_centres.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    status: PersonStatus = Field(
        default=PersonStatus.ACTIVE,
        sa_column=_enum(
            PersonStatus, "organization_person_status", PersonStatus.ACTIVE
        ),
    )
    archived_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class PeopleImport(SQLModel, table=True):
    """One uploaded file, from parse to applied, as a resumable record."""

    __tablename__ = "people_imports"
    __table_args__ = (
        # The same bytes uploaded twice are the same import. An administrator
        # who did not see the first response — or clicked twice — gets the
        # import they already have rather than a second copy of their staff.
        Index(
            "ux_people_imports_digest",
            "organization_id",
            "content_digest",
            unique=True,
            postgresql_where=text("state <> 'cancelled'"),
            sqlite_where=text("state <> 'cancelled'"),
        ),
        Index("ix_people_imports_org", "organization_id", "created_at"),
        CheckConstraint("row_count >= 0", name="ck_people_imports_row_count"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(
        sa_column=Column(
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    #: Who uploaded it. `SET NULL` because the file's history outlives an
    #: administrator leaving.
    uploaded_by_user_id: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    filename: str = Field(sa_column=Column(String(255), nullable=False))
    #: SHA-256 of the uploaded bytes. Identity, not integrity: it is what makes
    #: a re-upload recognisable as the same file.
    content_digest: str = Field(sa_column=Column(String(64), nullable=False))
    state: ImportState = Field(
        default=ImportState.PREVIEWED,
        sa_column=_enum(ImportState, "people_import_state", ImportState.PREVIEWED),
    )
    row_count: int = Field(sa_column=Column(Integer, nullable=False))
    valid_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    invalid_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    created_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    updated_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    #: Why the whole file was refused, when it was. Row-level problems live on
    #: the rows; this is for "this is not a CSV" and "no recognisable header".
    rejection_code: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    applied_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class PeopleImportRow(SQLModel, table=True):
    """One line of one file, with what we made of it.

    The payload is kept so a preview can be re-rendered and a failure can be
    explained without asking the administrator to re-upload. It is the
    customer's own data, already in our database; what it must never become is a
    value rendered into an export without passing `csv_safe`.
    """

    __tablename__ = "people_import_rows"
    __table_args__ = (
        UniqueConstraint("import_id", "row_number", name="uq_people_import_rows_line"),
        Index("ix_people_import_rows_state", "import_id", "state"),
        CheckConstraint("row_number >= 1", name="ck_people_import_rows_number"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    import_id: UUID = Field(
        sa_column=Column(
            ForeignKey("people_imports.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    #: The line number in the customer's file, counting the header as line 1, so
    #: that "row 12" means what it means in their spreadsheet.
    row_number: int = Field(sa_column=Column(Integer, nullable=False))
    state: ImportRowState = Field(
        sa_column=_enum(ImportRowState, "people_import_row_state")
    )
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=_json())
    #: A stable code the dashboard localizes — never a sentence. One row can
    #: fail for several reasons and an administrator fixing a file needs all of
    #: them, not the first.
    error_codes: list[str] = Field(default_factory=list, sa_column=_json())
    person_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("organization_people.id", ondelete="SET NULL"), nullable=True
        ),
    )
