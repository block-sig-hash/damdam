"""Orders and order items -- seller, payer, recipient (US-28, data-model.md §6.44).

The legacy `packages` row is one object playing four parts at once: it is the
purchase, the entitlement, the provisioning job and the thing that expires, all
keyed off a single `status` column whose values mix payment, provisioning and
lifecycle. `transactions` then hangs off it for the money.

These tables split the purchase from what it entitles someone to, and split the
three parties a purchase involves:

- **seller** -- the legal entity making the sale (D3, open)
- **payer** -- exactly one of a person or an organization
- **recipient** -- the person who receives the service, per item

An enterprise buying lines for its staff is the case that breaks any model where
those three collapse into one user id.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now
from app.money import currency_check, currency_column, money_column


def _enum(enum_type: type[Enum], name: str, default: Enum) -> "Column[Any]":
    return Column(
        SAEnum(
            enum_type,
            name=name,
            values_callable=lambda choices: [choice.value for choice in choices],
        ),
        nullable=False,
        server_default=default.value,
    )


class PaymentState(str, Enum):
    """Money only. Says nothing about whether anything was provisioned."""

    UNPAID = "unpaid"
    AUTHORIZED = "authorized"
    PAID = "paid"
    REFUNDED = "refunded"
    FAILED = "failed"


class ProvisioningState(str, Enum):
    """Supplier fulfilment only. Says nothing about whether anyone paid.

    `OUTCOME_UNKNOWN` is a first-class state, not an error: a supplier request
    whose response was lost must be reconciled against the same operation
    reference, never retried as a fresh purchase. Chunk 11 owns that recovery;
    the state exists here so it has somewhere truthful to sit.
    """

    NOT_STARTED = "not_started"
    REQUESTED = "requested"
    OUTCOME_UNKNOWN = "outcome_unknown"
    PROVISIONED = "provisioned"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Order(SQLModel, table=True):
    __tablename__ = "orders"
    __table_args__ = (
        currency_check("orders"),
        currency_check("orders", "settlement_currency"),
        UniqueConstraint("id", "currency", name="uq_orders_id_currency"),
        CheckConstraint(
            "(payer_user_id IS NOT NULL AND payer_organization_id IS NULL) "
            "OR (payer_user_id IS NULL AND payer_organization_id IS NOT NULL)",
            name="ck_orders_exactly_one_payer",
        ),
        CheckConstraint("total_amount >= 0", name="ck_orders_total_not_negative"),
        CheckConstraint(
            "(settlement_currency IS NULL AND settlement_amount IS NULL) OR "
            "(settlement_currency IS NOT NULL AND settlement_amount IS NOT NULL)",
            name="ck_orders_settlement_pair",
        ),
        CheckConstraint(
            "settlement_amount >= 0",
            name="ck_orders_settlement_amount_not_negative",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    reference: str = Field(sa_column=Column(String(32), nullable=False, unique=True))
    seller_legal_entity_id: UUID = Field(
        sa_column=Column(ForeignKey("legal_entities.id"), nullable=False, index=True)
    )
    payer_user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
        ),
    )
    payer_organization_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
    )
    currency: str = Field(sa_column=currency_column())
    total_amount: Decimal = Field(sa_column=money_column())
    # Settlement is recorded independently because a processor may charge the
    # customer in one currency and remit to the seller in another. Both values
    # remain null until a settlement amount is known.
    settlement_currency: str | None = Field(
        default=None, sa_column=currency_column(nullable=True)
    )
    settlement_amount: Decimal | None = Field(
        default=None, sa_column=money_column(nullable=True)
    )
    payment_state: PaymentState = Field(
        default=PaymentState.UNPAID,
        sa_column=_enum(PaymentState, "order_payment_state", PaymentState.UNPAID),
    )
    placed_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class OrderItem(SQLModel, table=True):
    __tablename__ = "order_items"
    __table_args__ = (
        currency_check("order_items", "unit_currency"),
        ForeignKeyConstraint(
            ["order_id", "unit_currency"],
            ["orders.id", "orders.currency"],
            name="fk_order_items_order_currency",
            ondelete="CASCADE",
        ),
        CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        CheckConstraint("unit_amount >= 0", name="ck_order_items_amount_not_negative"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    order_id: UUID = Field(
        sa_column=Column(nullable=False, index=True)
    )
    product_id: UUID = Field(
        sa_column=Column(ForeignKey("products.id"), nullable=False, index=True)
    )
    # Null until an enterprise assigns the item to a person. A consumer order
    # names its recipient immediately; a bulk order does not know yet, and
    # inventing one would attribute service to someone who never received it.
    recipient_user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
        ),
    )
    quantity: int = Field(default=1)
    # Copied from the ProductPrice at sale time, not referenced. A later price
    # version must never rewrite what someone was charged.
    unit_currency: str = Field(sa_column=currency_column())
    unit_amount: Decimal = Field(sa_column=money_column())
    provisioning_state: ProvisioningState = Field(
        default=ProvisioningState.NOT_STARTED,
        sa_column=_enum(
            ProvisioningState,
            "order_item_provisioning_state",
            ProvisioningState.NOT_STARTED,
        ),
    )
    # The supplier-facing idempotency handle. Set before dispatch so a crash
    # between request and response can be reconciled rather than repeated.
    operation_reference: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True, unique=True)
    )
