"""US-04 admin rejection of HTO operator registrations.

Revision ID: 0009_us04_hto_rejection
Revises: 0008_us26_manual_pricing
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_us04_hto_rejection"
down_revision: str | None = "0008_us26_manual_pricing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "rejected_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("rejection_reason", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "rejection_reason")
    op.drop_column("organizations", "rejected_by")
    op.drop_column("organizations", "rejected_at")
