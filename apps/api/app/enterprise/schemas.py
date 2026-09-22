"""Request and response shapes for enterprise funding, reports and offboarding."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.enterprise.models import (
    OffboardingActionKind,
    OffboardingActionState,
    OffboardingState,
)


class FundingView(BaseModel):
    """What an organization has and may spend — three different things.

    `period_cap` and `headroom` are `null` when nobody has recorded a policy.
    That is **undecided**, not unlimited, and a client that renders a missing cap
    as infinity is inventing a commitment.
    """

    currency: str
    balance: Decimal
    held: Decimal
    available: Decimal
    period_cap: Decimal | None = None
    #: Authorized or paid purchases; consumes policy headroom but is not all
    #: settled spend.
    committed_this_period: Decimal
    spent_this_period: Decimal
    headroom: Decimal | None = None
    #: Always false today, and carried explicitly so a dashboard cannot render a
    #: shared bucket by assuming one. No supplier pooling capability exists.
    pooling: bool = False
    pooling_note: str


class DepartmentTotalView(BaseModel):
    key: str
    label: str
    people: int
    lines: int
    #: What was bought. Known the moment an order is placed.
    purchased_amount: Decimal
    #: What was metered. Arrives late — see `observed_through`.
    usage_amount: Decimal
    currency: str


class DepartmentalReportView(BaseModel):
    organization_id: UUID
    currency: str
    period_from: datetime
    period_to: datetime
    totals: list[DepartmentTotalView]
    purchased_total: Decimal
    usage_total: Decimal
    #: The latest usage this organization's lines have been observed to.
    #: **`null` means nothing has been observed**, which is not the same as zero
    #: used — a stalled poller and an unused line look identical without it.
    observed_through: datetime | None = None


class OffboardingRequest(BaseModel):
    person_id: UUID
    reason: str | None = Field(default=None, max_length=200)


class OffboardingActionView(BaseModel):
    action_id: UUID
    kind: OffboardingActionKind
    state: OffboardingActionState
    target_reference: str | None = None
    detail: str | None = None
    requested_at: datetime
    confirmed_at: datetime | None = None


class OffboardingView(BaseModel):
    """A departure, including what is still outstanding with a carrier."""

    offboarding_id: UUID
    person_id: UUID
    state: OffboardingState
    confirmed: int
    pending_carrier: int
    not_applicable: int
    failed: int
    requested_at: datetime
    completed_at: datetime | None = None


class OffboardingDetailView(OffboardingView):
    actions: list[OffboardingActionView]


class OffboardingListResponse(BaseModel):
    offboardings: list[OffboardingView]
