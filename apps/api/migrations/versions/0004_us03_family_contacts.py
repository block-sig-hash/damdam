"""US-03 family contact WhatsApp nomination.

Revision ID: 0004_us03_family_contacts
Revises: 0003_organization_refactor
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_us03_family_contacts"
down_revision: str | None = "0003_organization_refactor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "family_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phone_number", sa.String(14), nullable=False),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column(
            "notified_of_nomination",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_family_contacts_user_id",
        "family_contacts",
        ["user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("family_contacts")
