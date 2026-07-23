"""Persist English/French recipient locale preferences.

Revision ID: 0025_i18n_locales
Revises: 0024_retention_payment_gaps
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025_i18n_locales"
down_revision: str | None = "0024_retention_payment_gaps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

locale = postgresql.ENUM("en", "fr", name="locale", create_type=False)


def upgrade() -> None:
    locale.create(op.get_bind(), checkfirst=True)
    for table in (
        "users",
        "organizations",
        "admin_users",
        "family_contacts",
        "manifest_pilgrims",
    ):
        op.add_column(
            table,
            sa.Column(
                "locale",
                locale,
                nullable=False,
                server_default="en",
            ),
        )
        op.alter_column(table, "locale", server_default=None)


def downgrade() -> None:
    for table in (
        "manifest_pilgrims",
        "family_contacts",
        "admin_users",
        "organizations",
        "users",
    ):
        op.drop_column(table, "locale")
    locale.drop(op.get_bind(), checkfirst=True)
