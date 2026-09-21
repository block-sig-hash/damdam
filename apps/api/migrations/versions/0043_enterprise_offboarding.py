"""Offboarding runs and their individual actions — US-40.

Revision ID: 0043_enterprise_offboarding
Revises: 0042_bulk_provisioning

**Purely additive.** Two new tables, no column added to an existing table, no
row touched and nothing dropped. Offboarding *changes* rows in
`organization_members`, `activation_requests`, `bulk_job_items` and
`organization_people` at runtime — it does not alter their shape.

Funding, budgets and departmental reporting add **no schema at all**. They are
read models over the ledger, chunk 17's policies, chunk 22's teams and cost
centres and chunk 16's usage records. A stored report is a number that starts
drifting the moment it is written, and the one thing an enterprise report has to
be is reconcilable with the ledger.

Two constraints carry this chunk's guarantees:

- `ux_organization_offboardings_open` — one open run per person. Pressing the
  button twice is the same departure, and two runs would race each other's
  suspensions.
- `ck_offboarding_actions_failure_reason` — a failed action must say why. An
  action that failed silently is indistinguishable from one that was never
  attempted, and an administrator cannot act on either.

`offboarding_actions.target_reference` is a string rather than a foreign key
because the targets are of different kinds — a membership, an invitation, a
line, a call. Five nullable columns, four always empty, and a sixth kind next
quarter is the alternative.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043_enterprise_offboarding"
down_revision: str | None = "0042_bulk_provisioning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_ENUMS = (
    (
        "offboarding_state",
        (
            "requested",
            "in_progress",
            "completed",
            "completed_with_pending",
            "completed_with_exceptions",
        ),
    ),
    (
        "offboarding_action_kind",
        (
            "revoke_membership",
            "revoke_activation_request",
            "cancel_pending_line",
            "revoke_entitlement",
            "suspend_line",
            "end_active_call",
            "cancel_pending_top_up",
        ),
    ),
    (
        "offboarding_action_state",
        ("requested", "confirmed", "pending_carrier", "not_applicable", "failed"),
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _NEW_ENUMS:
        postgresql.ENUM(*values, name=name, create_type=True).create(
            bind, checkfirst=True
        )

    op.create_table(
        "organization_offboardings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization_people.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "requested_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "state",
            postgresql.ENUM(name="offboarding_state", create_type=False),
            nullable=False,
            server_default="requested",
        ),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ux_organization_offboardings_open",
        "organization_offboardings",
        ["person_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('requested', 'in_progress')"),
    )
    op.create_index(
        "ix_organization_offboardings_org",
        "organization_offboardings",
        ["organization_id", "requested_at"],
    )

    op.create_table(
        "offboarding_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "offboarding_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization_offboardings.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "kind",
            postgresql.ENUM(name="offboarding_action_kind", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "state",
            postgresql.ENUM(name="offboarding_action_state", create_type=False),
            nullable=False,
            server_default="requested",
        ),
        sa.Column("target_reference", sa.String(200), nullable=True),
        sa.Column("detail", sa.String(500), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(state = 'failed' AND detail IS NOT NULL) OR state <> 'failed'",
            name="ck_offboarding_actions_failure_reason",
        ),
    )
    op.create_index(
        "ix_offboarding_actions_run", "offboarding_actions", ["offboarding_id", "state"]
    )


def downgrade() -> None:
    """Drops only what `upgrade` created.

    The revocations an offboarding performed **stay revoked**. They are changes
    to membership, invitation and line rows, and undoing them because the record
    of why was dropped would restore access somebody deliberately removed.
    """
    op.drop_table("offboarding_actions")
    op.drop_table("organization_offboardings")
    bind = op.get_bind()
    for name, _ in _NEW_ENUMS:
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
