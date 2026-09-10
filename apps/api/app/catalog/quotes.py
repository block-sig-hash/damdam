"""Immutable, expiring, server-priced quotes (US-31, chunk 09).

A quote is the server's promise of a price. Three properties make it worth
anything, and each is enforced somewhere a service bug cannot reach:

1. **Immutable.** A database trigger refuses any `UPDATE` that changes a priced
   column. Only `status` and its timestamps may move. A quote whose total can be
   edited is not a promise, and "the service never does that" is a claim about
   code that has not been written yet.
2. **Expiring, exclusively at the boundary.** Dead *at* `expires_at`, not after
   it — the same rule chunk 06 applies to identity tokens and chunk 07 to
   step-up elevations.
3. **Priced by the server, from pinned versions.** Every line records the exact
   `product_price` version and, for voice, the exact `tariff` version it was
   priced from. A price change afterwards produces a *new* quote; it never
   reaches back into this one.

The client sends a quote id at checkout. It never sends an amount. Anything a
client can name, a client can change.
"""

import hashlib
import json
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
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.schema import Table
from sqlmodel import Field, SQLModel

from app.money import currency_check, currency_column, money_column, round_money


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


class QuoteStatus(str, Enum):
    ISSUED = "issued"
    REDEEMED = "redeemed"
    VOID = "void"
    # `expired` is deliberately absent: expiry is a fact about `expires_at` and
    # the clock, and storing it as a status would create a second, lagging
    # answer that only a sweeper keeps true.


class Quote(SQLModel, table=True):
    __tablename__ = "quotes"
    __table_args__ = (
        currency_check("quotes"),
        UniqueConstraint("id", "currency", name="uq_quotes_id_currency"),
        CheckConstraint("expires_at > issued_at", name="ck_quotes_window"),
        CheckConstraint(
            "subtotal_amount >= 0 AND tax_amount >= 0 AND fee_amount >= 0 "
            "AND total_amount >= 0",
            name="ck_quotes_amounts_not_negative",
        ),
        CheckConstraint(
            "total_amount = subtotal_amount + tax_amount + fee_amount",
            name="ck_quotes_total_is_sum",
        ),
        CheckConstraint(
            "(status = 'redeemed' AND redeemed_at IS NOT NULL) "
            "OR (status <> 'redeemed' AND redeemed_at IS NULL)",
            name="ck_quotes_redeemed_at",
        ),
        Index("ix_quotes_status_expiry", "status", "expires_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    reference: str = Field(sa_column=Column(String(32), nullable=False, unique=True))
    seller_legal_entity_id: UUID = Field(
        sa_column=Column(ForeignKey("legal_entities.id"), nullable=False, index=True)
    )
    sales_market_id: UUID = Field(
        sa_column=Column(ForeignKey("sales_markets.id"), nullable=False, index=True)
    )
    currency: str = Field(sa_column=currency_column())

    subtotal_amount: Decimal = Field(sa_column=money_column())
    #: Zero until a tax treatment is decided. D3 is open, and inventing a rate
    #: would put a number on an invoice that no authority asked for -- which is
    #: worse than charging nothing and saying so.
    tax_amount: Decimal = Field(sa_column=money_column())
    #: A reference to the tax configuration used, never an inline rate. Null
    #: means "no tax treatment is recorded", which is the honest state today.
    tax_configuration_reference: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    fee_amount: Decimal = Field(sa_column=money_column())
    total_amount: Decimal = Field(sa_column=money_column())

    status: QuoteStatus = Field(
        default=QuoteStatus.ISSUED,
        sa_column=_enum(
            QuoteStatus, "quote_status", QuoteStatus.ISSUED
        ),
    )
    issued_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    redeemed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: SHA-256 over the canonical serialisation of the quote and its lines,
    #: computed at issue. Belt to the trigger's braces: the trigger stops an
    #: `UPDATE`, and this catches anything that reached the rows another way --
    #: a restore, a manual `psql` session, a migration with a bug in it.
    digest: str = Field(sa_column=Column(String(64), nullable=False))


class QuoteItem(SQLModel, table=True):
    __tablename__ = "quote_items"
    __table_args__ = (
        currency_check("quote_items", "unit_currency"),
        # Ties every line to its parent's currency by foreign key, so a line in
        # a different currency cannot exist to be added up.
        ForeignKeyConstraint(
            ["quote_id", "unit_currency"],
            ["quotes.id", "quotes.currency"],
            name="fk_quote_items_quote_currency",
            ondelete="CASCADE",
        ),
        CheckConstraint("quantity >= 1", name="ck_quote_items_quantity"),
        CheckConstraint(
            "unit_amount >= 0 AND line_amount >= 0",
            name="ck_quote_items_amounts_not_negative",
        ),
        CheckConstraint(
            "line_amount = unit_amount * quantity", name="ck_quote_items_line_total"
        ),
        Index("ix_quote_items_quote", "quote_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    quote_id: UUID = Field(sa_column=Column(nullable=False))
    product_id: UUID = Field(
        sa_column=Column(ForeignKey("products.id"), nullable=False, index=True)
    )
    #: The exact price version this line was priced from. Pinning the version,
    #: not the product, is what makes a later price change unable to rewrite
    #: this quote.
    product_price_id: UUID = Field(
        sa_column=Column(ForeignKey("product_prices.id"), nullable=False)
    )
    #: The exact tariff version for a voice line. Null for data-only lines.
    tariff_id: UUID | None = Field(
        default=None, sa_column=Column(ForeignKey("tariffs.id"), nullable=True)
    )
    #: Who the line is for, when that is known at quote time. A bulk quote
    #: often does not know yet, and inventing a recipient would attribute
    #: service to somebody who never received it.
    recipient_user_id: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
    )
    quantity: int = Field(default=1, sa_column=Column(Integer, nullable=False))
    unit_currency: str = Field(sa_column=currency_column())
    unit_amount: Decimal = Field(sa_column=money_column())
    line_amount: Decimal = Field(sa_column=money_column())


def _amount(value: Decimal, currency: str) -> str:
    """Normalise an amount to its currency exponent before hashing it.

    The column is `Numeric(20, 6)`, so a quote issued as `1000.00` reads back
    from PostgreSQL as `1000.000000`. Both are the same money and neither is
    wrong, but `str()` disagrees about them -- so hashing the raw value makes
    every quote read as tampered the moment it survives a round trip.

    Normalising to the currency's own exponent is the fix that keeps the digest
    meaningful: it still changes when the *amount* changes, and no longer
    changes when only the storage scale does.
    """
    return str(round_money(value, currency))


def canonical_payload(quote: Quote, items: list[QuoteItem]) -> str:
    """The exact bytes the digest is taken over.

    Sorted, explicit and stringified: dictionary ordering, storage scale and
    locale are all ways two runs could serialise the same quote differently and
    disagree about its digest for no real reason.
    """
    return json.dumps(
        {
            "id": str(quote.id),
            "reference": quote.reference,
            "seller": str(quote.seller_legal_entity_id),
            "market": str(quote.sales_market_id),
            "currency": quote.currency,
            "subtotal": _amount(quote.subtotal_amount, quote.currency),
            "tax": _amount(quote.tax_amount, quote.currency),
            "tax_configuration": quote.tax_configuration_reference,
            "fee": _amount(quote.fee_amount, quote.currency),
            "total": _amount(quote.total_amount, quote.currency),
            "issued_at": quote.issued_at.isoformat(),
            "expires_at": quote.expires_at.isoformat(),
            "items": sorted(
                (
                    {
                        "product": str(item.product_id),
                        "price_version": str(item.product_price_id),
                        "tariff": str(item.tariff_id) if item.tariff_id else None,
                        "recipient": (
                            str(item.recipient_user_id)
                            if item.recipient_user_id
                            else None
                        ),
                        "quantity": item.quantity,
                        "currency": item.unit_currency,
                        "unit": _amount(item.unit_amount, item.unit_currency),
                        "line": _amount(item.line_amount, item.unit_currency),
                    }
                    for item in items
                ),
                key=lambda entry: (
                    entry["product"],
                    entry["price_version"],
                    entry["recipient"] or "",
                    entry["unit"],
                ),
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def compute_digest(quote: Quote, items: list[QuoteItem]) -> str:
    return hashlib.sha256(canonical_payload(quote, items).encode()).hexdigest()


# --- immutability, enforced by the database ---------------------------------

#: Columns a quote may still change after issue. Everything else is the price,
#: and the price is the promise.
MUTABLE_QUOTE_COLUMNS = ("status", "redeemed_at")

_QUOTE_IMMUTABLE_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE OR REPLACE FUNCTION damdam_quotes_immutable() RETURNS trigger AS $$
    BEGIN
        IF OLD.status <> 'issued' AND NEW.status IS DISTINCT FROM OLD.status THEN
            RAISE EXCEPTION
                'quote status %% is terminal (quote %%)', OLD.status, OLD.id;
        END IF;
        IF NEW.id IS DISTINCT FROM OLD.id
            OR NEW.reference IS DISTINCT FROM OLD.reference
            OR NEW.seller_legal_entity_id IS DISTINCT FROM OLD.seller_legal_entity_id
            OR NEW.sales_market_id IS DISTINCT FROM OLD.sales_market_id
            OR NEW.currency IS DISTINCT FROM OLD.currency
            OR NEW.subtotal_amount IS DISTINCT FROM OLD.subtotal_amount
            OR NEW.tax_amount IS DISTINCT FROM OLD.tax_amount
            OR NEW.tax_configuration_reference
                IS DISTINCT FROM OLD.tax_configuration_reference
            OR NEW.fee_amount IS DISTINCT FROM OLD.fee_amount
            OR NEW.total_amount IS DISTINCT FROM OLD.total_amount
            OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
            OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
            OR NEW.digest IS DISTINCT FROM OLD.digest
        THEN
            RAISE EXCEPTION
                'quotes are immutable: only status and redeemed_at may change'
                ' (quote %%)',
                OLD.id;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_quotes_immutable
        BEFORE UPDATE OR DELETE ON quotes
        FOR EACH ROW EXECUTE FUNCTION damdam_quotes_immutable();
    """
)

#: A quote line never changes at all -- there is no status on it to move.
_QUOTE_ITEM_IMMUTABLE_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE OR REPLACE FUNCTION damdam_quote_items_immutable() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'quote items are immutable (item %%)', OLD.id;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_quote_items_immutable
        BEFORE UPDATE OR DELETE ON quote_items
        FOR EACH ROW EXECUTE FUNCTION damdam_quote_items_immutable();
    """
)

# Attached to table creation so `SQLModel.metadata.create_all` builds them too.
# A guarantee that exists only in a migration is a guarantee every test runs
# without.
_QUOTE_TABLE: Table = Quote.__table__  # type: ignore[attr-defined]
_QUOTE_ITEM_TABLE: Table = QuoteItem.__table__  # type: ignore[attr-defined]

event.listen(
    _QUOTE_TABLE,
    "after_create",
    _QUOTE_IMMUTABLE_TRIGGER.execute_if(dialect="postgresql"),
)
event.listen(
    _QUOTE_ITEM_TABLE,
    "after_create",
    _QUOTE_ITEM_IMMUTABLE_TRIGGER.execute_if(dialect="postgresql"),
)
