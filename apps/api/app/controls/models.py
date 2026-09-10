"""Top-ups, spending bounds and organization budgets (US-36, chunk 17).

Three tables, and the first one exists because of a fact about this product
rather than about databases: **a prepaid promise is only as good as the thing
that enforces it.**

`prd.md` AC-36.4 forbids presenting a delayed, app-side figure as a guaranteed
cap, and the Telnyx capability record says why that matters here — the data
limit's network-side enforcement latency is undocumented, and no voice spending
cap is documented at all. So an app that adds up delayed usage records and calls
the result a hard cap is describing something it cannot do. `spending_controls`
is where a bound is either **enforced by the supplier** or honestly recorded as
absent.

## The tables

**`entitlement_top_ups`** — more allowance bought for an existing line. A grant
is append-only; incrementing the original would rewrite what somebody was sold.

**`spending_controls`** — the bound on one line, and who enforces it. "We add up
records" and "the carrier stops the traffic" are different promises.

**`organization_spending_policies`** — an organization's cap, per currency. An
enterprise cap is a policy about people, not a property of a line.

**`allowance_notices`** — which low-balance threshold has already been
announced. Without it, every poll re-announces the same one.

## Why a top-up is a new row rather than a bigger number

`entitlements.data_bytes_total` is what the customer was granted when they
bought the plan. Adding to it in place would make the original grant
unreadable — and "how much did I actually buy, and when" is the first question
in any billing dispute.

So a top-up is its own row with its own order item, and the available allowance
is the grant **plus** the applied top-ups. Append-only, auditable, and the same
discipline chunk 10 applies to money and chunk 16 applies to usage.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
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


class TopUpState(str, Enum):
    """Where a top-up has got to, with the partial states named.

    The assignment asks for *"idempotent payment/reservation/provisioning and
    recoverable partial states"*, and a partial state is only recoverable if it
    has a name. Five of these are ordinary; `OUTCOME_UNKNOWN` is the one that
    matters, for the same reason it matters in chunk 11: a supplier request whose
    response was lost is not a failure, and retrying it raises a cap twice or
    buys allowance twice.
    """

    REQUESTED = "requested"
    #: Funds held. Nothing has moved and nothing has been granted.
    RESERVED = "reserved"
    #: Money settled. The customer has paid; the allowance is not theirs yet.
    PAID = "paid"
    #: The supplier is being asked to raise the enforced cap.
    PROVISIONING = "provisioning"
    #: We do not know whether the supplier applied it. Reconcile; never retry.
    OUTCOME_UNKNOWN = "outcome_unknown"
    #: The allowance is live. Only this state counts toward a balance.
    APPLIED = "applied"
    FAILED = "failed"


#: Top-ups whose allowance is spendable. Exactly one state, deliberately: a
#: customer who has paid but whose cap has not been raised does not yet have
#: the data, and telling them they do produces a call that fails.
SPENDABLE_TOP_UP_STATES = (TopUpState.APPLIED,)


class EntitlementTopUp(SQLModel, table=True):
    """More allowance for an existing line, bought separately.

    `order_item_id` is unique, which is the idempotency guarantee in table form:
    one purchase, one top-up, however many times a worker replays the request.

    Expiry extension is separate from allowance because they are separately
    saleable and separately refusable — a supplier may let us add data to a
    profile it will not let us keep alive longer.
    """

    __tablename__ = "entitlement_top_ups"
    __table_args__ = (
        currency_check("entitlement_top_ups"),
        UniqueConstraint("order_item_id", name="uq_entitlement_top_ups_order_item"),
        UniqueConstraint(
            "business_event_id", name="uq_entitlement_top_ups_business_event"
        ),
        CheckConstraint(
            "data_bytes >= 0 AND voice_seconds >= 0",
            name="ck_entitlement_top_ups_not_negative",
        ),
        CheckConstraint(
            "data_bytes > 0 OR voice_seconds > 0 OR extends_days > 0",
            name="ck_entitlement_top_ups_grants_something",
        ),
        CheckConstraint("extends_days >= 0", name="ck_entitlement_top_ups_extension"),
        CheckConstraint("amount >= 0", name="ck_entitlement_top_ups_amount"),
        CheckConstraint(
            "(state = 'applied' AND applied_at IS NOT NULL) "
            "OR (state <> 'applied' AND applied_at IS NULL)",
            name="ck_entitlement_top_ups_applied_at",
        ),
        Index("ix_entitlement_top_ups_entitlement", "entitlement_id", "state"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    entitlement_id: UUID = Field(
        sa_column=Column(
            ForeignKey("entitlements.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
    )
    #: The purchase this top-up is. One order item, one top-up.
    order_item_id: UUID = Field(
        sa_column=Column(
            ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=False
        )
    )
    #: Names the event for the ledger, so a replayed settlement posts once.
    business_event_id: str = Field(sa_column=Column(String(200), nullable=False))
    data_bytes: int = Field(
        sa_column=Column(BigInteger, nullable=False, server_default="0")
    )
    voice_seconds: int = Field(
        sa_column=Column(BigInteger, nullable=False, server_default="0")
    )
    extends_days: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    currency: str = Field(sa_column=currency_column())
    amount: Decimal = Field(sa_column=money_column())
    state: TopUpState = Field(
        default=TopUpState.REQUESTED,
        sa_column=_enum(TopUpState, "top_up_state", TopUpState.REQUESTED),
    )
    #: Why it is stuck or why it failed, in the supplier's words where given.
    detail: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    requested_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    applied_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class Enforcement(str, Enum):
    """Who actually stops the spending.

    The distinction the whole chunk turns on. `NONE` is not a missing value — it
    is the honest state for a supplier whose cap we cannot rely on, and it is
    what stops an offer being sold with a prepaid guarantee behind it.
    """

    #: The supplier enforces a documented hard limit, network-side.
    PROVIDER_HARD_LIMIT = "provider_hard_limit"
    #: A bounded-exposure policy somebody approved with a named reference: we
    #: accept a quantified maximum overshoot rather than claiming there is none.
    APPROVED_BOUNDED_EXPOSURE = "approved_bounded_exposure"
    #: Nothing enforces it but our own delayed accounting. No guarantee may be
    #: made on this basis, and `prd.md` AC-36.4 says so.
    NONE = "none"


class ControlState(str, Enum):
    """Whether the bound we asked for is actually in place at the supplier."""

    #: We have decided on a limit and not yet sent it.
    REQUESTED = "requested"
    #: The supplier confirmed it.
    ACTIVE = "active"
    #: We do not know whether the supplier applied it. Never re-send blindly.
    OUTCOME_UNKNOWN = "outcome_unknown"
    FAILED = "failed"


class SpendingControl(SQLModel, table=True):
    """The bound on one line, and who enforces it.

    Two numbers, deliberately: `requested_limit_bytes` is what we asked for and
    `confirmed_limit_bytes` is what the supplier says is in force. They differ
    while a change is in flight, and a UI that shows the requested figure during
    that window tells a customer their cap has moved when it has not.

    `enforcement` is what a product decision reads. Selling a hard prepaid
    guarantee against `NONE` is exactly the claim `AGENTS.md` and AC-36.4
    forbid — an app-side balance computed from delayed records does not stop a
    native call.
    """

    __tablename__ = "spending_controls"
    __table_args__ = (
        UniqueConstraint("carrier_line_id", name="uq_spending_controls_line"),
        CheckConstraint(
            "requested_limit_bytes IS NULL OR requested_limit_bytes >= 0",
            name="ck_spending_controls_requested",
        ),
        CheckConstraint(
            "confirmed_limit_bytes IS NULL OR confirmed_limit_bytes >= 0",
            name="ck_spending_controls_confirmed",
        ),
        # A supplier-enforced bound has to name the number the supplier
        # confirmed. Claiming enforcement with no confirmed limit is the exact
        # overstatement this table exists to prevent.
        CheckConstraint(
            "enforcement <> 'provider_hard_limit' "
            "OR confirmed_limit_bytes IS NOT NULL",
            name="ck_spending_controls_hard_limit_needs_confirmation",
        ),
        # And an approved bounded-exposure policy has to name the approval.
        CheckConstraint(
            "enforcement <> 'approved_bounded_exposure' "
            "OR policy_reference IS NOT NULL",
            name="ck_spending_controls_policy_needs_reference",
        ),
        Index(
            "ix_spending_controls_open",
            "state",
            postgresql_where=text("state IN ('requested', 'outcome_unknown')"),
            sqlite_where=text("state IN ('requested', 'outcome_unknown')"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    carrier_line_id: UUID = Field(
        sa_column=Column(
            ForeignKey("carrier_lines.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    enforcement: Enforcement = Field(
        default=Enforcement.NONE,
        sa_column=_enum(Enforcement, "spending_enforcement", Enforcement.NONE),
    )
    state: ControlState = Field(
        default=ControlState.REQUESTED,
        sa_column=_enum(ControlState, "spending_control_state", ControlState.REQUESTED),
    )
    requested_limit_bytes: int | None = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    confirmed_limit_bytes: int | None = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    #: The approval artefact for a bounded-exposure policy — a decision record,
    #: not a checkbox. Free text for the same reason `sales_markets` uses it.
    policy_reference: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    #: The supplier's documented maximum overshoot, when one is documented. Null
    #: means unquantified, which is different from zero and is why Telnyx does
    #: not get `PROVIDER_HARD_LIMIT` today.
    max_overshoot_bytes: int | None = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    detail: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    requested_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    confirmed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class OrganizationSpendingPolicy(SQLModel, table=True):
    """An organization's cap on connectivity spend, per currency.

    Per currency because a cap is money and money has a currency; a single
    number covering NGN and USD would be adding unrelated balances, which
    `app/money.py` exists to make impossible.

    Deliberately small. Chunk 24 owns enterprise budgets, reports and
    offboarding; this is the part chunk 17 needs to refuse a top-up that would
    exceed a cap, and nothing more.
    """

    __tablename__ = "organization_spending_policies"
    __table_args__ = (
        currency_check("organization_spending_policies"),
        UniqueConstraint(
            "organization_id", "currency", name="uq_org_spending_policies_identity"
        ),
        CheckConstraint("period_cap_amount >= 0", name="ck_org_spending_policies_cap"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(
        sa_column=Column(
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    currency: str = Field(sa_column=currency_column())
    period_cap_amount: Decimal = Field(sa_column=money_column())
    #: False while a cap is being trialled. An advisory cap that silently blocks
    #: purchases, or an enforced one that silently does not, are both worse than
    #: saying which it is.
    enforced: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default="true")
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AllowanceNotice(SQLModel, table=True):
    """Which low-balance threshold has already been announced for a line.

    Without this, every poll re-announces the same threshold and a customer gets
    a notification every five minutes until they top up — which is how people
    learn to turn notifications off, including the one that matters.

    The unique constraint is the whole mechanism: crossing 80% twice, because
    usage was corrected downward and then back up, notifies once.
    """

    __tablename__ = "allowance_notices"
    __table_args__ = (
        UniqueConstraint(
            "entitlement_id", "kind", "threshold_percent", name="uq_allowance_notices"
        ),
        CheckConstraint(
            "threshold_percent > 0 AND threshold_percent <= 100",
            name="ck_allowance_notices_threshold",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    entitlement_id: UUID = Field(
        sa_column=Column(
            ForeignKey("entitlements.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    #: `data` or `voice` — the two allowances run out independently.
    kind: str = Field(sa_column=Column(String(16), nullable=False))
    threshold_percent: int = Field(sa_column=Column(Integer, nullable=False))
    notified_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
