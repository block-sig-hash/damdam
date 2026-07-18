"""Index package lookups by user, destination, and status.

Revision ID: 0020_pkg_dest_status_idx
Revises: 0019_pkg_destination_country
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020_pkg_dest_status_idx"
down_revision: str | None = "0019_pkg_destination_country"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_packages_user_destination_status",
        "packages",
        ["user_id", "destination_country", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_packages_user_destination_status", table_name="packages")
