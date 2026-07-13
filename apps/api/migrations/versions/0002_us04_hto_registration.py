"""US-04 HTO operator registration and approval.

Revision ID: 0002_us04_hto_registration
Revises: 0001_us01_auth
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_us04_hto_registration"
down_revision: str | None = "0001_us01_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

admin_role = sa.Enum("admin", name="admin_role")
hto_approval_status = sa.Enum(
    "pending", "approved", "rejected", name="hto_approval_status"
)


def upgrade() -> None:
    op.create_table(
        "admin_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", admin_role, nullable=False, server_default="admin"),
    )
    op.create_index("ix_admin_users_email", "admin_users", ["email"], unique=True)

    op.create_table(
        "hto_operators",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("business_name", sa.String(255), nullable=False),
        sa.Column("operator_name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("phone_number", sa.String(14), nullable=False),
        sa.Column("nahcon_licence_number", sa.String(50), nullable=False),
        sa.Column(
            "email_verified", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "approval_status",
            hto_approval_status,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "approved_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "approval_email_sent_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "approval_whatsapp_sent_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_hto_operators_email", "hto_operators", ["email"], unique=True)

    op.create_table(
        "hto_refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "hto_operator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hto_operators.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_hto_refresh_tokens_hto_operator_id",
        "hto_refresh_tokens",
        ["hto_operator_id"],
    )
    op.create_index(
        "ix_hto_refresh_tokens_token_hash",
        "hto_refresh_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_hto_refresh_tokens_expires_at", "hto_refresh_tokens", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_table("hto_refresh_tokens")
    op.drop_table("hto_operators")
    op.drop_table("admin_users")
    hto_approval_status.drop(op.get_bind(), checkfirst=True)
    admin_role.drop(op.get_bind(), checkfirst=True)
