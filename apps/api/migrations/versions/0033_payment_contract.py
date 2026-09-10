"""Provider-neutral payment contract — US-33, chunk 12.

Revision ID: 0033_payment_contract
Revises: 0032_fulfilment_outbox

Additive. `transactions` and the legacy Paystack/Flutterwave path are untouched
and keep working; this is what new orders use, and moving the legacy path over
belongs to the chunk that retires it.

**Nothing is seeded, and nothing can collect money.** `merchant_accounts` is
empty, `live_enabled` defaults to false, and
`ck_merchant_accounts_live_needs_approval` refuses to let it be true without a
named approval artefact. D3 (selling entity) and D4 (processors and merchant
approval) are both open, so that constraint is where "keep live collection
disabled" stops being a promise.

`ux_payment_attempts_one_success` is the chunk's central guarantee: at most one
succeeded attempt per intent. Two successful charges for one order is the
failure this chunk exists to prevent, and this refuses it rather than reporting
it afterwards.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033_payment_contract"
down_revision: str | None = "0032_fulfilment_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUMS = (
    ("payment_method_kind", ("card", "bank_transfer", "ussd", "wallet")),
    (
        "payment_attempt_status",
        ("created", "pending", "succeeded", "failed", "unknown", "abandoned"),
    ),
)

_PAYMENT_HISTORY_TRIGGER = """
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

CREATE TRIGGER trg_payment_attempts_history
    BEFORE UPDATE OR DELETE ON payment_attempts
    FOR EACH ROW EXECUTE FUNCTION damdam_payment_history();
"""


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _ENUMS:
        postgresql.ENUM(*values, name=name, create_type=True).create(
            bind, checkfirst=True
        )

    op.create_table(
        "merchant_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("processor", sa.String(32), nullable=False),
        sa.Column(
            "legal_entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("legal_entities.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "live_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("approval_reference", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "processor",
            "legal_entity_id",
            "currency",
            name="uq_merchant_accounts_identity",
        ),
        sa.UniqueConstraint("id", "currency", name="uq_merchant_accounts_id_currency"),
        sa.UniqueConstraint(
            "id",
            "legal_entity_id",
            "currency",
            name="uq_merchant_accounts_intent_binding",
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_merchant_accounts_currency_iso4217"
        ),
        # Where D3/D4 bite: going live needs a named approval artefact, not a
        # checkbox somebody ticked and not a passing sandbox call.
        sa.CheckConstraint(
            "NOT live_enabled OR approval_reference IS NOT NULL",
            name="ck_merchant_accounts_live_needs_approval",
        ),
    )

    op.create_table(
        "merchant_payment_methods",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "merchant_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("merchant_accounts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "method",
            postgresql.ENUM(name="payment_method_kind", create_type=False),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "merchant_account_id", "method", name="uq_merchant_payment_methods"
        ),
    )

    op.create_table(
        "payment_intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "quote_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("quotes.id"),
            nullable=True,
        ),
        sa.Column(
            "seller_legal_entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("legal_entities.id"),
            nullable=False,
        ),
        sa.Column(
            "merchant_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("merchant_accounts.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # One intent per order: the business intention to collect for an order
        # is singular, even when several attempts are made at it.
        sa.UniqueConstraint("order_id", name="uq_payment_intents_order"),
        sa.UniqueConstraint("id", "currency", name="uq_payment_intents_id_currency"),
        sa.ForeignKeyConstraint(
            ["merchant_account_id", "seller_legal_entity_id", "currency"],
            [
                "merchant_accounts.id",
                "merchant_accounts.legal_entity_id",
                "merchant_accounts.currency",
            ],
            name="fk_payment_intents_merchant_binding",
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_payment_intents_currency_iso4217"
        ),
        sa.CheckConstraint("amount > 0", name="ck_payment_intents_amount"),
    )

    op.create_table(
        "payment_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "intent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_intents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("processor", sa.String(32), nullable=False),
        sa.Column(
            "method",
            postgresql.ENUM(name="payment_method_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("processor_reference", sa.String(200), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="payment_attempt_status", create_type=False),
            nullable=False,
            server_default="created",
        ),
        sa.Column("processor_status", sa.String(100), nullable=True),
        sa.Column("failure_reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_payment_attempts_currency_iso4217"
        ),
        sa.CheckConstraint("amount > 0", name="ck_payment_attempts_amount"),
        sa.CheckConstraint(
            "(status = 'succeeded' AND processor_reference IS NOT NULL "
            "AND captured_at IS NOT NULL) "
            "OR status <> 'succeeded'",
            name="ck_payment_attempts_succeeded",
        ),
        sa.UniqueConstraint(
            "processor", "idempotency_key", name="uq_payment_attempts_key"
        ),
    )
    # The same charge cannot be recorded twice, which is what makes a replayed
    # webhook harmless.
    op.create_index(
        "ux_payment_attempts_processor_reference",
        "payment_attempts",
        ["processor", "processor_reference"],
        unique=True,
        postgresql_where=sa.text("processor_reference IS NOT NULL"),
    )
    # The chunk's central guarantee.
    op.create_index(
        "ux_payment_attempts_one_success",
        "payment_attempts",
        ["intent_id"],
        unique=True,
        postgresql_where=sa.text("status = 'succeeded'"),
    )
    op.create_index(
        "ux_payment_attempts_one_live",
        "payment_attempts",
        ["intent_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('created', 'pending', 'unknown')"),
    )
    op.create_index(
        "ix_payment_attempts_intent", "payment_attempts", ["intent_id", "status"]
    )

    op.create_table(
        "excess_payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "intent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_intents.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("processor", sa.String(32), nullable=False),
        sa.Column("processor_reference", sa.String(200), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_excess_payments_currency_iso4217"
        ),
        sa.CheckConstraint("amount > 0", name="ck_excess_payments_amount"),
    )
    # Money we received that no intent should have collected is recorded, not
    # dropped: the customer's account has already been debited, and refusing to
    # write it down would be losing it.
    op.create_index(
        "ux_excess_payments_reference",
        "excess_payments",
        ["processor", "processor_reference"],
        unique=True,
    )
    op.execute(sa.text(_PAYMENT_HISTORY_TRIGGER))


def downgrade() -> None:
    bind = op.get_bind()
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_payment_attempts_history "
            "ON payment_attempts"
        )
    )
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_payment_intents_immutable "
            "ON payment_intents"
        )
    )
    op.execute(sa.text("DROP FUNCTION IF EXISTS damdam_payment_history()"))
    for table in (
        "excess_payments",
        "payment_attempts",
        "payment_intents",
        "merchant_payment_methods",
        "merchant_accounts",
    ):
        op.drop_table(table)
    for name, _ in _ENUMS:
        postgresql.ENUM(name=name, create_type=False).drop(bind, checkfirst=True)
