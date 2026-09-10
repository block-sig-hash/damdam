"""Refunds, disputes, bank funding and receipts (US-34, chunk 14).

Money going back out is not the mirror image of money coming in, and the
differences are where it goes wrong:

- **A refund is bounded by a specific charge**, not by an order total. Refunding
  more than was captured is not a large refund; it is a payout, and a payout is
  a different product with different licensing.
- **A dispute is not a refund.** The customer's bank has taken the money back
  and told us afterwards. It is recorded as what it is, and it never rewrites
  the original posting — a chargeback after the service was consumed is a real
  loss and the books have to be able to say so.
- **Bank funding is confirmed from reconciled evidence**, never from an uploaded
  screenshot or a balance somebody edited. A screenshot is a picture; a bank
  statement line is a fact, and only one of them is worth credit.
- **A receipt is generated from history**, never from live lookups. Reprinting
  last year's receipt must produce last year's numbers, in last year's currency,
  naming the entity that actually sold it.

Everything here is additive to the ledger rather than corrective of it. Chunk
10's triggers refuse an edit to a posted entry, and this module never tries: a
refund posts a new, opposite entry with its own business event.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
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


class RefundStatus(str, Enum):
    """`UNKNOWN` again, for the same reason it exists everywhere else.

    A refund request whose response was lost must not be retried blindly: the
    processor may have already sent the money, and a second refund is a second
    payout.
    """

    REQUESTED = "requested"
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class Refund(SQLModel, table=True):
    """Money returned against one specific captured charge.

    Bound to a `payment_attempt`, not to an order. The attempt carries the
    seller, the processor and the charge reference that the refund has to be
    made against — `AGENTS.md` requires the original seller, processor and
    currency to survive a refund, and pointing at the attempt is how that is
    structural rather than remembered.
    """

    __tablename__ = "refunds"
    __table_args__ = (
        currency_check("refunds"),
        UniqueConstraint("business_event_id", name="uq_refunds_event"),
        Index(
            "ux_refunds_processor_reference",
            "processor",
            "processor_reference",
            unique=True,
            postgresql_where=text("processor_reference IS NOT NULL"),
            sqlite_where=text("processor_reference IS NOT NULL"),
        ),
        CheckConstraint("amount > 0", name="ck_refunds_amount"),
        Index("ix_refunds_attempt", "payment_attempt_id", "status"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    #: Ours, and stable across retries of the *same* refund decision.
    business_event_id: str = Field(sa_column=Column(String(200), nullable=False))
    payment_attempt_id: UUID = Field(
        sa_column=Column(
            ForeignKey("payment_attempts.id"), nullable=False, index=True
        )
    )
    processor: str = Field(sa_column=Column(String(32), nullable=False))
    processor_reference: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    currency: str = Field(sa_column=currency_column())
    amount: Decimal = Field(sa_column=money_column())
    status: RefundStatus = Field(
        default=RefundStatus.REQUESTED,
        sa_column=_enum(RefundStatus, "refund_status", RefundStatus.REQUESTED),
    )
    reason: str = Field(sa_column=Column(String(500), nullable=False))
    #: What policy allowed it. D5 is open, so this is a reference rather than a
    #: computed entitlement -- writing a refund rule now would be inventing the
    #: decision it is waiting for.
    policy_reference: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    requested_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    settled_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class DisputeState(str, Enum):
    OPENED = "opened"
    #: We sent evidence. The outcome is still the bank's to decide.
    CONTESTED = "contested"
    WON = "won"
    LOST = "lost"


class Dispute(SQLModel, table=True):
    """A chargeback: the bank took the money back and told us afterwards.

    Recorded separately from refunds because it is a different event with a
    different cause and a different accounting treatment. A dispute lost after
    the customer already consumed the service is a real loss, and collapsing it
    into "refunded" would make the books say we chose to give the money back.
    """

    __tablename__ = "disputes"
    __table_args__ = (
        currency_check("disputes"),
        Index(
            "ux_disputes_processor_reference",
            "processor",
            "processor_reference",
            unique=True,
        ),
        CheckConstraint("amount > 0", name="ck_disputes_amount"),
        CheckConstraint(
            "(state IN ('won', 'lost') AND resolved_at IS NOT NULL) "
            "OR (state NOT IN ('won', 'lost') AND resolved_at IS NULL)",
            name="ck_disputes_resolved_at",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    payment_attempt_id: UUID = Field(
        sa_column=Column(
            ForeignKey("payment_attempts.id"), nullable=False, index=True
        )
    )
    processor: str = Field(sa_column=Column(String(32), nullable=False))
    processor_reference: str = Field(sa_column=Column(String(200), nullable=False))
    currency: str = Field(sa_column=currency_column())
    amount: Decimal = Field(sa_column=money_column())
    state: DisputeState = Field(
        default=DisputeState.OPENED,
        sa_column=_enum(DisputeState, "dispute_state", DisputeState.OPENED),
    )
    reason_code: str | None = Field(
        default=None, sa_column=Column(String(100), nullable=True)
    )
    opened_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    resolved_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class BankFundingStatus(str, Enum):
    IMPORTED = "imported"
    MATCHED = "matched"
    #: Imported, and deliberately not credited: nobody could say whose it is.
    UNMATCHED = "unmatched"


class BankTransferReceipt(SQLModel, table=True):
    """One line from a reconciled bank statement.

    **Not** an uploaded screenshot, and not somebody typing a number into an
    admin screen. `statement_reference` is unique per bank account, so importing
    the same statement twice credits nobody twice — which is the specific
    failure a manual funding process produces every time.

    An unmatched line stays imported and uncredited. Guessing which customer a
    payment belongs to is how one customer is credited with another's money.
    """

    __tablename__ = "bank_transfer_receipts"
    __table_args__ = (
        currency_check("bank_transfer_receipts"),
        # The identity of a statement line. Re-importing a statement is normal
        # and must be harmless.
        UniqueConstraint(
            "bank_account_reference",
            "statement_reference",
            name="uq_bank_transfer_receipts_line",
        ),
        CheckConstraint("amount > 0", name="ck_bank_transfer_receipts_amount"),
        CheckConstraint(
            "(status = 'matched' AND matched_ledger_account_id IS NOT NULL) "
            "OR (status <> 'matched' AND matched_ledger_account_id IS NULL)",
            name="ck_bank_transfer_receipts_matched",
        ),
        Index("ix_bank_transfer_receipts_status", "status", "value_date"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    bank_account_reference: str = Field(
        sa_column=Column(String(100), nullable=False)
    )
    #: The bank's own line identifier. What makes re-import idempotent.
    statement_reference: str = Field(sa_column=Column(String(200), nullable=False))
    currency: str = Field(sa_column=currency_column())
    amount: Decimal = Field(sa_column=money_column())
    #: What the payer typed in the reference field. A hint, never a decision:
    #: people mistype, and crediting on a fuzzy match funds the wrong account.
    payer_reference: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    value_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    status: BankFundingStatus = Field(
        default=BankFundingStatus.IMPORTED,
        sa_column=_enum(
            BankFundingStatus, "bank_funding_status", BankFundingStatus.IMPORTED
        ),
    )
    matched_ledger_account_id: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("ledger_accounts.id"), nullable=True),
    )
    matched_by: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    imported_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    matched_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class DocumentKind(str, Enum):
    RECEIPT = "receipt"
    INVOICE = "invoice"
    CREDIT_NOTE = "credit_note"


class FinancialDocument(SQLModel, table=True):
    """A receipt, invoice or credit note, frozen at the moment it was issued.

    `snapshot` holds the facts the document states — amounts, currency, seller,
    tax reference — copied rather than referenced. A receipt regenerated from
    live data next year would show next year's prices and this year's date, and
    a customer comparing it to their bank statement would be right to complain.

    Numbers are unique per seller and kind, because a tax authority asking for
    invoice 47 must get exactly one document.
    """

    __tablename__ = "financial_documents"
    __table_args__ = (
        currency_check("financial_documents"),
        UniqueConstraint(
            "seller_legal_entity_id",
            "kind",
            "number",
            name="uq_financial_documents_number",
        ),
        Index("ix_financial_documents_order", "order_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    kind: DocumentKind = Field(sa_column=_enum(DocumentKind, "document_kind"))
    number: str = Field(sa_column=Column(String(50), nullable=False))
    seller_legal_entity_id: UUID = Field(
        sa_column=Column(ForeignKey("legal_entities.id"), nullable=False, index=True)
    )
    order_id: UUID | None = Field(
        default=None, sa_column=Column(ForeignKey("orders.id"), nullable=True)
    )
    currency: str = Field(sa_column=currency_column())
    total_amount: Decimal = Field(sa_column=money_column())
    #: The historical facts, copied. Never regenerated from live tables.
    snapshot: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON().with_variant(JSONB, "postgresql"), nullable=False),
    )
    issued_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ExceptionKind(str, Enum):
    UNMATCHED_BANK_TRANSFER = "unmatched_bank_transfer"
    EXCESS_PAYMENT = "excess_payment"
    REFUND_UNKNOWN = "refund_unknown"
    DISPUTE_OPENED = "dispute_opened"
    SETTLEMENT_MISMATCH = "settlement_mismatch"


class ExceptionItem(SQLModel, table=True):
    """Something a human has to look at, with enough context to act.

    Chunk 25 builds the operations interface; this chunk owns the backend
    correctness and gives it a queue to read. Every entry names its kind, what
    it is about, and why — an exception queue whose rows do not explain
    themselves is a list people learn to ignore.
    """

    __tablename__ = "exception_items"
    __table_args__ = (
        UniqueConstraint("kind", "subject_reference", name="uq_exception_items"),
        Index(
            "ix_exception_items_open",
            "kind",
            "resolved_at",
            postgresql_where=text("resolved_at IS NULL"),
            sqlite_where=text("resolved_at IS NULL"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    kind: ExceptionKind = Field(sa_column=_enum(ExceptionKind, "exception_kind"))
    #: What it is about: `bank:<id>`, `excess:<id>`, `refund:<id>`.
    subject_reference: str = Field(sa_column=Column(String(200), nullable=False))
    detail: str = Field(sa_column=Column(String(1000), nullable=False))
    raised_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    resolved_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    resolution: str | None = Field(
        default=None, sa_column=Column(String(1000), nullable=True)
    )
