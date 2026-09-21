"""Organization people, teams, cost centres and validated imports — US-39.

Revision ID: 0041_organization_people
Revises: 0040_account_and_support

**Purely additive.** Five new tables, no column added to an existing table, no
row touched and nothing dropped. `organization_members` in particular is left
exactly as it is: membership is what grants dashboard access, and this migration
adds no way to reach it. An organization importing two thousand staff creates
two thousand *recipients* and zero administrators.

The manifest tables chunk 04 retained (`manifests`, `manifest_rows` and their
pilgrim vocabulary) are neither read nor altered. Chunk 22 generalizes the
product's model of people; retiring the legacy tables is the removal sequence in
`IMPLEMENTATION-PLAN.md` §7, which is a different piece of work with its own
compatibility window.

Four constraints carry this chunk's guarantees:

- `ux_organization_people_reference`, `ux_organization_people_email` and
  `ux_organization_people_phone` — **duplicate identity policy, per
  organization.** Partial, because most of these fields are legitimately null;
  scoped to one organization, because two customers may employ the same
  contractor and neither gets to block the other. This is what makes the same
  file uploaded twice an update rather than a second Ada Obi.
- `ck_organization_people_identifiable` — a person with no email, no phone and
  no employee reference is a name nobody can deliver service to or recognise
  again.
- `ux_people_imports_digest` — the same bytes are the same import. An
  administrator who lost the response, or clicked twice, gets the preview they
  already have rather than a second one to choose between.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041_organization_people"
down_revision: str | None = "0040_account_and_support"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_ENUMS = (
    ("organization_person_status", ("active", "archived")),
    (
        "people_import_state",
        ("previewed", "applying", "applied", "cancelled", "rejected"),
    ),
    (
        "people_import_row_state",
        ("valid", "invalid", "created", "updated", "skipped"),
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _NEW_ENUMS:
        postgresql.ENUM(*values, name=name, create_type=True).create(
            bind, checkfirst=True
        )

    op.create_table(
        "organization_cost_centres",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id", "code", name="uq_organization_cost_centres_code"
        ),
    )
    op.create_index(
        "ix_organization_cost_centres_org",
        "organization_cost_centres",
        ["organization_id", "archived_at"],
    )

    op.create_table(
        "organization_teams",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "cost_centre_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization_cost_centres.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id", "name", name="uq_organization_teams_name"
        ),
    )
    op.create_index(
        "ix_organization_teams_org",
        "organization_teams",
        ["organization_id", "archived_at"],
    )

    op.create_table(
        "organization_people",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone_number", sa.String(20), nullable=True),
        sa.Column("external_reference", sa.String(64), nullable=True),
        sa.Column("job_title", sa.String(200), nullable=True),
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization_teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "cost_centre_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization_cost_centres.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="organization_person_status", create_type=False),
            nullable=False,
            server_default="active",
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "email IS NOT NULL OR phone_number IS NOT NULL "
            "OR external_reference IS NOT NULL",
            name="ck_organization_people_identifiable",
        ),
        sa.CheckConstraint(
            "(status = 'archived' AND archived_at IS NOT NULL) "
            "OR (status = 'active' AND archived_at IS NULL)",
            name="ck_organization_people_archived_at",
        ),
    )
    op.create_index(
        "ux_organization_people_reference",
        "organization_people",
        ["organization_id", "external_reference"],
        unique=True,
        postgresql_where=sa.text("external_reference IS NOT NULL"),
    )
    op.create_index(
        "ux_organization_people_email",
        "organization_people",
        ["organization_id", "email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_index(
        "ux_organization_people_phone",
        "organization_people",
        ["organization_id", "phone_number"],
        unique=True,
        postgresql_where=sa.text("phone_number IS NOT NULL"),
    )
    op.create_index(
        "ix_organization_people_org",
        "organization_people",
        ["organization_id", "status"],
    )
    op.create_index("ix_organization_people_team", "organization_people", ["team_id"])

    op.create_table(
        "people_imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "uploaded_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column(
            "state",
            postgresql.ENUM(name="people_import_state", create_type=False),
            nullable=False,
            server_default="previewed",
        ),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("valid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejection_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("row_count >= 0", name="ck_people_imports_row_count"),
    )
    op.create_index(
        "ux_people_imports_digest",
        "people_imports",
        ["organization_id", "content_digest"],
        unique=True,
        postgresql_where=sa.text("state <> 'cancelled'"),
    )
    op.create_index(
        "ix_people_imports_org", "people_imports", ["organization_id", "created_at"]
    )

    op.create_table(
        "people_import_rows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "import_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("people_imports.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column(
            "state",
            postgresql.ENUM(name="people_import_row_state", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "error_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization_people.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "import_id", "row_number", name="uq_people_import_rows_line"
        ),
        sa.CheckConstraint("row_number >= 1", name="ck_people_import_rows_number"),
    )
    op.create_index(
        "ix_people_import_rows_state", "people_import_rows", ["import_id", "state"]
    )


def downgrade() -> None:
    """Drops only what `upgrade` created.

    Safe in a way most downgrades are not, because nothing here was added to an
    existing table and no historical row is touched. It does discard an
    organization's people and their import history, so it belongs in a
    development rollback rather than a production procedure.
    """
    op.drop_table("people_import_rows")
    op.drop_table("people_imports")
    op.drop_table("organization_people")
    op.drop_table("organization_teams")
    op.drop_table("organization_cost_centres")
    bind = op.get_bind()
    for name, _ in _NEW_ENUMS:
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
