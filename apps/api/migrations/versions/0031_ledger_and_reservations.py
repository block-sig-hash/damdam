"""Multi-currency ledger and atomic reservations — US-32, chunk 10.

Revision ID: 0031_ledger_and_reservations
Revises: 0030_catalog_and_quotes

Additive. `packages`, `transactions` and their NGN columns are untouched: the
legacy purchase path keeps working exactly as it does, and chunk 11 is what
moves new purchases onto these tables.

**No backfill runs here.** `app/ledger/backfill.py` posts the legacy history and
returns a reconciliation report, and it is deliberately a separate, re-runnable
operation rather than a migration step. A backfill inside a migration runs once,
in a transaction nobody is watching, with no report anyone reads — and this one
makes a judgement worth reviewing: it records revenue and creates **no** service
credit, because the legacy product had no wallet and inventing one would put a
liability on the books that no event produced.

The four triggers are the substance:

- `trg_journal_entries_balance` is a **deferred constraint** trigger, checked at
  COMMIT. An entry's lines are inserted one at a time, so a per-statement check
  would fail on the first line of every balanced entry. Deferred also means a
  half-written entry cannot survive a crash.
- `trg_journal_lines_balance` reruns that deferred check for every appended
  line and compares the actual count with the entry's frozen expected count.
- `trg_journal_entries_immutable` / `trg_journal_lines_immutable` refuse UPDATE
  and DELETE outright. A correction is a new, opposite entry — never an edit.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031_ledger_and_reservations"
down_revision: str | None = "0030_catalog_and_quotes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUMS = (
    ("ledger_owner_kind", ("user", "organization", "system")),
    (
        "ledger_account_kind",
        (
            "service_credit",
            "reserved",
            "consumed",
            "revenue",
            "settlement_clearing",
            "adjustment",
        ),
    ),
    ("ledger_direction", ("debit", "credit")),
    ("reservation_state", ("held", "released", "settled")),
)

_BALANCE_TRIGGER = """
CREATE OR REPLACE FUNCTION damdam_journal_balances() RETURNS trigger AS $$
DECLARE
    target_entry_id uuid;
    expected_line_count integer;
    imbalance numeric;
    actual_line_count integer;
BEGIN
    IF TG_TABLE_NAME = 'journal_entries' THEN
        target_entry_id := NEW.id;
    ELSE
        target_entry_id := NEW.entry_id;
    END IF;

    SELECT line_count INTO expected_line_count
    FROM journal_entries
    WHERE id = target_entry_id;

    SELECT
        COALESCE(SUM(CASE WHEN direction = 'debit' THEN amount ELSE -amount END), 0),
        COUNT(*)
    INTO imbalance, actual_line_count
    FROM journal_lines
    WHERE entry_id = target_entry_id;

    IF actual_line_count = 0 THEN
        RAISE EXCEPTION 'journal entry % has no lines', target_entry_id;
    END IF;
    IF actual_line_count <> expected_line_count THEN
        RAISE EXCEPTION
            'journal entry % expected % lines but has %',
            target_entry_id, expected_line_count, actual_line_count;
    END IF;
    IF imbalance <> 0 THEN
        RAISE EXCEPTION
            'journal entry % does not balance: debits minus credits = %',
            target_entry_id, imbalance;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_journal_entries_balance
    AFTER INSERT ON journal_entries
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION damdam_journal_balances();

CREATE CONSTRAINT TRIGGER trg_journal_lines_balance
    AFTER INSERT ON journal_lines
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION damdam_journal_balances();
"""

_IMMUTABLE_TRIGGERS = """
CREATE OR REPLACE FUNCTION damdam_journal_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'posted journal history is immutable; post a compensating entry instead';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_journal_entries_immutable
    BEFORE UPDATE OR DELETE ON journal_entries
    FOR EACH ROW EXECUTE FUNCTION damdam_journal_immutable();

CREATE TRIGGER trg_journal_lines_immutable
    BEFORE UPDATE OR DELETE ON journal_lines
    FOR EACH ROW EXECUTE FUNCTION damdam_journal_immutable();
"""


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _ENUMS:
        postgresql.ENUM(*values, name=name, create_type=True).create(
            bind, checkfirst=True
        )

    op.create_table(
        "ledger_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_kind",
            postgresql.ENUM(name="ledger_owner_kind", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "owner_organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(name="ledger_account_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # The composite target journal lines point at, so a line's currency is
        # its account's by foreign key rather than by convention.
        sa.UniqueConstraint("id", "currency", name="uq_ledger_accounts_id_currency"),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_ledger_accounts_currency_iso4217"
        ),
        sa.CheckConstraint(
            "(owner_kind = 'user' AND owner_user_id IS NOT NULL "
            "AND owner_organization_id IS NULL) "
            "OR (owner_kind = 'organization' AND owner_organization_id IS NOT NULL "
            "AND owner_user_id IS NULL) "
            "OR (owner_kind = 'system' AND owner_user_id IS NULL "
            "AND owner_organization_id IS NULL)",
            name="ck_ledger_accounts_owner",
        ),
    )
    op.create_index(
        "ix_ledger_accounts_owner",
        "ledger_accounts",
        ["owner_kind", "currency", "kind"],
    )
    op.create_index(
        "uq_ledger_accounts_system_identity",
        "ledger_accounts",
        ["currency", "kind"],
        unique=True,
        postgresql_where=sa.text("owner_kind = 'system'"),
    )
    op.create_index(
        "uq_ledger_accounts_user_identity",
        "ledger_accounts",
        ["owner_user_id", "currency", "kind"],
        unique=True,
        postgresql_where=sa.text("owner_kind = 'user'"),
    )
    op.create_index(
        "uq_ledger_accounts_organization_identity",
        "ledger_accounts",
        ["owner_organization_id", "currency", "kind"],
        unique=True,
        postgresql_where=sa.text("owner_kind = 'organization'"),
    )

    op.create_table(
        "journal_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # Unique, and that single constraint is what makes the whole ledger
        # replay-safe: a webhook delivered twice or a retried worker fails here
        # instead of crediting twice.
        sa.Column("business_event_id", sa.String(200), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference", sa.String(500), nullable=True),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("business_event_id", name="uq_journal_entries_event"),
        sa.UniqueConstraint("id", "currency", name="uq_journal_entries_id_currency"),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_journal_entries_currency_iso4217"
        ),
    )
    op.create_index("ix_journal_entries_occurred", "journal_entries", ["occurred_at"])

    op.create_table(
        "journal_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "direction",
            postgresql.ENUM(name="ledger_direction", create_type=False),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        # Two composite foreign keys, one reason: a line cannot be in a
        # currency that differs from its entry's or its account's, so a
        # cross-currency entry is impossible rather than merely refused.
        sa.ForeignKeyConstraint(
            ["entry_id", "currency"],
            ["journal_entries.id", "journal_entries.currency"],
            name="fk_journal_lines_entry_currency",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "currency"],
            ["ledger_accounts.id", "ledger_accounts.currency"],
            name="fk_journal_lines_account_currency",
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_journal_lines_currency_iso4217"
        ),
        # Amounts are always positive; direction carries the sign. A negative
        # debit and a positive credit are one posting written two ways, and one
        # of them will eventually be summed wrongly.
        sa.CheckConstraint("amount > 0", name="ck_journal_lines_amount_positive"),
    )
    op.create_index("ix_journal_lines_account", "journal_lines", ["account_id"])
    op.create_index("ix_journal_lines_entry", "journal_lines", ["entry_id"])

    op.create_table(
        "ledger_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("business_event_id", sa.String(200), nullable=False),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ledger_accounts.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("settled_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("released_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "state",
            postgresql.ENUM(name="reservation_state", create_type=False),
            nullable=False,
            server_default="held",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "business_event_id", name="uq_ledger_reservations_event"
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_ledger_reservations_currency_iso4217"
        ),
        sa.CheckConstraint("amount > 0", name="ck_ledger_reservations_amount"),
        # Partial settlement is normal -- a call reserves a maximum and settles
        # what it cost -- so what must hold is that the parts never exceed the
        # whole.
        sa.CheckConstraint(
            "settled_amount >= 0 AND released_amount >= 0 "
            "AND settled_amount + released_amount <= amount",
            name="ck_ledger_reservations_disposition",
        ),
        sa.CheckConstraint(
            "(state = 'held' AND closed_at IS NULL) "
            "OR (state <> 'held' AND closed_at IS NOT NULL)",
            name="ck_ledger_reservations_closed_at",
        ),
    )
    op.create_index(
        "ix_ledger_reservations_open",
        "ledger_reservations",
        ["account_id", "state"],
        postgresql_where=sa.text("state = 'held'"),
    )

    op.execute(sa.text(_BALANCE_TRIGGER))
    op.execute(sa.text(_IMMUTABLE_TRIGGERS))


def downgrade() -> None:
    bind = op.get_bind()
    for statement in (
        "DROP TRIGGER IF EXISTS trg_journal_lines_immutable ON journal_lines",
        "DROP TRIGGER IF EXISTS trg_journal_lines_balance ON journal_lines",
        "DROP TRIGGER IF EXISTS trg_journal_entries_immutable ON journal_entries",
        "DROP TRIGGER IF EXISTS trg_journal_entries_balance ON journal_entries",
        "DROP FUNCTION IF EXISTS damdam_journal_immutable()",
        "DROP FUNCTION IF EXISTS damdam_journal_balances()",
    ):
        op.execute(sa.text(statement))
    for table in (
        "ledger_reservations",
        "journal_lines",
        "journal_entries",
        "ledger_accounts",
    ):
        op.drop_table(table)
    for name, _ in _ENUMS:
        postgresql.ENUM(name=name, create_type=False).drop(bind, checkfirst=True)
