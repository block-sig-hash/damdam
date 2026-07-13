"""Generalize HTO operators into organizations.

Revision ID: 0003_organization_refactor
Revises: 0002_us04_hto_registration
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_organization_refactor"
down_revision: str | None = "0002_us04_hto_registration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

organization_type = postgresql.ENUM(
    "hto_operator",
    "enterprise",
    "government",
    name="organization_type",
    create_type=False,
)


def upgrade() -> None:
    organization_type.create(op.get_bind(), checkfirst=True)
    op.execute(
        "ALTER TYPE hto_approval_status RENAME TO organization_approval_status"
    )

    op.rename_table("hto_operators", "organizations")
    op.alter_column("organizations", "business_name", new_column_name="name")
    op.alter_column(
        "organizations", "operator_name", new_column_name="primary_contact_name"
    )
    op.add_column(
        "organizations",
        sa.Column(
            "org_type",
            organization_type,
            nullable=False,
            server_default="hto_operator",
        ),
    )
    op.alter_column("organizations", "org_type", server_default=None)
    op.alter_column("organizations", "nahcon_licence_number", nullable=True)
    op.create_check_constraint(
        "ck_organizations_hto_licence",
        "organizations",
        "(org_type = 'hto_operator' AND nahcon_licence_number IS NOT NULL) "
        "OR (org_type != 'hto_operator' AND nahcon_licence_number IS NULL)",
    )
    op.execute(
        "ALTER TABLE organizations RENAME CONSTRAINT "
        "hto_operators_pkey TO organizations_pkey"
    )
    op.execute(
        "ALTER INDEX ix_hto_operators_email RENAME TO ix_organizations_email"
    )

    op.rename_table("hto_refresh_tokens", "organization_refresh_tokens")
    op.alter_column(
        "organization_refresh_tokens",
        "hto_operator_id",
        new_column_name="organization_id",
    )
    op.execute(
        "ALTER TABLE organization_refresh_tokens RENAME CONSTRAINT "
        "hto_refresh_tokens_pkey TO organization_refresh_tokens_pkey"
    )
    op.execute(
        "ALTER TABLE organization_refresh_tokens RENAME CONSTRAINT "
        "hto_refresh_tokens_hto_operator_id_fkey TO "
        "organization_refresh_tokens_organization_id_fkey"
    )
    op.execute(
        "ALTER INDEX ix_hto_refresh_tokens_hto_operator_id RENAME TO "
        "ix_organization_refresh_tokens_organization_id"
    )
    op.execute(
        "ALTER INDEX ix_hto_refresh_tokens_token_hash RENAME TO "
        "ix_organization_refresh_tokens_token_hash"
    )
    op.execute(
        "ALTER INDEX ix_hto_refresh_tokens_expires_at RENAME TO "
        "ix_organization_refresh_tokens_expires_at"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM organizations "
        "WHERE org_type != 'hto_operator') THEN "
        "RAISE EXCEPTION 'cannot downgrade with non-HTO organizations'; "
        "END IF; END $$"
    )

    op.execute(
        "ALTER INDEX ix_organization_refresh_tokens_expires_at RENAME TO "
        "ix_hto_refresh_tokens_expires_at"
    )
    op.execute(
        "ALTER INDEX ix_organization_refresh_tokens_token_hash RENAME TO "
        "ix_hto_refresh_tokens_token_hash"
    )
    op.execute(
        "ALTER INDEX ix_organization_refresh_tokens_organization_id RENAME TO "
        "ix_hto_refresh_tokens_hto_operator_id"
    )
    op.execute(
        "ALTER TABLE organization_refresh_tokens RENAME CONSTRAINT "
        "organization_refresh_tokens_organization_id_fkey TO "
        "hto_refresh_tokens_hto_operator_id_fkey"
    )
    op.execute(
        "ALTER TABLE organization_refresh_tokens RENAME CONSTRAINT "
        "organization_refresh_tokens_pkey TO hto_refresh_tokens_pkey"
    )
    op.alter_column(
        "organization_refresh_tokens",
        "organization_id",
        new_column_name="hto_operator_id",
    )
    op.rename_table("organization_refresh_tokens", "hto_refresh_tokens")

    op.drop_constraint(
        "ck_organizations_hto_licence", "organizations", type_="check"
    )
    op.alter_column("organizations", "nahcon_licence_number", nullable=False)
    op.drop_column("organizations", "org_type")
    op.execute(
        "ALTER INDEX ix_organizations_email RENAME TO ix_hto_operators_email"
    )
    op.execute(
        "ALTER TABLE organizations RENAME CONSTRAINT "
        "organizations_pkey TO hto_operators_pkey"
    )
    op.alter_column(
        "organizations", "primary_contact_name", new_column_name="operator_name"
    )
    op.alter_column("organizations", "name", new_column_name="business_name")
    op.rename_table("organizations", "hto_operators")

    op.execute(
        "ALTER TYPE organization_approval_status RENAME TO hto_approval_status"
    )
    organization_type.drop(op.get_bind(), checkfirst=True)
