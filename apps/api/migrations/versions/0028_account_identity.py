"""Account identifiers and purpose-bound identity tokens — US-29.

Revision ID: 0028_account_identity
Revises: 0027_core_domain_model

Additive, with one backfill that is safe to re-run.

Existing accounts were created by proving a phone number over OTP, so their
phone is recorded as an already-verified identifier rather than asking
established users to re-prove something they already log in with. Without that
backfill a legacy account would own no identifier and could not recover.

`users.phone_number` is left exactly as it is. It remains the login identity
until a launch method is recorded as adopted in DECISIONS.md; this revision adds
the structure that makes a different choice possible without another migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028_account_identity"
down_revision: str | None = "0027_core_domain_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUMS = (
    ("identifier_kind", ("email", "phone")),
    ("identity_token_purpose", ("verify_identifier", "recover_account")),
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _ENUMS:
        postgresql.ENUM(*values, name=name, create_type=False).create(
            bind, checkfirst=True
        )

    op.create_table(
        "account_identifiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "kind",
            postgresql.ENUM(name="identifier_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("value", sa.String(320), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Partial: one *verified* owner per identifier, while any number of accounts
    # may hold the same unverified claim. Squatting therefore cannot deny
    # service to the real owner.
    op.create_index(
        "ux_account_identifiers_verified_value",
        "account_identifiers",
        ["kind", "value"],
        unique=True,
        postgresql_where=sa.text("verified_at IS NOT NULL"),
    )
    op.create_index(
        "ix_account_identifiers_user_kind", "account_identifiers", ["user_id", "kind"]
    )

    op.create_table(
        "identity_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "identifier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("account_identifiers.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "purpose",
            postgresql.ENUM(name="identity_token_purpose", create_type=False),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Backfill: every existing account gets its OTP-proved phone as a verified
    # identifier. ON CONFLICT DO NOTHING keeps a re-run harmless.
    op.execute(
        sa.text(
            """
            INSERT INTO account_identifiers
                (id, user_id, kind, value, verified_at, is_primary, created_at)
            SELECT gen_random_uuid(), u.id, 'phone', u.phone_number,
                   COALESCE(u.created_at, now()), true, now()
            FROM users u
            WHERE u.phone_number IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM account_identifiers ai
                  WHERE ai.user_id = u.id AND ai.kind = 'phone'
              )
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_table("identity_tokens")
    op.drop_table("account_identifiers")
    for name, _ in _ENUMS:
        postgresql.ENUM(name=name, create_type=False).drop(bind, checkfirst=True)
