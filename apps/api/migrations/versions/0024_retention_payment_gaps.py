"""Minimize retained webhook PII and retain manual HTO payments.

Revision ID: 0024_retention_payment_gaps
Revises: 0023_data_retention
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_retention_payment_gaps"
down_revision: str | None = "0023_data_retention"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A manually confirmed invoice has no external payment processor. Keeping
    # this NULL is more accurate than mislabelling it Paystack or Flutterwave.
    op.alter_column(
        "transactions",
        "processor",
        existing_type=sa.Enum(name="payment_processor"),
        nullable=True,
        server_default=None,
    )

    # Apply the same ingestion allowlists to already-retained webhook bodies.
    # Customer, card/mobile-money identifiers, IP/device fingerprints,
    # authorization tokens, metadata, and provider diagnostic logs are removed.
    op.execute(
        sa.text(
            """
            UPDATE transactions
            SET webhook_payload = jsonb_strip_nulls(jsonb_build_object(
                'event', webhook_payload -> 'event',
                'data', jsonb_strip_nulls(jsonb_build_object(
                    'id', webhook_payload -> 'data' -> 'id',
                    'domain', webhook_payload -> 'data' -> 'domain',
                    'status', webhook_payload -> 'data' -> 'status',
                    'reference', webhook_payload -> 'data' -> 'reference',
                    'amount', webhook_payload -> 'data' -> 'amount',
                    'currency', webhook_payload -> 'data' -> 'currency',
                    'channel', webhook_payload -> 'data' -> 'channel',
                    'paid_at', webhook_payload -> 'data' -> 'paid_at',
                    'created_at', webhook_payload -> 'data' -> 'created_at',
                    'fees', webhook_payload -> 'data' -> 'fees'
                ))
            ))
            WHERE processor = 'paystack'
              AND webhook_payload IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE transactions
            SET webhook_payload = jsonb_strip_nulls(jsonb_build_object(
                'event', webhook_payload -> 'event',
                'data', jsonb_strip_nulls(jsonb_build_object(
                    'id', webhook_payload -> 'data' -> 'id',
                    'status', webhook_payload -> 'data' -> 'status',
                    'tx_ref', webhook_payload -> 'data' -> 'tx_ref',
                    'flw_ref', webhook_payload -> 'data' -> 'flw_ref',
                    'amount', webhook_payload -> 'data' -> 'amount',
                    'charged_amount',
                        webhook_payload -> 'data' -> 'charged_amount',
                    'currency', webhook_payload -> 'data' -> 'currency',
                    'app_fee', webhook_payload -> 'data' -> 'app_fee',
                    'merchant_fee',
                        webhook_payload -> 'data' -> 'merchant_fee',
                    'payment_type',
                        webhook_payload -> 'data' -> 'payment_type',
                    'created_at', webhook_payload -> 'data' -> 'created_at',
                    'account_id', webhook_payload -> 'data' -> 'account_id'
                ))
            ))
            WHERE processor = 'flutterwave'
              AND webhook_payload IS NOT NULL
            """
        )
    )

    # Heal the historic gap before enforcing one transaction per HTO order.
    op.execute(
        sa.text(
            """
            INSERT INTO transactions (
                id,
                package_id,
                manifest_order_id,
                processor,
                processor_reference,
                amount_ngn,
                payment_method,
                status,
                webhook_payload,
                receipt_sent_at,
                created_at
            )
            SELECT
                md5('hto-transaction:' || orders.id::text)::uuid,
                NULL,
                orders.id,
                NULL,
                'hto-' || orders.id::text,
                orders.total_ngn,
                'invoice',
                'success',
                jsonb_build_object(
                    'confirmation_source', 'admin',
                    'confirmed_by_admin_id', orders.payment_confirmed_by::text,
                    'confirmed_at', orders.payment_confirmed_at
                ),
                NULL,
                orders.payment_confirmed_at
            FROM manifest_orders AS orders
            WHERE orders.payment_confirmed_at IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM transactions AS existing
                  WHERE existing.manifest_order_id = orders.id
              )
            """
        )
    )

    op.create_index(
        "ux_transactions_manifest_order_id",
        "transactions",
        ["manifest_order_id"],
        unique=True,
    )
    op.create_check_constraint(
        "ck_transactions_manual_invoice_processor",
        "transactions",
        "processor IS NOT NULL OR "
        "(payment_method = 'invoice' AND processor_reference LIKE 'hto-%')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_transactions_manual_invoice_processor",
        "transactions",
        type_="check",
    )
    op.drop_index("ux_transactions_manifest_order_id", table_name="transactions")
    # The pre-amendment schema cannot represent processor-neutral manual
    # evidence. A development downgrade removes those new backfill rows; the
    # deliberately discarded PII cannot and must not be reconstructed.
    op.execute(
        "DELETE FROM transactions "
        "WHERE processor IS NULL AND payment_method = 'invoice'"
    )
    op.alter_column(
        "transactions",
        "processor",
        existing_type=sa.Enum(name="payment_processor"),
        nullable=False,
        server_default=sa.text("'paystack'"),
    )
