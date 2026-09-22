"""Request and response shapes for the internal operations surface.

Two conventions run through this file and both are deliberate.

**Every action carries a reason and an idempotency key, required.** They are not
optional fields with a server-side default, because a default reason is no
reason and a server-generated key makes a replay a second action. A client that
cannot supply them is a client that should not be taking these actions.

**No response shape can carry activation material.** There is no field for an
LPA string, an activation code or a full ICCID anywhere below. Masking is not
applied at the edge as a formatting step — the views simply have nowhere to put
the thing, which is the only version of that rule that survives a refactor.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.operations.models import OperatorActionKind, OperatorSubjectKind
from app.refunds.models import ExceptionKind


class ActionRequest(BaseModel):
    """The two fields every constrained action needs from its caller."""

    model_config = ConfigDict(extra="forbid")

    #: Why. Stored, immutable, and required by a database check as well as here
    #: — a form is one client release away from not asking.
    reason: str = Field(min_length=1, max_length=500)
    #: The caller's key for *this decision*. Replaying it returns the decision
    #: that exists rather than taking a second one.
    idempotency_key: str = Field(min_length=1, max_length=200)


class SupplierResolutionRequest(ActionRequest):
    """Settle a supplier attempt whose outcome we lost.

    The attempt itself must already be `held_for_review`, which is the durable
    result of reconciling the original operation against the original supplier.
    The request deliberately has no "reconciled" checkbox: caller testimony is
    not evidence that the supplier was asked.
    """

    succeeded: bool
    #: Required when `succeeded` is true: the supplier's own reference for the
    #: work being confirmed. A confirmed success with nothing behind it is an
    #: operator's word, and the schema for supplier attempts already refuses it.
    provider_reference: str | None = Field(default=None, max_length=200)
    exception_item_id: UUID | None = None


class PaymentDiscrepancyRequest(ActionRequest):
    """Match one reconciled bank receipt to a customer service-credit account."""

    customer_account_id: UUID
    exception_item_id: UUID


class CallSettlementCorrectionRequest(ActionRequest):
    """Replace one call charge through V03's bounded correction path."""

    billable_seconds: int = Field(ge=0)
    setup_amount: Decimal = Field(ge=0)
    usage_amount: Decimal = Field(ge=0)
    exception_item_id: UUID


class LineLookupRequest(ActionRequest):
    """Find a line from what a customer can read out loud.

    Exactly one identifier, because a lookup that accepts several and quietly
    prefers one is a lookup whose result nobody can explain.
    """

    line_id: UUID | None = None
    iccid: str | None = Field(default=None, max_length=22)
    e164: str | None = Field(default=None, max_length=16)


class OperatorActionView(BaseModel):
    id: UUID
    kind: OperatorActionKind
    subject_kind: OperatorSubjectKind
    subject_reference: str
    actor_admin_id: UUID
    reason: str
    idempotency_key: str
    before_state: dict[str, Any]
    after_state: dict[str, Any]
    #: Set only when money moved, and then it names a balanced journal entry.
    ledger_entry_id: UUID | None = None
    created_at: datetime


class OperatorActionListResponse(BaseModel):
    actions: list[OperatorActionView]


class QueueEntryView(BaseModel):
    exception_id: UUID
    kind: ExceptionKind
    subject_reference: str
    detail: str
    raised_at: datetime
    resolved_at: datetime | None = None
    #: How many operator actions already name this subject. An item two people
    #: have already acted on is worth reading before a third acts on it.
    action_count: int = 0


class QueueResponse(BaseModel):
    entries: list[QueueEntryView]


class LineSupportView(BaseModel):
    """Enough to confirm a line is the right one. Never enough to use it.

    `iccid_masked` and `e164_masked` show trailing digits only. There is no
    unmasked variant of this view and no endpoint that returns one: the
    activation credential chunk 15 stores is not readable from this surface at
    all, by any operator, for any reason.
    """

    line_id: UUID
    carrier: str
    iccid_masked: str | None = None
    e164_masked: str | None = None
    activation_state: str
    network_state: str
    #: The carrier's own words, kept verbatim by chunk 15. An operator asking
    #: "but what does the carrier say" gets an answer, not our interpretation.
    provider_status: str | None = None
    voice_enabled: bool
    organization_id: UUID | None = None
    holder_user_id: UUID | None = None
    #: The audit row written because this was read. Returned so the operator can
    #: see that looking was recorded, rather than being told so by a footer.
    access_action_id: UUID
