"""The provider-neutral payment contract (US-33, chunk 12).

Every processor is reached through this, and nothing above it knows which one it
is talking to. That boundary exists for a specific reason rather than as
architecture for its own sake: **D4 is open.** No global processor is selected,
Stripe is a candidate and not a decision, and code that named one would have to
be unpicked when the decision goes elsewhere.

Four things are immutable on a payment intent, and the immutability is the
point:

| Field | Why it can never change |
|---|---|
| `seller_legal_entity_id` | The entity that sold it is the entity that must refund it |
| `merchant_account_id` | Money settles to the account that took it |
| `currency` | A charge in one currency cannot be captured in another |
| `quote_id` / `order_id` | What was bought is what was paid for |

An attempt that needs different values is a **new attempt**, not an edit. That is
what makes "one business order cannot be credited twice" checkable: every
attempt names the order, and the order's captured total is the sum of its
attempts.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DDL,
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import Table
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now

# Imported for its side effect: a foreign key can only be resolved if the table
# it targets is registered in SQLModel's metadata, and `create_all` in a test
# that never imports the catalog would otherwise fail on `payment_intents`.
# Declaring the dependency here, where the foreign key is, keeps it from being
# a trap the next test file falls into.
from app.catalog.quotes import Quote as _Quote  # noqa: F401
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


class PaymentMethodKind(str, Enum):
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    USSD = "ussd"
    WALLET = "wallet"


class AttemptStatus(str, Enum):
    """Where one attempt at collecting money has got to.

    `UNKNOWN` is here for the same reason it is in `AttemptOutcome`: a charge
    whose outcome we did not see is not a failure, and treating it as one is how
    a customer gets charged twice. It routes to reconciliation.
    """

    CREATED = "created"
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    ABANDONED = "abandoned"


class MerchantAccount(SQLModel, table=True):
    """One merchant relationship: a processor, an entity, a currency.

    `live_enabled` defaults to **false** and is the D3/D4 gate in table form. A
    sandbox that works is not merchant approval, a registered company is not a
    merchant account, and neither is a reason to start collecting money.
    """

    __tablename__ = "merchant_accounts"
    __table_args__ = (
        currency_check("merchant_accounts"),
        UniqueConstraint(
            "processor",
            "legal_entity_id",
            "currency",
            name="uq_merchant_accounts_identity",
        ),
        UniqueConstraint("id", "currency", name="uq_merchant_accounts_id_currency"),
        UniqueConstraint(
            "id",
            "legal_entity_id",
            "currency",
            name="uq_merchant_accounts_intent_binding",
        ),
        # Going live needs a named approval artefact. Not a checkbox somebody
        # ticked, and not a passing sandbox call.
        CheckConstraint(
            "NOT live_enabled OR approval_reference IS NOT NULL",
            name="ck_merchant_accounts_live_needs_approval",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    processor: str = Field(sa_column=Column(String(32), nullable=False))
    legal_entity_id: UUID = Field(
        sa_column=Column(ForeignKey("legal_entities.id"), nullable=False, index=True)
    )
    currency: str = Field(sa_column=currency_column())
    #: False until a real merchant approval exists. See D4.
    live_enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    approval_reference: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
class MerchantPaymentMethod(SQLModel, table=True):
    """A payment rail explicitly enabled for one merchant relationship."""

    __tablename__ = "merchant_payment_methods"
    __table_args__ = (
        UniqueConstraint(
            "merchant_account_id", "method", name="uq_merchant_payment_methods"
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    merchant_account_id: UUID = Field(
        sa_column=Column(
            ForeignKey("merchant_accounts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    method: PaymentMethodKind = Field(
        sa_column=_enum(PaymentMethodKind, "payment_method_kind")
    )


class PaymentIntent(SQLModel, table=True):
    """One business intention to collect money for one order.

    An order has at most one intent, and an intent may have several attempts —
    a card declined, then a bank transfer. The *intent* is what carries the
    amount and the immutable identity; an attempt is one try at collecting it.

    Separating them is what makes double-capture detectable: two successful
    attempts against one intent is a fact the database can see, rather than two
    unrelated payments nobody correlates.
    """

    __tablename__ = "payment_intents"
    __table_args__ = (
        currency_check("payment_intents"),
        UniqueConstraint("order_id", name="uq_payment_intents_order"),
        UniqueConstraint("id", "currency", name="uq_payment_intents_id_currency"),
        CheckConstraint("amount > 0", name="ck_payment_intents_amount"),
        ForeignKeyConstraint(
            ["merchant_account_id", "seller_legal_entity_id", "currency"],
            [
                "merchant_accounts.id",
                "merchant_accounts.legal_entity_id",
                "merchant_accounts.currency",
            ],
            name="fk_payment_intents_merchant_binding",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    order_id: UUID = Field(
        sa_column=Column(ForeignKey("orders.id"), nullable=False, index=True)
    )
    quote_id: UUID | None = Field(
        default=None, sa_column=Column(ForeignKey("quotes.id"), nullable=True)
    )
    seller_legal_entity_id: UUID = Field(
        sa_column=Column(ForeignKey("legal_entities.id"), nullable=False)
    )
    #: A plain foreign key. Money settles to the account that took it, so an
    #: intent pointing at an account that does not exist is not a state worth
    #: allowing.
    merchant_account_id: UUID = Field(
        sa_column=Column(
            ForeignKey("merchant_accounts.id"), nullable=False, index=True
        )
    )
    currency: str = Field(sa_column=currency_column())
    amount: Decimal = Field(sa_column=money_column())
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class PaymentAttempt(SQLModel, table=True):
    """One try at collecting an intent, through one processor.

    `processor_reference` is unique per processor: the same charge cannot be
    recorded twice, which is what makes a replayed webhook harmless.
    """

    __tablename__ = "payment_attempts"
    __table_args__ = (
        currency_check("payment_attempts"),
        UniqueConstraint(
            "processor", "idempotency_key", name="uq_payment_attempts_key"
        ),
        Index(
            "ux_payment_attempts_processor_reference",
            "processor",
            "processor_reference",
            unique=True,
            postgresql_where=text("processor_reference IS NOT NULL"),
            sqlite_where=text("processor_reference IS NOT NULL"),
        ),
        # At most one *succeeded* attempt per intent. Two successful charges
        # for one order is the failure this whole chunk is about, and this is
        # where it is refused rather than reported.
        Index(
            "ux_payment_attempts_one_success",
            "intent_id",
            unique=True,
            postgresql_where=text("status = 'succeeded'"),
            sqlite_where=text("status = 'succeeded'"),
        ),
        Index(
            "ux_payment_attempts_one_live",
            "intent_id",
            unique=True,
            postgresql_where=text(
                "status IN ('created', 'pending', 'unknown')"
            ),
            sqlite_where=text("status IN ('created', 'pending', 'unknown')"),
        ),
        CheckConstraint("amount > 0", name="ck_payment_attempts_amount"),
        CheckConstraint(
            "(status = 'succeeded' AND processor_reference IS NOT NULL "
            "AND captured_at IS NOT NULL) "
            "OR status <> 'succeeded'",
            name="ck_payment_attempts_succeeded",
        ),
        Index("ix_payment_attempts_intent", "intent_id", "status"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    intent_id: UUID = Field(
        sa_column=Column(
            ForeignKey("payment_intents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    processor: str = Field(sa_column=Column(String(32), nullable=False))
    method: PaymentMethodKind = Field(
        sa_column=_enum(PaymentMethodKind, "payment_method_kind")
    )
    #: Ours, sent to the processor. Same discipline as chunk 11's supplier key.
    idempotency_key: str = Field(sa_column=Column(String(200), nullable=False))
    processor_reference: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    currency: str = Field(sa_column=currency_column())
    amount: Decimal = Field(sa_column=money_column())
    status: AttemptStatus = Field(
        default=AttemptStatus.CREATED,
        sa_column=_enum(AttemptStatus, "payment_attempt_status", AttemptStatus.CREATED),
    )
    #: What the processor actually told us, kept for reconciliation. Never a
    #: card number: `security.md` keeps raw card data outside DamDam entirely.
    processor_status: str | None = Field(
        default=None, sa_column=Column(String(100), nullable=True)
    )
    failure_reason: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    captured_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


_PAYMENT_HISTORY_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE OR REPLACE FUNCTION damdam_payment_history() RETURNS trigger AS $$
    BEGIN
        IF TG_TABLE_NAME = 'payment_intents' THEN
            RAISE EXCEPTION 'payment intent is immutable';
        END IF;
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'payment attempt history is immutable';
        END IF;
        IF OLD.status = 'succeeded' AND NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'succeeded payment attempt is immutable';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_payment_intents_immutable
        BEFORE UPDATE OR DELETE ON payment_intents
        FOR EACH ROW EXECUTE FUNCTION damdam_payment_history();
    """
)

_ATTEMPT_HISTORY_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE TRIGGER trg_payment_attempts_history
        BEFORE UPDATE OR DELETE ON payment_attempts
        FOR EACH ROW EXECUTE FUNCTION damdam_payment_history();
    """
)

_INTENT_TABLE: Table = PaymentIntent.__table__  # type: ignore[attr-defined]
_PAYMENT_ATTEMPT_TABLE: Table = PaymentAttempt.__table__  # type: ignore[attr-defined]
event.listen(
    _INTENT_TABLE,
    "after_create",
    _PAYMENT_HISTORY_TRIGGER.execute_if(dialect="postgresql"),
)
event.listen(
    _PAYMENT_ATTEMPT_TABLE,
    "after_create",
    _ATTEMPT_HISTORY_TRIGGER.execute_if(dialect="postgresql"),
)


class ExcessPayment(SQLModel, table=True):
    """Money we received that no intent should have collected.

    A second successful charge for one order is refused by
    `ux_payment_attempts_one_success` — but the money may already have left the
    customer's account, and refusing to *record* it would be losing it. So it is
    recorded here instead, with what it belongs to, and chunk 14 refunds it.

    Dropping the webhook would be the alternative, and the alternative is a
    customer who has been charged twice and a system that has never heard of the
    second charge.
    """

    __tablename__ = "excess_payments"
    __table_args__ = (
        currency_check("excess_payments"),
        Index(
            "ux_excess_payments_reference",
            "processor",
            "processor_reference",
            unique=True,
        ),
        CheckConstraint("amount > 0", name="ck_excess_payments_amount"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    intent_id: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("payment_intents.id"), nullable=True, index=True),
    )
    processor: str = Field(sa_column=Column(String(32), nullable=False))
    processor_reference: str = Field(sa_column=Column(String(200), nullable=False))
    currency: str = Field(sa_column=currency_column())
    amount: Decimal = Field(sa_column=money_column())
    reason: str = Field(sa_column=Column(String(500), nullable=False))
    resolved_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    raw_payload: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON().with_variant(JSONB, "postgresql"), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
