"""Add destination dimension to pricing tiers.

Revision ID: 0022_pricing_tier_destination
Revises: 0021_destination_geofences
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_pricing_tier_destination"
down_revision: str | None = "0021_destination_geofences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pricing_tiers",
        sa.Column(
            "destination_country",
            sa.String(2),
            nullable=False,
            server_default="SA",
        ),
    )


def downgrade() -> None:
    op.drop_column("pricing_tiers", "destination_country")
