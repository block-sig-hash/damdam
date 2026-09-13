"""The immutable record of privileged operator decisions — US-41.

Revision ID: 0044_operator_actions
Revises: 0043_enterprise_offboarding

**Purely additive.** One new table, no column added to an existing table, no row
touched and nothing dropped. The operations surface *changes* supplier attempts,
order items and exception items at runtime; it alters none of their shapes, and
it reaches money only by posting balanced entries through chunk 10's ledger.

Three guarantees are held here rather than in application code:

- `trg_operator_action_immutable` refuses **`UPDATE` and `DELETE` outright.**
  An audit trail an operator can edit is an audit trail of whatever the last
  operator wanted it to say. The same mechanism chunk 11 used for supplier
  attempt history, and for the same reason: application-level immutability is
  one migration away from not being immutable.
- `ck_operator_actions_reason` requires a non-blank reason. A form can be
  changed by the next client; this cannot. An action nobody explained is one
  nobody can review.
- `uq_operator_actions_idempotency` makes a replayed resolution the *same*
  resolution. An operator who lost a response and clicked again must not post a
  second compensating entry.

`actor_admin_id` is `RESTRICT`: the operator who made a decision is part of the
record, and deleting them would leave a decision nobody made.

There is deliberately **no** balance-adjustment column, no free-form statement
field and no delete path for an exception. The assignment forbids an arbitrary
SQL editor and unrestricted balance editing; a closed vocabulary of named
actions and a ledger that refuses unbalanced entries is what that looks like in
a schema.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0044_operator_actions"
down_revision: str | None = "0043_enterprise_offboarding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_ENUMS = (
    (
        "operator_action_kind",
        (
            "confirm_supplier_success",
            "confirm_supplier_failure",
            "resolve_payment_discrepancy",
            "dismiss_exception",
            "view_sensitive_record",
        ),
    ),
    (
        "operator_subject_kind",
        ("order_item", "supplier_attempt", "payment", "exception_item", "organization"),
    ),
)

_IMMUTABLE_TRIGGER = """
CREATE OR REPLACE FUNCTION damdam_operator_action_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'operator action history is immutable';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_operator_action_immutable
    BEFORE UPDATE OR DELETE ON operator_actions
    FOR EACH ROW EXECUTE FUNCTION damdam_operator_action_immutable();
"""


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _NEW_ENUMS:
        postgresql.ENUM(*values, name=name, create_type=True).create(
            bind, checkfirst=True
        )

    op.create_table(
        "operator_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "kind",
            postgresql.ENUM(name="operator_action_kind", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "subject_kind",
            postgresql.ENUM(name="operator_subject_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("subject_reference", sa.String(200), nullable=False),
        sa.Column(
            "actor_admin_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column(
            "exception_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exception_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "before_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "after_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "ledger_entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("journal_entries.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "kind",
            "subject_reference",
            "idempotency_key",
            name="uq_operator_actions_idempotency",
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0", name="ck_operator_actions_reason"
        ),
    )
    op.create_index(
        "ix_operator_actions_subject",
        "operator_actions",
        ["subject_kind", "subject_reference"],
    )
    op.create_index(
        "ix_operator_actions_actor",
        "operator_actions",
        ["actor_admin_id", "created_at"],
    )
    op.create_index("ix_operator_actions_created", "operator_actions", ["created_at"])
    op.execute(_IMMUTABLE_TRIGGER)


def downgrade() -> None:
    """Drops only what `upgrade` created.

    **Development only, and more so than usual.** This table is the record of
    who decided what on the privileged surface; dropping it discards the answer
    to every later question about an incident. The trigger goes with it, because
    a trigger protecting a table that no longer exists protects nothing.
    """
    op.execute(
        "DROP TRIGGER IF EXISTS trg_operator_action_immutable ON operator_actions"
    )
    op.execute("DROP FUNCTION IF EXISTS damdam_operator_action_immutable()")
    op.drop_table("operator_actions")
    bind = op.get_bind()
    for name, _ in _NEW_ENUMS:
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
