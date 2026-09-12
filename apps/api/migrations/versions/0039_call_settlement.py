"""Call charges, supplier costs and durable settlement deadlines — US-46.

Revision ID: 0039_call_settlement
Revises: 0038_call_authorization

**Purely additive.** Three new tables, no column added to an existing table, no
row touched, nothing seeded and nothing dropped. `call_attempts`, `call_legs`,
`call_operations` and `call_events` — everything V02 created — are referenced by
foreign key and otherwise untouched, and the historical voice tables chunk 04
retained are neither read nor altered.

`exception_kind` gains five values. `ALTER TYPE … ADD VALUE` is used for the
same reason chunk 16 used it: rewriting the type would require rewriting every
row that references it, and the queue holds rows that must survive.

Three constraints carry this chunk's guarantees, and each is a failure a code
path alone has not historically prevented:

- `ux_call_charges_live` — **one live charge per attempt.** Settlement is
  idempotent through chunk 10's business event id, but a second charge row would
  let two amounts both claim to be current, and a receipt cannot be rendered
  from a disagreement. A correction supersedes; it does not coexist.
- `ck_call_charges_total_is_its_parts` — the charged amount is exactly setup
  plus usage. A total that can drift from its own breakdown is a receipt that
  cannot be explained to the person who paid it.
- `uq_call_supplier_costs_reference` — one supplier reference, one component,
  one row. A redelivered CDR is the ordinary case, not the exception, and
  counting it twice overstates cost and understates margin in the same motion.

`ux_call_deadlines_open` allows exactly one open deadline per attempt and kind,
so a restarted worker that re-registers a renewal finds the existing row instead
of creating a second one that fires twice.

**No money moves here and no route is enabled.** The tables exist so that
settlement can be built and tested against PostgreSQL's real guarantees while
V01's blockers B1–B5 keep the live route closed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039_call_settlement"
down_revision: str | None = "0038_call_authorization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_ENUMS = (
    ("call_charge_state", ("provisional", "final", "superseded")),
    (
        "call_charge_basis",
        ("provider_events", "supplier_cdr", "manual_correction"),
    ),
    (
        "call_supplier_cost_component",
        (
            "webrtc",
            "voice_api",
            "pstn_termination",
            "connection_fee",
            "tax_or_passthrough",
            "adjustment",
        ),
    ),
    (
        "call_deadline_kind",
        (
            "reservation_renewal",
            "unknown_outcome_review",
            "missing_terminal_event",
            "supplier_cost_wait",
        ),
    ),
    ("call_deadline_state", ("pending", "claimed", "done", "abandoned")),
)

_NEW_EXCEPTION_KINDS = (
    "call_duplicate_billable_leg",
    "call_missing_terminal_event",
    "call_unknown_outcome",
    "call_settlement_shortfall",
    "call_supplier_cost_unmatched",
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _NEW_ENUMS:
        postgresql.ENUM(*values, name=name, create_type=True).create(
            bind, checkfirst=True
        )
    for value in _NEW_EXCEPTION_KINDS:
        op.execute(f"ALTER TYPE exception_kind ADD VALUE IF NOT EXISTS '{value}'")

    op.create_table(
        "call_charges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("call_attempts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "state",
            postgresql.ENUM(name="call_charge_state", create_type=False),
            nullable=False,
            server_default="provisional",
        ),
        sa.Column(
            "basis",
            postgresql.ENUM(name="call_charge_basis", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "corrects_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("call_charges.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("billable_seconds", sa.Integer(), nullable=False),
        sa.Column("setup_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("usage_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("charged_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("metered_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metered_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "journal_entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("journal_entries.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "billable_seconds >= 0", name="ck_call_charges_seconds_not_negative"
        ),
        sa.CheckConstraint(
            "charged_amount = setup_amount + usage_amount",
            name="ck_call_charges_total_is_its_parts",
        ),
        sa.CheckConstraint(
            "(metered_to IS NULL AND metered_from IS NULL) "
            "OR (metered_to IS NOT NULL AND metered_from IS NOT NULL "
            "AND metered_to >= metered_from)",
            name="ck_call_charges_metered_window",
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_call_charges_currency_iso4217"
        ),
    )
    op.create_index(
        "ux_call_charges_live",
        "call_charges",
        ["attempt_id"],
        unique=True,
        postgresql_where=sa.text("state <> 'superseded'"),
    )
    op.create_index("ix_call_charges_attempt", "call_charges", ["attempt_id"])

    op.create_table(
        "call_supplier_costs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("call_attempts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "leg_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("call_legs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_reference", sa.String(200), nullable=False),
        sa.Column(
            "component",
            postgresql.ENUM(name="call_supplier_cost_component", create_type=False),
            nullable=False,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("billable_seconds", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "superseded_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("call_supplier_costs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "provider",
            "provider_reference",
            "component",
            name="uq_call_supplier_costs_reference",
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_call_supplier_costs_currency_iso4217"
        ),
    )
    op.create_index(
        "ix_call_supplier_costs_attempt", "call_supplier_costs", ["attempt_id"]
    )

    op.create_table(
        "call_deadlines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("call_attempts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "kind",
            postgresql.ENUM(name="call_deadline_kind", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "state",
            postgresql.ENUM(name="call_deadline_state", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_detail", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempts >= 0", name="ck_call_deadlines_attempts"),
    )
    op.create_index(
        "ux_call_deadlines_open",
        "call_deadlines",
        ["attempt_id", "kind"],
        unique=True,
        postgresql_where=sa.text("state IN ('pending', 'claimed')"),
    )
    op.create_index("ix_call_deadlines_due", "call_deadlines", ["state", "due_at"])


def downgrade() -> None:
    """Drops only what `upgrade` created.

    The five `exception_kind` values stay. PostgreSQL cannot remove an enum
    label without rewriting the type, and a queue row that named one would lose
    the only word describing why a human was called — `AGENTS.md` is explicit
    that audit history is not erased because a surface was removed.

    Dropping `call_charges` discards settlement records, so this belongs in a
    development rollback and not in a production procedure: the journal entries
    those charges posted remain, and the books would no longer name what they
    were for.
    """
    op.drop_table("call_deadlines")
    op.drop_table("call_supplier_costs")
    op.drop_table("call_charges")
    bind = op.get_bind()
    for name, _ in _NEW_ENUMS:
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
