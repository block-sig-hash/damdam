"""Refunds, disputes, bank funding, receipts and the exception queue — US-34.

Revision ID: 0034_refunds_and_reconciliation
Revises: 0033_payment_contract

Additive. Nothing is seeded and no existing row is touched.

Three constraints carry the chunk's guarantees:

- `ux_refunds_processor_reference` — the same payout cannot be recorded twice.
- `uq_bank_transfer_receipts_line` — re-importing a bank statement credits
  nobody twice, which is the failure a manual funding process produces every
  time.
- `ck_bank_transfer_receipts_matched` — a matched line names the account it
  funded, so a credit with no attributable decision cannot exist. That is the
  difference between reconciled evidence and an unaudited balance edit, which
  the assignment forbids.

The refund ceiling — total refunded never exceeding the refundable charge — is
not a single constraint because it spans rows. It is enforced by the service
under a row lock on the payment attempt, and by chunk 10's balance trigger,
which would refuse the posting even if the service were wrong.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034_refunds_and_reconciliation"
down_revision: str | None = "0033_payment_contract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUMS = (
    ("refund_status", ("requested", "pending", "succeeded", "failed", "unknown")),
    ("dispute_state", ("opened", "contested", "won", "lost")),
    ("bank_funding_status", ("imported", "matched", "unmatched")),
    ("document_kind", ("receipt", "invoice", "credit_note")),
    (
        "exception_kind",
        (
            "unmatched_bank_transfer",
            "excess_payment",
            "refund_unknown",
            "dispute_opened",
            "settlement_mismatch",
        ),
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _ENUMS:
        postgresql.ENUM(*values, name=name, create_type=True).create(
            bind, checkfirst=True
        )

    op.create_table(
        "refunds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("business_event_id", sa.String(200), nullable=False),
        sa.Column(
            "payment_attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_attempts.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("processor", sa.String(32), nullable=False),
        sa.Column("processor_reference", sa.String(200), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="refund_status", create_type=False),
            nullable=False,
            server_default="requested",
        ),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("policy_reference", sa.String(200), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("business_event_id", name="uq_refunds_event"),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_refunds_currency_iso4217"
        ),
        sa.CheckConstraint("amount > 0", name="ck_refunds_amount"),
    )
    op.create_index(
        "ux_refunds_processor_reference",
        "refunds",
        ["processor", "processor_reference"],
        unique=True,
        postgresql_where=sa.text("processor_reference IS NOT NULL"),
    )
    op.create_index("ix_refunds_attempt", "refunds", ["payment_attempt_id", "status"])

    op.create_table(
        "disputes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "payment_attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_attempts.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("processor", sa.String(32), nullable=False),
        sa.Column("processor_reference", sa.String(200), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "state",
            postgresql.ENUM(name="dispute_state", create_type=False),
            nullable=False,
            server_default="opened",
        ),
        sa.Column("reason_code", sa.String(100), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_disputes_currency_iso4217"
        ),
        sa.CheckConstraint("amount > 0", name="ck_disputes_amount"),
        sa.CheckConstraint(
            "(state IN ('won', 'lost') AND resolved_at IS NOT NULL) "
            "OR (state NOT IN ('won', 'lost') AND resolved_at IS NULL)",
            name="ck_disputes_resolved_at",
        ),
    )
    op.create_index(
        "ux_disputes_processor_reference",
        "disputes",
        ["processor", "processor_reference"],
        unique=True,
    )

    op.create_table(
        "bank_transfer_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("bank_account_reference", sa.String(100), nullable=False),
        sa.Column("statement_reference", sa.String(200), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("payer_reference", sa.String(200), nullable=True),
        sa.Column("value_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="bank_funding_status", create_type=False),
            nullable=False,
            server_default="imported",
        ),
        sa.Column(
            "matched_ledger_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ledger_accounts.id"),
            nullable=True,
        ),
        sa.Column("matched_by", sa.String(200), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "bank_account_reference",
            "statement_reference",
            name="uq_bank_transfer_receipts_line",
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="ck_bank_transfer_receipts_currency_iso4217",
        ),
        sa.CheckConstraint("amount > 0", name="ck_bank_transfer_receipts_amount"),
        sa.CheckConstraint(
            "(status = 'matched' AND matched_ledger_account_id IS NOT NULL) "
            "OR (status <> 'matched' AND matched_ledger_account_id IS NULL)",
            name="ck_bank_transfer_receipts_matched",
        ),
    )
    op.create_index(
        "ix_bank_transfer_receipts_status",
        "bank_transfer_receipts",
        ["status", "value_date"],
    )

    op.create_table(
        "financial_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "kind",
            postgresql.ENUM(name="document_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("number", sa.String(50), nullable=False),
        sa.Column(
            "seller_legal_entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("legal_entities.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id"),
            nullable=True,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("total_amount", sa.Numeric(20, 6), nullable=False),
        # The historical facts, copied. A receipt regenerated from live data
        # next year shows next year's prices with this year's date.
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # A tax authority asking for invoice 47 must get exactly one document.
        sa.UniqueConstraint(
            "seller_legal_entity_id",
            "kind",
            "number",
            name="uq_financial_documents_number",
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_financial_documents_currency_iso4217"
        ),
    )
    op.create_index("ix_financial_documents_order", "financial_documents", ["order_id"])

    op.create_table(
        "exception_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "kind",
            postgresql.ENUM(name="exception_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("subject_reference", sa.String(200), nullable=False),
        sa.Column("detail", sa.String(1000), nullable=False),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.String(1000), nullable=True),
        sa.UniqueConstraint("kind", "subject_reference", name="uq_exception_items"),
    )
    op.create_index(
        "ix_exception_items_open",
        "exception_items",
        ["kind", "resolved_at"],
        postgresql_where=sa.text("resolved_at IS NULL"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        "exception_items",
        "financial_documents",
        "bank_transfer_receipts",
        "disputes",
        "refunds",
    ):
        op.drop_table(table)
    for name, _ in _ENUMS:
        postgresql.ENUM(name=name, create_type=False).drop(bind, checkfirst=True)
