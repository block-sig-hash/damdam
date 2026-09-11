"""Double-entry ledger and reservations (US-32, chunk 10).

The legacy accounting was a `Decimal` column on `packages` that code decremented.
That shape cannot answer the two questions an accounting system exists for —
*why* is the balance this number, and does it still add up — and it loses money
silently the first time two requests decrement it at once.

This is an ordinary double-entry ledger, with the properties that make one
trustworthy each enforced by the database rather than promised by a service:

| Property | Enforced by |
|---|---|
| Every entry balances, **per currency** | A deferred constraint trigger, at commit |
| Nothing posted is ever edited | An immutability trigger on entries and lines |
| One business event posts once | A unique constraint on `business_event_id` |
| No cross-currency arithmetic | A line's currency is its account's, by composite FK |
| A reservation cannot overspend | `SELECT … FOR UPDATE`, tested under concurrency |

The deferred check is the interesting one. A balanced entry cannot be written by
a single statement — the lines go in one at a time — so the constraint has to be
checked when the transaction commits rather than as each row lands. `DEFERRABLE
INITIALLY DEFERRED` is exactly that, and it means a half-written entry cannot
survive a crash: either the whole balanced entry commits or none of it does.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DDL,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.schema import Table
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now
from app.money import currency_check, currency_column, money_column


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


class OwnerKind(str, Enum):
    USER = "user"
    ORGANIZATION = "organization"
    #: Accounts that belong to DamDam rather than to a customer — revenue,
    #: processor clearing, and the counterpart of every customer credit.
    SYSTEM = "system"


class AccountKind(str, Enum):
    """What an account is for, and which way its balance naturally runs.

    `SERVICE_CREDIT` is deliberately not called a wallet. It is **closed-loop**:
    it buys DamDam connectivity and nothing else. There is no transfer between
    customers, no cash-out and no foreign-exchange engine, because each of those
    turns a prepaid balance into a money-transmission product with an entirely
    different licensing conversation attached.
    """

    #: Money a customer has funded and we owe them service for. A liability.
    SERVICE_CREDIT = "service_credit"
    #: Held against a pending purchase. Still theirs, not yet spent.
    RESERVED = "reserved"
    #: Spent. The counterpart of a settlement.
    CONSUMED = "consumed"
    #: Ours, once service is delivered.
    REVENUE = "revenue"
    #: Money in flight at a processor: charged but not yet settled to us.
    SETTLEMENT_CLEARING = "settlement_clearing"
    #: Corrections. Never an edit to history -- a new, opposite entry.
    ADJUSTMENT = "adjustment"


class Direction(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


#: Which side increases each kind of account. Balances are reported signed in
#: this direction, so a customer holding 1,000 of credit reads as `1000` rather
#: than as `-1000` because a liability is credit-natured.
NATURAL_SIDE: dict[AccountKind, Direction] = {
    AccountKind.SERVICE_CREDIT: Direction.CREDIT,
    AccountKind.REVENUE: Direction.CREDIT,
    AccountKind.RESERVED: Direction.DEBIT,
    AccountKind.CONSUMED: Direction.DEBIT,
    AccountKind.SETTLEMENT_CLEARING: Direction.DEBIT,
    AccountKind.ADJUSTMENT: Direction.DEBIT,
}


class LedgerAccount(SQLModel, table=True):
    """One account, for one owner, in exactly one currency.

    Currency is part of the account's identity rather than a property of each
    posting. That is what makes "do not add unrelated currency balances"
    structural: there is no account that holds two currencies, so there is no
    balance that could mix them.
    """

    __tablename__ = "ledger_accounts"
    __table_args__ = (
        currency_check("ledger_accounts"),
        # PostgreSQL UNIQUE constraints treat NULLs as distinct. Separate
        # owner-shaped indexes are therefore required to make get-or-create
        # identity real for system, user and organization accounts alike.
        Index(
            "uq_ledger_accounts_system_identity",
            "currency",
            "kind",
            unique=True,
            postgresql_where=text("owner_kind = 'system'"),
            sqlite_where=text("owner_kind = 'system'"),
        ),
        Index(
            "uq_ledger_accounts_user_identity",
            "owner_user_id",
            "currency",
            "kind",
            unique=True,
            postgresql_where=text("owner_kind = 'user'"),
            sqlite_where=text("owner_kind = 'user'"),
        ),
        Index(
            "uq_ledger_accounts_organization_identity",
            "owner_organization_id",
            "currency",
            "kind",
            unique=True,
            postgresql_where=text("owner_kind = 'organization'"),
            sqlite_where=text("owner_kind = 'organization'"),
        ),
        # Composite target for journal lines, so a line's currency is the
        # account's currency by foreign key rather than by convention.
        UniqueConstraint("id", "currency", name="uq_ledger_accounts_id_currency"),
        CheckConstraint(
            "(owner_kind = 'user' AND owner_user_id IS NOT NULL "
            "AND owner_organization_id IS NULL) "
            "OR (owner_kind = 'organization' AND owner_organization_id IS NOT NULL "
            "AND owner_user_id IS NULL) "
            "OR (owner_kind = 'system' AND owner_user_id IS NULL "
            "AND owner_organization_id IS NULL)",
            name="ck_ledger_accounts_owner",
        ),
        Index("ix_ledger_accounts_owner", "owner_kind", "currency", "kind"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    owner_kind: OwnerKind = Field(sa_column=_enum(OwnerKind, "ledger_owner_kind"))
    owner_user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
        ),
    )
    owner_organization_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
    )
    currency: str = Field(sa_column=currency_column())
    kind: AccountKind = Field(sa_column=_enum(AccountKind, "ledger_account_kind"))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class JournalEntry(SQLModel, table=True):
    """One balanced, immutable posting, caused by exactly one business event.

    `business_event_id` is unique, and that single constraint is what makes the
    whole ledger replay-safe: a webhook delivered twice, a retried worker or a
    reordered message all try to post the same event id, and the second one
    fails on the constraint instead of crediting twice.
    """

    __tablename__ = "journal_entries"
    __table_args__ = (
        currency_check("journal_entries"),
        UniqueConstraint("business_event_id", name="uq_journal_entries_event"),
        UniqueConstraint("id", "currency", name="uq_journal_entries_id_currency"),
        Index("ix_journal_entries_occurred", "occurred_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    #: Caller-supplied and meaningful: `order:<id>:capture`, not a random UUID.
    #: A random id per attempt would make every retry a new event and defeat
    #: the constraint above.
    business_event_id: str = Field(sa_column=Column(String(200), nullable=False))
    currency: str = Field(sa_column=currency_column())
    #: When the event happened, which is not when we wrote it down. A settlement
    #: report arriving three days late posts with the date it describes.
    occurred_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    recorded_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    reference: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    # Freezes the complete set of lines. Without an expected count, immutable
    # rows can still acquire new lines after the original entry commits.
    line_count: int = Field(sa_column=Column(Integer, nullable=False))


class JournalLine(SQLModel, table=True):
    __tablename__ = "journal_lines"
    __table_args__ = (
        currency_check("journal_lines"),
        # Both composite foreign keys exist for one reason: a line cannot be in
        # a currency that differs from its entry's or its account's. Mixing
        # currencies inside one entry is impossible rather than merely refused.
        ForeignKeyConstraint(
            ["entry_id", "currency"],
            ["journal_entries.id", "journal_entries.currency"],
            name="fk_journal_lines_entry_currency",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["account_id", "currency"],
            ["ledger_accounts.id", "ledger_accounts.currency"],
            name="fk_journal_lines_account_currency",
        ),
        # Amounts are always positive; `direction` carries the sign. A negative
        # debit and a positive credit are the same posting written two ways,
        # and one of them will eventually be summed wrongly.
        CheckConstraint("amount > 0", name="ck_journal_lines_amount_positive"),
        Index("ix_journal_lines_account", "account_id"),
        Index("ix_journal_lines_entry", "entry_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    entry_id: UUID = Field(sa_column=Column(nullable=False))
    account_id: UUID = Field(sa_column=Column(nullable=False))
    currency: str = Field(sa_column=currency_column())
    direction: Direction = Field(sa_column=_enum(Direction, "ledger_direction"))
    amount: Decimal = Field(sa_column=money_column())


class ReservationState(str, Enum):
    HELD = "held"
    RELEASED = "released"
    SETTLED = "settled"


class Reservation(SQLModel, table=True):
    """An amount held against a pending operation.

    A reservation is *not* a posting. Nothing has happened to the money yet — it
    is still the customer's, and it is still in their account. What a
    reservation does is reduce what is *available*, so two concurrent purchases
    cannot both be told there is enough.

    Partial settlement is normal: a call reserves a maximum and settles what it
    actually cost. `settled_amount` plus `released_amount` never exceeds
    `amount`, which is a CHECK rather than a convention.
    """

    __tablename__ = "ledger_reservations"
    __table_args__ = (
        currency_check("ledger_reservations"),
        UniqueConstraint("business_event_id", name="uq_ledger_reservations_event"),
        CheckConstraint("amount > 0", name="ck_ledger_reservations_amount"),
        CheckConstraint(
            "settled_amount >= 0 AND released_amount >= 0 "
            "AND settled_amount + released_amount <= amount",
            name="ck_ledger_reservations_disposition",
        ),
        CheckConstraint(
            "(state = 'held' AND closed_at IS NULL) "
            "OR (state <> 'held' AND closed_at IS NOT NULL)",
            name="ck_ledger_reservations_closed_at",
        ),
        Index(
            "ix_ledger_reservations_open",
            "account_id",
            "state",
            postgresql_where=text("state = 'held'"),
            sqlite_where=text("state = 'held'"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    business_event_id: str = Field(sa_column=Column(String(200), nullable=False))
    account_id: UUID = Field(
        sa_column=Column(
            ForeignKey("ledger_accounts.id"), nullable=False, index=True
        )
    )
    currency: str = Field(sa_column=currency_column())
    amount: Decimal = Field(sa_column=money_column())
    settled_amount: Decimal = Field(sa_column=money_column())
    released_amount: Decimal = Field(sa_column=money_column())
    state: ReservationState = Field(
        default=ReservationState.HELD,
        sa_column=_enum(ReservationState, "reservation_state", ReservationState.HELD),
    )
    #: A reservation that is never closed holds money forever. Expiry is what a
    #: sweeper acts on; nothing here expires implicitly, because implicitly
    #: releasing money that a supplier is about to charge for is worse.
    expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    closed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


# --- database-enforced invariants -------------------------------------------

#: Checked at COMMIT, not per row: an entry's lines are inserted one at a time,
#: so a per-statement check would fail on the first line of every balanced
#: entry. Deferred means a half-written entry cannot survive a crash either --
#: the whole balanced entry commits, or none of it does.
_BALANCE_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    """
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
            COALESCE(SUM(CASE WHEN direction = 'debit' THEN amount
                              ELSE -amount END), 0),
            COUNT(*)
        INTO imbalance, actual_line_count
        FROM journal_lines
        WHERE entry_id = target_entry_id;

        IF actual_line_count = 0 THEN
            RAISE EXCEPTION 'journal entry %% has no lines', target_entry_id;
        END IF;
        IF actual_line_count <> expected_line_count THEN
            RAISE EXCEPTION
                'journal entry %% expected %% lines but has %%',
                target_entry_id, expected_line_count, actual_line_count;
        END IF;
        IF imbalance <> 0 THEN
            RAISE EXCEPTION
                'journal entry %% does not balance: debits minus credits = %%',
                target_entry_id, imbalance;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE CONSTRAINT TRIGGER trg_journal_entries_balance
        AFTER INSERT ON journal_entries
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION damdam_journal_balances();
    """
)

_ENTRY_IMMUTABLE_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE OR REPLACE FUNCTION damdam_journal_immutable() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION
            'posted journal history is immutable; post a compensating entry instead';
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_journal_entries_immutable
        BEFORE UPDATE OR DELETE ON journal_entries
        FOR EACH ROW EXECUTE FUNCTION damdam_journal_immutable();
    """
)

_LINE_IMMUTABLE_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE CONSTRAINT TRIGGER trg_journal_lines_balance
        AFTER INSERT ON journal_lines
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION damdam_journal_balances();

    CREATE TRIGGER trg_journal_lines_immutable
        BEFORE UPDATE OR DELETE ON journal_lines
        FOR EACH ROW EXECUTE FUNCTION damdam_journal_immutable();
    """
)

_ENTRY_TABLE: Table = JournalEntry.__table__  # type: ignore[attr-defined]
_LINE_TABLE: Table = JournalLine.__table__  # type: ignore[attr-defined]

event.listen(
    _ENTRY_TABLE, "after_create", _BALANCE_TRIGGER.execute_if(dialect="postgresql")
)
event.listen(
    _ENTRY_TABLE,
    "after_create",
    _ENTRY_IMMUTABLE_TRIGGER.execute_if(dialect="postgresql"),
)
event.listen(
    _LINE_TABLE,
    "after_create",
    _LINE_IMMUTABLE_TRIGGER.execute_if(dialect="postgresql"),
)
