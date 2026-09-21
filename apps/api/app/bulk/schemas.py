"""Request and response shapes for bulk provisioning (US-40, chunk 23)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.bulk.models import ActivationRequestState, BulkItemState, BulkJobState


class BulkJobCreate(BaseModel):
    """Choose a product and a list of this organization's own people."""

    #: The client's key. Replaying it returns the job that already exists — a
    #: double-clicked "buy for these fifty people" is one job, not two.
    idempotency_key: str = Field(min_length=8, max_length=200)
    product_id: UUID
    #: Which market this is bought in. Names the seller and the currency, the
    #: same way a consumer quote does — an organization's country is not a
    #: field we hold, and guessing one would pick a seller nobody chose.
    country: str = Field(min_length=2, max_length=2)
    currency: str = Field(min_length=3, max_length=3)
    person_ids: list[UUID] = Field(min_length=1, max_length=500)


class BulkItemView(BaseModel):
    item_id: UUID
    person_id: UUID
    state: BulkItemState
    #: Why this one recipient has no line, in a code the dashboard localizes.
    error_code: str | None = None
    order_item_id: UUID | None = None
    provisioned_at: datetime | None = None


class BulkJobProgressView(BaseModel):
    """Counts a screen must show as they are, not rounded to done or failed.

    `outstanding` is derived rather than stored: it is whatever has not reached
    a terminal state, and a stored copy would be a second answer that lags.
    """

    job_id: UUID
    state: BulkJobState
    recipient_count: int
    reserved: int
    provisioned: int
    failed: int
    unknown: int
    invalid: int
    cancelled: int
    outstanding: int


class BulkJobView(BaseModel):
    job_id: UUID
    state: BulkJobState
    product_id: UUID
    currency: str
    unit_amount: Decimal
    recipient_count: int
    order_id: UUID | None = None
    created_at: datetime
    completed_at: datetime | None = None


class BulkJobListResponse(BaseModel):
    jobs: list[BulkJobView]


class BulkItemListResponse(BaseModel):
    items: list[BulkItemView]


class CancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=64)


class ActivationRequestView(BaseModel):
    """An invitation to claim a line.

    Carries **no** installation or network state, deliberately. Those are
    separate facts on separate tables, and a view that mixed them would let a
    dashboard report staff as connected on the strength of an email.
    """

    request_id: UUID
    item_id: UUID
    person_id: UUID
    state: ActivationRequestState
    delivered_to: str | None = None
    expires_at: datetime
    redeemed_at: datetime | None = None


class ActivationRequestIssued(BaseModel):
    """The one and only time the token crosses the wire."""

    request: ActivationRequestView
    #: Shown once, to be delivered to the recipient. Never stored in plaintext
    #: and never returned again — a table of live tokens is a table of
    #: credentials, readable by every administrator of the tenant.
    token: str


class BulkActivationRedeemRequest(BaseModel):
    """Claim a work line bought in bulk.

    Named `Bulk…` rather than `ActivationRedeemRequest` because chunk 15
    already publishes a schema by that name for redeeming an eSIM activation
    code. Two Pydantic models sharing a class name silently collapse into one
    entry in the generated OpenAPI — the drift check caught it as ten deleted
    lines, which is the whole reason that check exists.
    """

    token: str = Field(min_length=16, max_length=200)
