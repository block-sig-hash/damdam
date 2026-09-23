"""Request and response shapes for the calling API.

Two things are deliberately absent from every response here.

**Provider nouns.** No `call_control_id`, no connection id, no Telnyx anything.
A client that learned a provider identifier would start correlating on it, and
V01's invariant 7 is that our attempt-to-leg mapping is authoritative while
provider identifiers are corroboration. Keeping them server-side keeps that true.

**Anything credential-shaped**, except in the one response whose entire purpose
is to deliver a short-lived token. `ClientSessionResponse` is that response, and
it is the only one.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class EligibilityResponse(BaseModel):
    """What a call would cost, before anybody commits to it.

    `route_enabled` is reported rather than implied. A price with no route is a
    quote for something that cannot be bought, and a client that cannot tell the
    difference will show a working call button.
    """

    destination_e164: str
    destination_country: str
    destination_kind: str
    #: Server-selected presentation identity. Previewed before any hold so a
    #: caller knows which number the recipient will see before committing.
    identity_e164: str
    currency: str
    max_seconds: int
    max_charge_amount: Decimal
    rate_per_minute_amount: Decimal
    setup_amount: Decimal
    available_amount: Decimal
    fundable: bool
    route_enabled: bool


class ClientSessionRequest(BaseModel):
    #: The client's own stable installation identifier. One credential per
    #: device, so this is what a revocation later names.
    device_id: str = Field(min_length=1, max_length=200)
    device_label: str | None = Field(default=None, max_length=200)


class ClientSessionResponse(BaseModel):
    """A short-lived provider token for one device. The only secret we return.

    `expires_at` is the earlier of the token's own expiry and its parent
    credential's, so a client is never told it has a working session after the
    credential behind it has gone.
    """

    token: str
    sip_identity: str
    expires_at: datetime


class AuthorizeRequest(BaseModel):
    destination: str = Field(min_length=1, max_length=32)
    #: Supplied by the client and scoped to the caller. Replaying it returns the
    #: same attempt and the same hold rather than a second of either.
    idempotency_key: str = Field(min_length=8, max_length=200)
    currency: str = Field(min_length=3, max_length=3)
    #: Present for a work call, absent for a personal one. It is what decides
    #: the payer, and it is recorded rather than derived later.
    organization_id: UUID | None = None
    device_id: str | None = Field(default=None, max_length=200)
    requested_seconds: int | None = Field(default=None, ge=1, le=14400)


class AttemptResponse(BaseModel):
    """One call attempt, as its owner may see it."""

    attempt_id: UUID
    state: str
    destination_e164: str
    destination_country: str
    identity_e164: str
    currency: str
    max_seconds: int
    max_charge_amount: Decimal
    expires_at: datetime
    created_at: datetime
    answered_at: datetime | None = None
    ended_at: datetime | None = None
    end_reason: str | None = None
    organization_id: UUID | None = None
    #: Added by V03. `None` while the call is live, unanswered liability is
    #: still open, or settlement has been deferred for review.
    charge: ChargeView | None = None


class ChargeView(BaseModel):
    """What the call actually cost, once it has been metered — US-46, V03.

    Absent until the call is settled, and `is_final` says whether the supplier's
    own record could still move it. A UI that showed a provisional amount as
    final would be making a promise this chunk cannot keep: V01 could not
    establish how many components a call bills, so a later correction is an
    ordinary event rather than a failure.
    """

    amount: Decimal
    currency: str
    billable_seconds: int
    setup_amount: Decimal
    usage_amount: Decimal
    is_final: bool
    settled_at: datetime | None = None


class AttemptListResponse(BaseModel):
    attempts: list[AttemptResponse]


class StartResponse(BaseModel):
    """Everything the client needs for one attempt, and nothing else.

    `correlation` is echoed back to us by the provider. It points at an attempt;
    it does not authorize one, and the event path re-validates ownership from the
    database before acting on anything it names.
    """

    attempt_id: UUID
    destination_e164: str
    correlation: str
    max_seconds: int
    expires_at: datetime


class StopRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=100)


class CallEventAckResponse(BaseModel):
    """What the provider is told. Deliberately uninformative.

    `received` is true for an event we stored, including a duplicate we did not
    apply. A provider that learned which of its deliveries were novel would be
    told something about our state that it has no need for, and an attacker
    probing the endpoint would learn the same thing.

    Named distinctly rather than `WebhookResponse`, which `app/payments` and
    `app/voice` already share. Those two are structurally identical so FastAPI
    emits one schema for both; a third with a different shape would split all
    three into module-qualified names and rename two existing client-visible
    schemas as a side effect of this chunk.
    """

    received: bool
