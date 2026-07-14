"""US-09 processor-neutral retail checkout and webhook transactions.

Revision ID: 0010_us09_retail_payments
Revises: 0009_us04_hto_rejection
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_us09_retail_payments"
down_revision: str | None = "0009_us04_hto_rejection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

payment_processor = postgresql.ENUM(
    "paystack", "flutterwave", name="payment_processor", create_type=False
)
payment_method = postgresql.ENUM(
    "card",
    "bank_transfer",
    "ussd",
    "invoice",
    name="payment_method",
    create_type=False,
)
transaction_status = postgresql.ENUM(
    "pending", "success", "failed", name="transaction_status", create_type=False
)


def upgrade() -> None:
    op.execute(
        "ALTER TYPE package_status ADD VALUE IF NOT EXISTS 'pending' BEFORE 'active'"
    )
    payment_processor.create(op.get_bind(), checkfirst=True)
    payment_method.create(op.get_bind(), checkfirst=True)
    transaction_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "package_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("packages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "manifest_order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("manifest_orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "processor", payment_processor, nullable=False, server_default="paystack"
        ),
        sa.Column("processor_reference", sa.String(100), nullable=True),
        sa.Column("amount_ngn", sa.Numeric(12, 2), nullable=False),
        sa.Column("payment_method", payment_method, nullable=True),
        sa.Column("status", transaction_status, nullable=False),
        sa.Column("webhook_payload", postgresql.JSONB(), nullable=True),
        sa.Column("receipt_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_transactions_package_id", "transactions", ["package_id"])
    op.create_index(
        "ux_transactions_processor_reference",
        "transactions",
        ["processor_reference"],
        unique=True,
        postgresql_where=sa.text("processor_reference IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_transactions_processor_reference", table_name="transactions")
    op.drop_index("ix_transactions_package_id", table_name="transactions")
    op.drop_table("transactions")
    transaction_status.drop(op.get_bind(), checkfirst=True)
    payment_method.drop(op.get_bind(), checkfirst=True)
    payment_processor.drop(op.get_bind(), checkfirst=True)

    # PostgreSQL cannot drop one enum value in place. Pending packages have
    # no equivalent in the pre-US-09 schema, so make them cancelled before
    # rebuilding the enum for a reversible development downgrade.
    op.execute("UPDATE packages SET status = 'cancelled' WHERE status = 'pending'")
    op.execute("ALTER TABLE packages ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE packages ALTER COLUMN status TYPE VARCHAR(20) USING status::text"
    )
    op.execute("DROP TYPE package_status")
    op.execute("CREATE TYPE package_status AS ENUM ('active', 'expired', 'cancelled')")
    op.execute(
        "ALTER TABLE packages ALTER COLUMN status TYPE package_status "
        "USING status::package_status"
    )
    op.execute("ALTER TABLE packages ALTER COLUMN status SET DEFAULT 'active'")
