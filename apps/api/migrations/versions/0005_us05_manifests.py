"""US-05 HTO manifest upload and validation.

Revision ID: 0005_us05_manifests
Revises: 0004_us03_family_contacts
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_us05_manifests"
down_revision: str | None = "0004_us03_family_contacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

manifest_status = sa.Enum(
    "draft", "validated", "partially_ordered", "provisioned", name="manifest_status"
)
manifest_validation_status = sa.Enum(
    "valid", "invalid", "duplicate_warning", name="manifest_validation_status"
)


def upgrade() -> None:
    op.create_table(
        "manifests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("status", manifest_status, nullable=False, server_default="draft"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("uploaded_file_url", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_manifests_organization_id", "manifests", ["organization_id"]
    )

    op.create_table(
        "manifest_pilgrims",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "manifest_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("manifests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("phone_number", sa.String(14), nullable=False),
        sa.Column("passport_number", sa.String(50), nullable=True),
        sa.Column("seat_number", sa.String(10), nullable=True),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("validation_status", manifest_validation_status, nullable=False),
        sa.Column("validation_error", sa.String(255), nullable=True),
        sa.Column("family_group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("manifest_order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("activation_code", sa.String(8), nullable=True),
        sa.Column(
            "activation_code_used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "activation_code_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "esim_incompatible_flag",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_manifest_pilgrims_manifest_id", "manifest_pilgrims", ["manifest_id"]
    )
    op.create_index(
        "ix_manifest_pilgrims_phone_number", "manifest_pilgrims", ["phone_number"]
    )
    op.create_index(
        "ix_manifest_pilgrims_manifest_order_id",
        "manifest_pilgrims",
        ["manifest_order_id"],
    )
    op.create_index(
        "ix_manifest_pilgrims_activation_code",
        "manifest_pilgrims",
        ["activation_code"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("manifest_pilgrims")
    op.drop_table("manifests")
    manifest_validation_status.drop(op.get_bind(), checkfirst=True)
    manifest_status.drop(op.get_bind(), checkfirst=True)
