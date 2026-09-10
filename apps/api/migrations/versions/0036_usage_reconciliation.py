"""Usage records, counter readings and durable polling cursors — US-36.

Revision ID: 0036_usage_reconciliation
Revises: 0035_connectivity_line_lifecycle

Additive. Nothing is seeded, no existing row is touched, and the one added
column is nullable.

Four constraints carry the chunk's guarantees:

- `uq_usage_records_natural_key` — the same supplier record cannot be counted
  twice, however many times it is redelivered or replayed. Suppliers redeliver;
  this is what makes that harmless rather than expensive.
- `ck_usage_records_channel_line` — a carrier record names the line it was
  measured on; an internet record has none and must not borrow one. The approved
  calling amendment requires both halves: internet calling must not depend on a
  carrier line foreign key, and *"WebRTC CDRs cannot prove native-carrier usage
  or spending caps"*. Chunk 16 ingests only the carrier channel; the column
  exists so V03 does not have to migrate this table to add the other.
- `ck_usage_records_corrections_are_derived` — only a record we wrote may claim
  to correct another. A supplier feed cannot rewrite history by asserting a
  `corrects_id`.
- `uq_counter_readings_observation` — one reading per line per observation
  timestamp, so a replayed poll cannot manufacture a second delta out of the
  same cumulative number.
- `ck_usage_cursors_backfill_window` — a cursor claiming to be backfilling must
  name the window. A backfill with no window is a cursor that has stopped
  advancing and cannot say what it is catching up on.

`carrier_lines.authoritative_data_source` is nullable and unset. A supplier can
report the same bytes twice — once in a cumulative counter, once in a session
record — and counting both charges a customer twice for one megabyte. Choosing
which source counts is a deliberate act, so the column starts empty rather than
defaulting to whichever poll runs first.

**`exception_kind` gains three values.** `ALTER TYPE … ADD VALUE` is used rather
than a type rebuild: rebuilding would rewrite every `exception_items` row and
take an exclusive lock on a table chunk 25 will be reading. The new values are
not *used* in this migration, which is the condition PostgreSQL places on adding
them inside a transaction.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036_usage_reconciliation"
down_revision: str | None = "0035_connectivity_line_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUMS = (
    ("adapter_channel", ("carrier", "internet")),
    ("usage_kind", ("data", "voice")),
    ("usage_source", ("counter", "event", "derived")),
    ("usage_state", ("provisional", "final", "superseded", "evidence")),
    ("usage_cursor_state", ("active", "backfilling", "stalled")),
)

_NEW_EXCEPTION_KINDS = (
    "usage_counter_reset",
    "usage_discrepancy",
    "usage_polling_stalled",
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _ENUMS:
        postgresql.ENUM(*values, name=name, create_type=True).create(
            bind, checkfirst=True
        )
    for value in _NEW_EXCEPTION_KINDS:
        op.execute(f"ALTER TYPE exception_kind ADD VALUE IF NOT EXISTS '{value}'")

    op.add_column(
        "carrier_lines",
        sa.Column("authoritative_data_source", sa.String(16), nullable=True),
    )

    op.create_table(
        "usage_cursors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("stream", sa.String(50), nullable=False),
        # Empty string rather than null: in PostgreSQL two rows carrying a null
        # are not duplicates, so a nullable column here would let the same
        # stream be registered twice.
        sa.Column(
            "scope_reference", sa.String(200), nullable=False, server_default=""
        ),
        sa.Column("position_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "state",
            postgresql.ENUM(name="usage_cursor_state", create_type=False),
            nullable=False,
            server_default="active",
        ),
        sa.Column("backfill_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("backfill_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_cursor", sa.String(500), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "consecutive_failures", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("last_error", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider", "stream", "scope_reference", name="uq_usage_cursors_identity"
        ),
        sa.CheckConstraint(
            "consecutive_failures >= 0", name="ck_usage_cursors_failures"
        ),
        sa.CheckConstraint(
            "(state = 'backfilling' AND backfill_from IS NOT NULL "
            "AND backfill_to IS NOT NULL) "
            "OR (state <> 'backfilling' AND backfill_from IS NULL "
            "AND backfill_to IS NULL)",
            name="ck_usage_cursors_backfill_window",
        ),
    )
    op.create_index(
        "ix_usage_cursors_state", "usage_cursors", ["state", "position_at"]
    )

    op.create_table(
        "usage_counter_readings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "carrier_line_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("carrier_lines.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("value_bytes", sa.BigInteger(), nullable=False),
        sa.Column("cycle_reference", sa.String(100), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "carrier_line_id", "observed_at", name="uq_counter_readings_observation"
        ),
        sa.CheckConstraint("value_bytes >= 0", name="ck_counter_readings_not_negative"),
    )
    op.create_index(
        "ix_counter_readings_line",
        "usage_counter_readings",
        ["carrier_line_id", "observed_at"],
    )

    op.create_table(
        "usage_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "channel",
            postgresql.ENUM(name="adapter_channel", create_type=False),
            nullable=False,
            server_default="carrier",
        ),
        # Nullable, and constrained below. The calling amendment requires that
        # internet calling not depend on a carrier line foreign key, and that a
        # WebRTC record never stand as evidence about a carrier line.
        sa.Column(
            "carrier_line_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("carrier_lines.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "entitlement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entitlements.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(name="usage_kind", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "source",
            postgresql.ENUM(name="usage_source", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "state",
            postgresql.ENUM(name="usage_state", create_type=False),
            nullable=False,
            server_default="provisional",
        ),
        sa.Column("provider_event_id", sa.String(200), nullable=True),
        sa.Column("natural_key", sa.String(300), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("occurred_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurred_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "tariff_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tariffs.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("charged_currency", sa.String(3), nullable=True),
        sa.Column("charged_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column(
            "corrects_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usage_records.id"),
            nullable=True,
        ),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider", "natural_key", name="uq_usage_records_natural_key"
        ),
        sa.CheckConstraint(
            "charged_currency IS NULL OR charged_currency ~ '^[A-Z]{3}$'",
            name="ck_usage_records_charged_currency_iso4217",
        ),
        sa.CheckConstraint(
            "(channel = 'carrier' AND carrier_line_id IS NOT NULL) "
            "OR (channel = 'internet' AND carrier_line_id IS NULL)",
            name="ck_usage_records_channel_line",
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_usage_records_quantity"),
        sa.CheckConstraint(
            "occurred_to >= occurred_from", name="ck_usage_records_window"
        ),
        sa.CheckConstraint(
            "(charged_amount IS NULL AND charged_currency IS NULL) "
            "OR (charged_amount IS NOT NULL AND charged_currency IS NOT NULL)",
            name="ck_usage_records_charge_pair",
        ),
        sa.CheckConstraint(
            "charged_amount IS NULL OR charged_amount >= 0",
            name="ck_usage_records_charge_not_negative",
        ),
        sa.CheckConstraint(
            "(source = 'derived') OR corrects_id IS NULL",
            name="ck_usage_records_corrections_are_derived",
        ),
    )
    op.create_index(
        "ix_usage_records_line_state",
        "usage_records",
        ["carrier_line_id", "state", "occurred_from"],
    )
    op.create_index(
        "ix_usage_records_entitlement", "usage_records", ["entitlement_id", "state"]
    )
    op.create_index(
        "ix_usage_records_channel", "usage_records", ["channel", "occurred_from"]
    )
    op.create_index(
        "ix_usage_records_corrects",
        "usage_records",
        ["corrects_id"],
        postgresql_where=sa.text("corrects_id IS NOT NULL"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_table("usage_records")
    op.drop_table("usage_counter_readings")
    op.drop_table("usage_cursors")
    op.drop_column("carrier_lines", "authoritative_data_source")
    for name, _ in _ENUMS:
        postgresql.ENUM(name=name, create_type=False).drop(bind, checkfirst=True)
    # The three `exception_kind` values stay. PostgreSQL cannot remove an enum
    # value, and rebuilding the type to drop them would rewrite every
    # `exception_items` row for no benefit — an unused value costs nothing, and
    # a downgrade that rewrites a table nobody asked it to touch is a worse
    # trade than a slightly wider enum.
