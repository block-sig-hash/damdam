"""Request and response shapes for the account area — US-38, chunk 21.

Money crosses as a string everywhere, following chunk 19: a price that travels
as a float can come back a hundredth different from the one that was shown, and
a receipt is the one document where that is unarguable.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.account.models import (
    NotificationCategory,
    NotificationChannel,
    SessionPlatform,
    SupportCategory,
)


class SessionView(BaseModel):
    """One device, described for the person deciding whether to revoke it."""

    session_id: UUID
    platform: SessionPlatform
    device_label: str | None = None
    app_version: str | None = None
    last_seen_city: str | None = None
    last_seen_country: str | None = None
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None
    #: True for the device making this request, so the app can label it and
    #: warn before signing itself out.
    is_current: bool = False


class SessionListResponse(BaseModel):
    sessions: list[SessionView]


class RevokeAllRequest(BaseModel):
    """Sign everything out, optionally sparing one device.

    The device to keep is named explicitly rather than inferred from the
    request, because an access token does not carry the id of the session it
    came from and inferring it would mean guessing. The named session is still
    verified against the caller — it is skipped only if it appears in *their*
    device list — so naming somebody else's spares nothing.

    Omitting it signs out every device including this one, which is the right
    default for "my phone was stolen" and is what the app asks for when the
    customer confirms they are signing themselves out too.
    """

    keep_session_id: UUID | None = None


class RevokeAllResponse(BaseModel):
    revoked: int


class ReceiptLineView(BaseModel):
    description: str
    quantity: int
    unit_amount: Decimal
    total_amount: Decimal


class ReceiptView(BaseModel):
    order_id: UUID
    reference: str
    placed_at: datetime
    currency: str
    total_amount: Decimal
    payment_state: str
    lines: list[ReceiptLineView]
    organization_id: UUID | None = None


class ReceiptListResponse(BaseModel):
    receipts: list[ReceiptView]


class SupportRequestCreate(BaseModel):
    category: SupportCategory
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    #: Optional references. Verified against this customer before they are
    #: stored — an unverified reference would attach a ticket to somebody
    #: else's order and have an agent open it in good faith.
    order_id: UUID | None = None
    entitlement_id: UUID | None = None


class SupportRequestView(BaseModel):
    request_id: UUID
    reference: str
    category: SupportCategory
    state: str
    subject: str
    created_at: datetime
    order_id: UUID | None = None
    entitlement_id: UUID | None = None
    subject_summary: str | None = None


class SupportRequestListResponse(BaseModel):
    requests: list[SupportRequestView]


class PreferenceView(BaseModel):
    category: NotificationCategory
    channel: NotificationChannel
    enabled: bool


class PreferenceListResponse(BaseModel):
    #: Only the categories this product actually sends. A preference row for
    #: something nobody sends is a feature that exists, switched off.
    preferences: list[PreferenceView]


class PreferenceUpdate(BaseModel):
    category: NotificationCategory
    channel: NotificationChannel
    enabled: bool


class DeletionBlockerView(BaseModel):
    """A reason, in a form the app can localize and the customer can act on."""

    kind: str
    code: str
    amount: Decimal | None = None
    currency: str | None = None


class DeletionPreflightResponse(BaseModel):
    may_delete: bool
    blockers: list[DeletionBlockerView]


class ExportJobView(BaseModel):
    export_id: UUID
    state: str
    requested_at: datetime
    completed_at: datetime | None = None
    expires_at: datetime | None = None
