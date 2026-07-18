"""Adds packages.destination_country, an immutable purchase-time snapshot
of the purchasing user's users.destination_country -- same pattern as the
existing data_gb_total/pstn_minutes_total snapshots (data-model.md §6.29).
Closes a latent bug: AC-25.3's chaining/superseding query and voice's
active-package balance lookup previously had no destination dimension at
all, so a second real destination would incorrectly chain/supersede or
bill against an unrelated destination's package. See data-model.md §6.32.

Revision ID: 0019_pkg_destination_country
Revises: 0018_us25_chaining_audit
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_pkg_destination_country"
down_revision: str | None = "0018_us25_chaining_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default backfills every pre-existing row in the same
    # statement on Postgres (fast-default path since PG11, no table
    # rewrite) -- every package that has ever existed was purchased by a
    # user whose destination_country has only ever been 'SA', so this is
    # not just an efficient default, it is the historically correct value.
    op.add_column(
        "packages",
        sa.Column(
            "destination_country",
            sa.String(2),
            nullable=False,
            server_default="SA",
        ),
    )


def downgrade() -> None:
    op.drop_column("packages", "destination_country")
