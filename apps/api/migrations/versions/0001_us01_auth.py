"""US-01 pilgrim accounts and hashed refresh-token sessions.

Revision ID: 0001_us01_auth
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_us01_auth"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

account_source = sa.Enum("direct", "hto_manifest", name="account_source")
platform = sa.Enum("ios", "android", name="platform")
user_status = sa.Enum("active", "suspended", name="user_status")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("phone_number", sa.String(14), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("pin_hash", sa.String(255), nullable=True),
        sa.Column(
            "pin_failed_attempts", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("pin_locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("account_source", account_source, nullable=False),
        sa.Column(
            "verified_cli", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("departure_date", sa.Date(), nullable=True),
        sa.Column(
            "destination_country", sa.String(2), nullable=False, server_default="SA"
        ),
        sa.Column("platform", platform, nullable=False),
        sa.Column("status", user_status, nullable=False, server_default="active"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_phone_number", "users", ["phone_number"], unique=True)
    op.create_index("ix_users_departure_date", "users", ["departure_date"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index(
        "ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True
    )
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])


def downgrade() -> None:
    op.drop_table("refresh_tokens")
    op.drop_table("users")
    user_status.drop(op.get_bind(), checkfirst=True)
    platform.drop(op.get_bind(), checkfirst=True)
    account_source.drop(op.get_bind(), checkfirst=True)
