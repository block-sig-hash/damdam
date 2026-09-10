"""Organization memberships, invitations and second factors — US-29, chunk 07.

Revision ID: 0029_organization_memberships
Revises: 0028_account_identity

Additive. No column is dropped, no row is deleted, and
`organizations.email`/`organizations.password_hash` are left exactly as they
are — the shared credential still opens the manifest and reporting flows so the
dashboard keeps working. What changes is that it no longer opens anything
privileged; that is enforced in `app/organizations/dependencies.py`, not here.

## The controlled migration, and what it deliberately does not do

Existing organizations get **one pending owner invitation** addressed to the
contact address already recorded on the row. That is the whole promotion path.

- **No user account is created.** Manufacturing an account for an address
  nobody has proved would be exactly the auto-promotion the assignment forbids,
  and it cannot be undone by anyone who later turns out not to own the mailbox.
- **Nobody becomes an owner here.** The organization gains its first owner when
  a person proves they can read that mailbox — a verified `account_identifiers`
  row — and claims the offer.
- **No `users` row is touched, read for enrollment, or promoted.** Historical
  customer accounts are customers; none of them is enrolled as organization
  staff by this revision.
- **Organizations that already have an active owner are skipped**, so a re-run
  cannot put a live tenant's ownership back up for grabs.

Bootstrap invitations carry no token and no expiry, and a CHECK constraint ties
those two nulls to `is_bootstrap`. A migration can neither send mail nor know
when someone will read it, so a seeded invitation with the ordinary seven-day
deadline would be dead before anyone saw it — and an expiring bootstrap offer
would lock every un-migrated organization out of its own account.

Rollback: `downgrade()` drops the new tables and enum types only. Nothing it
removes existed before this revision, so no pre-existing state is lost.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_organization_memberships"
down_revision: str | None = "0028_account_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUMS = (
    ("organization_role", ("owner", "administrator", "billing", "member")),
    ("organization_membership_status", ("active", "revoked")),
    ("organization_invitation_status", ("pending", "accepted", "revoked")),
    ("mfa_status", ("pending", "active", "disabled")),
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _ENUMS:
        postgresql.ENUM(*values, name=name, create_type=True).create(
            bind, checkfirst=True
        )

    op.create_table(
        "organization_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "role",
            postgresql.ENUM(name="organization_role", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                name="organization_membership_status", create_type=False
            ),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "invited_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # One row per pair, for the life of the pair. This is the last line
        # against an invitation replay producing two answers to "what may this
        # person do here".
        sa.UniqueConstraint(
            "organization_id", "user_id", name="uq_organization_members_pair"
        ),
        sa.CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL) "
            "OR (status = 'active' AND revoked_at IS NULL)",
            name="ck_organization_members_revoked_at",
        ),
    )
    op.create_index(
        "ix_organization_members_active",
        "organization_members",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_organization_members_user", "organization_members", ["user_id", "status"]
    )

    op.create_table(
        "organization_invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "role",
            postgresql.ENUM(name="organization_role", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "invited_kind",
            postgresql.ENUM(name="identifier_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("invited_value", sa.String(320), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=True, unique=True),
        sa.Column(
            "is_bootstrap", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                name="organization_invitation_status", create_type=False
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "invited_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "accepted_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(is_bootstrap AND token_hash IS NULL AND expires_at IS NULL) "
            "OR (NOT is_bootstrap AND token_hash IS NOT NULL "
            "AND expires_at IS NOT NULL)",
            name="ck_organization_invitations_bootstrap",
        ),
        sa.CheckConstraint(
            "(status = 'accepted' AND accepted_at IS NOT NULL "
            "AND accepted_by_user_id IS NOT NULL) "
            "OR (status <> 'accepted' AND accepted_at IS NULL "
            "AND accepted_by_user_id IS NULL)",
            name="ck_organization_invitations_accepted",
        ),
    )
    # Partial: at most one *live* offer per address per organization, while any
    # number of accepted or revoked ones may remain as history.
    op.create_index(
        "ux_organization_invitations_pending",
        "organization_invitations",
        ["organization_id", "invited_kind", "invited_value"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_organization_invitations_recipient",
        "organization_invitations",
        ["invited_kind", "invited_value", "status"],
    )

    op.create_table(
        "user_mfa_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("secret", sa.LargeBinary(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="mfa_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("last_used_counter", sa.Integer(), nullable=True),
        sa.Column(
            "failed_attempts", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "failed_attempts >= 0", name="ck_user_mfa_credentials_attempts"
        ),
        sa.CheckConstraint(
            "(status = 'active' AND confirmed_at IS NOT NULL) "
            "OR (status <> 'active' AND TRUE)",
            name="ck_user_mfa_credentials_confirmed",
        ),
    )
    # Partial: one live credential per account. A second active secret is a
    # second key to the same door, and nobody audits keys they did not know
    # about. Disabled rows are retained so "this code was spent" has an answer.
    op.create_index(
        "ux_user_mfa_credentials_live",
        "user_mfa_credentials",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'disabled'"),
    )

    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "credential_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_mfa_credentials.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code_hash", name="uq_mfa_recovery_codes_hash"),
    )
    op.create_index(
        "ix_mfa_recovery_codes_credential",
        "mfa_recovery_codes",
        ["credential_id", "used_at"],
    )

    op.create_table(
        "organization_elevations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "credential_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_mfa_credentials.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_organization_elevations_live",
        "organization_elevations",
        ["user_id", "organization_id", "revoked_at"],
    )

    # The controlled migration. See the module docstring for what this
    # deliberately does not do. `NOT EXISTS` on both an active owner and a
    # pending offer makes a re-run a no-op.
    op.execute(
        sa.text(
            """
            INSERT INTO organization_invitations
                (id, organization_id, role, invited_kind, invited_value,
                 token_hash, is_bootstrap, status, expires_at, created_at)
            SELECT gen_random_uuid(), o.id, 'owner', 'email',
                   lower(o.email), NULL, true, 'pending', NULL, now()
            FROM organizations o
            WHERE o.email IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM organization_members m
                  WHERE m.organization_id = o.id
                    AND m.role = 'owner'
                    AND m.status = 'active'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM organization_invitations i
                  WHERE i.organization_id = o.id
                    AND i.invited_kind = 'email'
                    AND i.invited_value = lower(o.email)
                    AND i.status = 'pending'
              )
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_table("organization_elevations")
    op.drop_table("mfa_recovery_codes")
    op.drop_table("user_mfa_credentials")
    op.drop_table("organization_invitations")
    op.drop_table("organization_members")
    for name, _ in _ENUMS:
        postgresql.ENUM(name=name, create_type=False).drop(bind, checkfirst=True)
