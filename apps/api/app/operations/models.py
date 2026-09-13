"""The record of what an operator did, and why (US-41, chunk 25).

One table, and its whole purpose is to make a privileged action **expensive to
take and impossible to hide**.

An internal operations surface exists because things go wrong in ways no
automatic path can settle: a supplier accepted a purchase and never said so, a
payment arrived for an order nobody can find, a customer was charged for a line
that failed. Somebody has to decide. The danger is not that they decide wrongly
— it is that six months later nobody can tell what they decided, on what
evidence, or whether the money moved twice.

So every constrained action writes a row here **before** it is allowed to have
an effect, carrying:

- **who** — an internal operator, not a customer and not an enterprise
  administrator. A different token audience entirely.
- **why** — a reason, required by the database rather than by a form. An action
  with an empty reason is one nobody can review.
- **what changed** — `before_state` and `after_state`, copied. A reference to a
  row that has since moved on explains nothing.
- **what it cost** — `ledger_entry_id` when money moved, and money only ever
  moves through a *balanced compensating entry*. There is no balance-editing
  path in this module, deliberately: the assignment forbids one and so does
  every honest accounting system.

## Immutable, and enforced where it cannot be argued with

`trg_operator_action_immutable` refuses `UPDATE` and `DELETE` outright — the
same mechanism chunk 11 used for supplier attempt history. An audit trail an
operator can edit is an audit trail of whatever the last operator wanted it to
say, and application-level immutability is one migration away from not being
immutable.

## Replay is answered here, not by the caller

`uq_operator_actions_idempotency` makes a repeated resolution the *same*
resolution. An operator who lost a response and clicked again must not post a
second compensating entry, and the honest place to enforce that is the row that
records the decision.
"""

from __future__ import annotations

from datetime import datetime
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
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now


def _enum(enum_type: type[Enum], name: str) -> Column[Any]:
    return Column(
        SAEnum(
            enum_type,
            name=name,
            values_callable=lambda choices: [choice.value for choice in choices],
        ),
        nullable=False,
    )


def _json(nullable: bool = False) -> Column[Any]:
    return Column(JSON().with_variant(JSONB, "postgresql"), nullable=nullable)


class OperatorActionKind(str, Enum):
    """The constrained set of things an operator may do.

    A closed vocabulary rather than free-form: the assignment forbids an
    arbitrary SQL editor, and a list of named actions is what "constrained"
    means in practice. Adding one is a code change with a review, which is the
    point.
    """

    #: A supplier attempt whose outcome was unknown has been reconciled against
    #: the supplier and found to have succeeded. The service is granted.
    CONFIRM_SUPPLIER_SUCCESS = "confirm_supplier_success"
    #: The same, found to have failed. The hold is released and the line fails.
    CONFIRM_SUPPLIER_FAILURE = "confirm_supplier_failure"
    #: A payment arrived that our records cannot account for, resolved by a
    #: balanced compensating entry.
    RESOLVE_PAYMENT_DISCREPANCY = "resolve_payment_discrepancy"
    #: An exception item a human has read and decided needs nothing.
    DISMISS_EXCEPTION = "dismiss_exception"
    #: Somebody looked at masked customer data. Recorded because looking is
    #: itself an act on this surface.
    VIEW_SENSITIVE_RECORD = "view_sensitive_record"


class OperatorSubjectKind(str, Enum):
    """What an action was about."""

    ORDER_ITEM = "order_item"
    SUPPLIER_ATTEMPT = "supplier_attempt"
    PAYMENT = "payment"
    EXCEPTION_ITEM = "exception_item"
    ORGANIZATION = "organization"


class OperatorAction(SQLModel, table=True):
    """One privileged decision, recorded permanently."""

    __tablename__ = "operator_actions"
    __table_args__ = (
        # A repeated resolution is the same resolution. Without this, an
        # operator who lost a response and clicked again posts a second
        # compensating entry against the same discrepancy.
        UniqueConstraint(
            "kind",
            "subject_reference",
            "idempotency_key",
            name="uq_operator_actions_idempotency",
        ),
        # The database requires a reason, because a form does not survive the
        # next client. An action nobody explained is one nobody can review.
        # PostgreSQL-only DDL, for the same reason as the E.164 check in
        # `app/connectivity/models.py`: `btrim` is not SQLite syntax. The
        # production guarantee is unchanged — PostgreSQL is the database this
        # runs on, and the migration creates the constraint there.
        CheckConstraint(
            "length(btrim(reason)) > 0", name="ck_operator_actions_reason"
        ).ddl_if(dialect="postgresql"),
        Index("ix_operator_actions_subject", "subject_kind", "subject_reference"),
        Index("ix_operator_actions_actor", "actor_admin_id", "created_at"),
        Index("ix_operator_actions_created", "created_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    kind: OperatorActionKind = Field(
        sa_column=_enum(OperatorActionKind, "operator_action_kind")
    )
    subject_kind: OperatorSubjectKind = Field(
        sa_column=_enum(OperatorSubjectKind, "operator_subject_kind")
    )
    #: The thing acted on, as a stable string. Deliberately not a foreign key:
    #: the subjects are of five different kinds, and an audit row must outlive
    #: whatever it points at.
    subject_reference: str = Field(sa_column=Column(String(200), nullable=False))
    #: `RESTRICT`: the operator who made a decision is part of the record, and
    #: deleting them would leave a decision nobody made.
    actor_admin_id: UUID = Field(
        sa_column=Column(
            ForeignKey("admin_users.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
    )
    reason: str = Field(sa_column=Column(String(500), nullable=False))
    #: The client's key for this decision. Replaying it returns this row.
    idempotency_key: str = Field(sa_column=Column(String(200), nullable=False))
    exception_item_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("exception_items.id", ondelete="SET NULL"), nullable=True
        ),
    )
    #: What the world looked like, copied. A reference to a row that has since
    #: moved on explains nothing six months later.
    before_state: dict[str, Any] = Field(default_factory=dict, sa_column=_json())
    after_state: dict[str, Any] = Field(default_factory=dict, sa_column=_json())
    #: Set when money moved. It only ever moves through a balanced compensating
    #: entry — there is no balance-editing path in this module.
    ledger_entry_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=True
        ),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
