"""Usage records, counter readings and durable polling cursors (US-36, chunk 16).

Three tables, and each exists because of a specific way usage accounting goes
wrong.

**`usage_records`** is the normalised, deduplicated fact: this line consumed this
much, between these times, and we learned about it then. It is append-only. A
supplier correction does not edit a record — it writes a new one that supersedes
the old, exactly as chunk 10's ledger posts a compensating entry rather than
rewriting history. Editing a usage row would make "why is my balance this
number" unanswerable, which is the same reason the ledger refuses updates.

**`counter_readings`** keeps the raw cumulative values a counter-based supplier
reports. It has to exist separately, because a delta can only be computed
against the previous reading and a reading is not itself a consumption fact. It
is also the only way to recognise a **counter reset**: the value going down
means either a new billing cycle or something wrong, and without the history
there is nothing to compare against.

**`usage_cursors`** is the durable watermark for polling. A cursor held in
memory is a cursor that restarts at zero after a deploy, and a poller that
restarts at zero either re-ingests a month of usage or skips it. Neither is
recoverable by hand.

## Carrier usage and internet usage are not the same fact

The approved calling amendment (`VOICE-EXPANSION.md`, 9 September 2026) requires
this chunk to *"coordinate usage provenance… to avoid cross-source double
charging"* and states plainly that *"WebRTC CDRs cannot prove native-carrier
usage or spending caps"*, and that internet calling *"must not require an eSIM
installation or carrier line foreign key"*.

So `usage_records.channel` names which world a record came from, and
`carrier_line_id` is **nullable** with a constraint tying the two together: a
carrier record names a line, an internet record must not. An internet call
record therefore cannot be counted as evidence about a carrier line — not
because a query remembers to exclude it, but because it has no line to be
counted against.

Chunk 16 ingests the carrier channel. V03 owns internet metering and settlement;
this schema is shaped so it does not have to migrate these tables to add it.

## The rule that stops double-charging across sources

A supplier can report the *same bytes* twice — once in its cumulative counter and
once in a session record. `carrier_lines` therefore gets one authoritative data
source per line, and everything from the other source is stored as **evidence**:
kept, compared, never charged. `AGENTS.md`'s "avoid charging the same data via
two sources" is not a rule somebody remembers here; it is a column.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now
from app.connectivity.contract import AdapterChannel
from app.money import currency_check, currency_column, money_column
from app.usage.contract import UsageKind


def _enum(
    enum_type: type[Enum], name: str, default: Enum | None = None
) -> "Column[Any]":
    return Column(
        SAEnum(
            enum_type,
            name=name,
            values_callable=lambda choices: [choice.value for choice in choices],
        ),
        nullable=False,
        server_default=None if default is None else default.value,
    )


class UsageSource(str, Enum):
    """Where a usage fact came from. Not interchangeable.

    A counter is cumulative and resets; events are incremental and arrive late.
    Recording which one a record came from is what lets a discrepancy be
    investigated rather than averaged.
    """

    COUNTER = "counter"
    EVENT = "event"
    #: Written by us, not observed: a correction, or the closing delta when a
    #: counter resets. Marked so nobody mistakes it for something a supplier
    #: said.
    DERIVED = "derived"


class UsageState(str, Enum):
    """What a usage record is worth right now.

    `PROVISIONAL` versus `FINAL` is the distinction the assignment asks for and
    the one a customer sees: a counter reading is an estimate that the next
    poll may revise, while a settled session record is what the supplier will
    invoice us for. Presenting the first as the second is what
    `prd.md` AC-36.4 forbids.
    """

    PROVISIONAL = "provisional"
    FINAL = "final"
    #: Replaced by a correction. Kept, never deleted: the old number explains
    #: what a customer was told last week.
    SUPERSEDED = "superseded"
    #: From the non-authoritative source for this line. Counted for
    #: reconciliation, never charged.
    EVIDENCE = "evidence"


class CursorState(str, Enum):
    ACTIVE = "active"
    #: Catching up over a window that was missed. Distinct from ACTIVE because
    #: a backfilling cursor must not also advance the live watermark.
    BACKFILLING = "backfilling"
    #: Too many consecutive failures. Parked for a human rather than retried
    #: forever, and loudly, because a silently stalled usage poller is a
    #: customer whose balance stopped moving and nobody noticed.
    STALLED = "stalled"


class UsageCursor(SQLModel, table=True):
    """Where polling got to, durably.

    `position_at` is a **watermark, not a bookmark**: it is the point up to
    which we believe we have everything, and it only moves when a poll actually
    covered the window it claims. A cursor advanced past a window the supplier
    did not report is usage that no later poll will ever look for again.
    """

    __tablename__ = "usage_cursors"
    __table_args__ = (
        UniqueConstraint(
            "provider", "stream", "scope_reference", name="uq_usage_cursors_identity"
        ),
        CheckConstraint(
            "consecutive_failures >= 0", name="ck_usage_cursors_failures"
        ),
        CheckConstraint(
            "(state = 'backfilling' AND backfill_from IS NOT NULL "
            "AND backfill_to IS NOT NULL) "
            "OR (state <> 'backfilling' AND backfill_from IS NULL "
            "AND backfill_to IS NULL)",
            name="ck_usage_cursors_backfill_window",
        ),
        Index("ix_usage_cursors_state", "state", "position_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    provider: str = Field(sa_column=Column(String(32), nullable=False))
    #: `data_counter`, `data_events`, `voice_events` — one cursor per stream,
    #: because they advance independently and a shared one would drag the
    #: fastest back to the slowest.
    stream: str = Field(sa_column=Column(String(50), nullable=False))
    #: A line, an account, a SIM group — whatever the supplier scopes its
    #: reporting to. Empty string rather than null so the unique constraint
    #: works: in PostgreSQL, two rows with a null are not duplicates.
    scope_reference: str = Field(
        sa_column=Column(String(200), nullable=False, server_default="")
    )
    position_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    state: CursorState = Field(
        default=CursorState.ACTIVE,
        sa_column=_enum(CursorState, "usage_cursor_state", CursorState.ACTIVE),
    )
    backfill_from: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    backfill_to: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: The supplier's own pagination handle, opaque. Reconstructing pagination
    #: from offsets loses records when the supplier's ordering changes.
    provider_cursor: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    last_polled_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_success_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    consecutive_failures: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    last_error: str | None = Field(
        default=None, sa_column=Column(String(1000), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class CounterReading(SQLModel, table=True):
    """One raw cumulative reading. Not a consumption fact by itself.

    Kept because a delta needs a predecessor, and because a reset is only
    visible as a comparison. `value_bytes` is exactly what the supplier said,
    unconverted and unrounded, so a disagreement about a customer's balance can
    be traced back to a number somebody can quote at the supplier.
    """

    __tablename__ = "usage_counter_readings"
    __table_args__ = (
        UniqueConstraint(
            "carrier_line_id", "observed_at", name="uq_counter_readings_observation"
        ),
        CheckConstraint("value_bytes >= 0", name="ck_counter_readings_not_negative"),
        Index("ix_counter_readings_line", "carrier_line_id", "observed_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    carrier_line_id: UUID = Field(
        sa_column=Column(
            ForeignKey("carrier_lines.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    value_bytes: int = Field(sa_column=Column(BigInteger, nullable=False))
    #: The supplier's billing period, when it names one. Telnyx does not, which
    #: is why the reset handling cannot rely on it.
    cycle_reference: str | None = Field(
        default=None, sa_column=Column(String(100), nullable=True)
    )
    observed_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    received_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class UsageRecord(SQLModel, table=True):
    """One deduplicated consumption fact, attributed to one line.

    `natural_key` is the deduplication handle and it is **required**. A supplier
    event id is used when there is one; Telnyx publishes no WDR record id, so
    the ingester composes a key from the fields that *are* documented — line,
    start, end, quantity. That composite is not perfect, and its imperfection is
    recorded rather than hidden: two genuinely distinct sessions with identical
    boundaries and volume collapse into one, which under-counts. Under-counting
    in the customer's favour is the right direction to be wrong when the
    supplier will not give us an id.

    Append-only. A correction writes a new row pointing at the old one; the old
    row becomes `SUPERSEDED` and keeps its numbers, because "what were they told
    last week" has to stay answerable.
    """

    __tablename__ = "usage_records"
    __table_args__ = (
        currency_check("usage_records", "charged_currency"),
        # The calling amendment, as a constraint. A carrier record names the
        # line it was measured on; an internet record has no line and must not
        # borrow one, because a WebRTC call proves nothing about whether a
        # handset can attach to a visited network.
        CheckConstraint(
            "(channel = 'carrier' AND carrier_line_id IS NOT NULL) "
            "OR (channel = 'internet' AND carrier_line_id IS NULL)",
            name="ck_usage_records_channel_line",
        ),
        UniqueConstraint(
            "provider", "natural_key", name="uq_usage_records_natural_key"
        ),
        CheckConstraint("quantity >= 0", name="ck_usage_records_quantity"),
        CheckConstraint(
            "occurred_to >= occurred_from", name="ck_usage_records_window"
        ),
        CheckConstraint(
            "(charged_amount IS NULL AND charged_currency IS NULL) "
            "OR (charged_amount IS NOT NULL AND charged_currency IS NOT NULL)",
            name="ck_usage_records_charge_pair",
        ),
        CheckConstraint(
            "charged_amount IS NULL OR charged_amount >= 0",
            name="ck_usage_records_charge_not_negative",
        ),
        # A correction must point at what it corrects, and nothing else may.
        CheckConstraint(
            "(source = 'derived') OR corrects_id IS NULL",
            name="ck_usage_records_corrections_are_derived",
        ),
        Index(
            "ix_usage_records_line_state", "carrier_line_id", "state", "occurred_from"
        ),
        Index("ix_usage_records_channel", "channel", "occurred_from"),
        Index("ix_usage_records_entitlement", "entitlement_id", "state"),
        # Finding what a correction replaced, cheaply.
        Index(
            "ix_usage_records_corrects",
            "corrects_id",
            postgresql_where=text("corrects_id IS NOT NULL"),
            sqlite_where=text("corrects_id IS NOT NULL"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    #: Which world this came from. Not derivable from `source`: a counter and a
    #: session record both exist on the carrier side, and V03's internet
    #: metering will have its own event stream.
    channel: AdapterChannel = Field(
        default=AdapterChannel.CARRIER,
        sa_column=_enum(AdapterChannel, "adapter_channel", AdapterChannel.CARRIER),
    )
    #: Null for internet usage, which has no carrier line and must not be given
    #: one. Required for carrier usage, by the constraint above.
    carrier_line_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("carrier_lines.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
    )
    #: Denormalised from the line's entitlement so an allowance query does not
    #: have to join through three tables on every balance read. Set once, at
    #: ingest, from the line -- never supplied by a caller.
    entitlement_id: UUID = Field(
        sa_column=Column(
            ForeignKey("entitlements.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
    )
    provider: str = Field(sa_column=Column(String(32), nullable=False))
    kind: UsageKind = Field(sa_column=_enum(UsageKind, "usage_kind"))
    source: UsageSource = Field(sa_column=_enum(UsageSource, "usage_source"))
    state: UsageState = Field(
        default=UsageState.PROVISIONAL,
        sa_column=_enum(UsageState, "usage_state", UsageState.PROVISIONAL),
    )
    #: The supplier's id when it issues one. Null is common and not a defect.
    provider_event_id: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    natural_key: str = Field(sa_column=Column(String(300), nullable=False))
    #: Bytes for data, seconds for voice. BigInteger: a 5 GB session does not
    #: fit in 32 bits.
    quantity: int = Field(sa_column=Column(BigInteger, nullable=False))
    occurred_from: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    occurred_to: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    #: When we learned. `occurred_to` minus this is how late the supplier was,
    #: which is the number a stale balance is stale by.
    received_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    #: The exact tariff version a voice charge was priced from. Pinned, not
    #: referenced by product: a rate change must not reprice a past call.
    tariff_id: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("tariffs.id"), nullable=True, index=True),
    )
    charged_currency: str | None = Field(
        default=None, sa_column=currency_column(nullable=True)
    )
    charged_amount: Decimal | None = Field(
        default=None, sa_column=money_column(nullable=True)
    )
    #: Set on the *correcting* row, pointing at what it replaces.
    corrects_id: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("usage_records.id"), nullable=True),
    )
    #: Why this row exists, when it is not simply "the supplier said so".
    note: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
