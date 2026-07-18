"""Add destination-keyed arrival geofence configuration.

Revision ID: 0021_destination_geofences
Revises: 0020_pkg_dest_status_idx
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_destination_geofences"
down_revision: str | None = "0020_pkg_dest_status_idx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = op.create_table(
        "destination_geofences",
        sa.Column("destination_country", sa.String(2), primary_key=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("radius_meters", sa.Float(), nullable=False),
    )
    op.bulk_insert(
        table,
        [
            {
                "destination_country": "SA",
                "latitude": 21.4858,
                "longitude": 39.1925,
                "radius_meters": 150000.0,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("destination_geofences")
