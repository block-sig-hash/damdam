"""Account identifiers and purpose-bound identity tokens — US-29.

Revision ID: 0028_account_identity
Revises: 0027_core_domain_model

Adds the global identity tables and makes the legacy phone/platform account
fields optional so an email-first account can exist without a SIM or mobile
device. The phone backfill is safe to re-run.

Existing accounts were created by proving a phone number over OTP, so their
phone is recorded as an already-verified identifier rather than asking
established users to re-prove something they already log in with. Without that
backfill a legacy account would own no identifier and could not recover.

Email was adopted as the launch identity on 9 September 2026. Existing phone
accounts remain valid and receive verified phone identifiers.
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
    (
        "identity_token_purpose",
        ("verify_identifier", "recover_account", "authenticate"),
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _ENUMS:
        postgresql.ENUM(*values, name=name, create_type=False).create(
            bind, checkfirst=True
        )

    op.alter_column("users", "phone_number", existing_type=sa.String(14), nullable=True)
    op.alter_column(
        "users",
        "platform",
        existing_type=postgresql.ENUM(name="platform", create_type=False),
        nullable=True,
    )
    op.add_column(
        "users",
        sa.Column(
            "auth_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_check_constraint(
        "ck_users_auth_version_nonnegative", "users", "auth_version >= 0"
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
    op.create_index(
        "ux_account_identifiers_primary_user",
        "account_identifiers",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_primary = true"),
    )

    op.create_table(
        "identity_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
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
        sa.Column(
            "target_kind",
            postgresql.ENUM(name="identifier_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("target_value", sa.String(320), nullable=False),
        sa.Column(
            "requested_locale",
            sa.String(2),
            nullable=False,
            server_default=sa.text("'en'"),
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
    email_only_accounts = bind.execute(
        sa.text(
            "SELECT count(*) FROM users "
            "WHERE phone_number IS NULL OR platform IS NULL"
        )
    ).scalar_one()
    if email_only_accounts:
        raise RuntimeError(
            "Cannot downgrade identity schema while email-only accounts exist; "
            "migrate those accounts to a phone and platform first"
        )
    op.drop_table("identity_tokens")
    op.drop_table("account_identifiers")
    op.drop_constraint("ck_users_auth_version_nonnegative", "users", type_="check")
    op.drop_column("users", "auth_version")
    op.alter_column(
        "users",
        "platform",
        existing_type=postgresql.ENUM(name="platform", create_type=False),
        nullable=False,
    )
    op.alter_column(
        "users", "phone_number", existing_type=sa.String(14), nullable=False
    )
    for name, _ in _ENUMS:
        postgresql.ENUM(name=name, create_type=False).drop(bind, checkfirst=True)
