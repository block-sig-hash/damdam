"""What My Line tells the customer (US-38, chunk 20).

The shape follows one rule, taken from `prd.md` and enforced by chunk 05's
schema: **payment, provisioning, installation, activation and network
attachment are separate facts, and each is reported with when it was observed.**
They genuinely disagree — a profile can sit installed on a phone that never
attaches, and a line can be suspended with the profile still on the device — so
nothing here collapses them into a single "status" that would have to lie about
at least one.

Anything the app might otherwise *infer* is answered explicitly instead, with a
reason attached. `native_calling.available` is not "the plan included voice"; it
is what the carrier last said about this line. `reinstall_available` is not "the
profile is gone"; it is whether the supplier can re-issue it, which for a
one-time-use eSIM is no.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class LineDelivery(str, Enum):
    CARRIER_ESIM = "carrier_esim"
    INTERNET = "internet"


class NumberStatus(str, Enum):
    """Three answers, because "no number shown" has three different meanings."""

    #: A number is live on this line right now.
    ASSIGNED = "assigned"
    #: The plan includes one and the carrier has not assigned it yet.
    PENDING = "pending"
    #: The plan includes no number at all. Not a delay — a fact about the plan.
    NOT_INCLUDED = "not_included"


class AssignedNumberView(BaseModel):
    e164: str
    country: str
    assigned_at: datetime


class InstallationView(BaseModel):
    """The device's half of the story, and only the device's."""

    state: str
    installed_at: datetime | None
    #: When the supplier released the profile for download. Not an installation.
    profile_released_at: datetime | None
    #: True when sealed installation material exists and can be delivered under
    #: a grant. False with a reason is far more useful than an empty screen.
    credential_available: bool
    credential_unavailable_reason: str | None
    #: How many times the profile has been delivered. Shown because a customer
    #: who has already revealed a one-time code needs to know that happened.
    delivery_count: int
    one_time_use: bool
    #: For a one-time-use profile this is **false**, always. Telnyx documents
    #: that a downloaded profile cannot be re-downloaded; a replacement device
    #: needs a new purchase, and the app must say so rather than offer a button
    #: that cannot work.
    reinstall_available: bool
    reinstall_blocked_reason: str | None


class LineStateView(BaseModel):
    carrier: str
    activation_state: str
    network_state: str
    network_state_observed_at: datetime | None
    #: The carrier's own words for its status, when it gives any.
    provider_status: str | None
    provider_status_observed_at: datetime | None
    voice_enabled: bool
    voice_enabled_observed_at: datetime | None


class UsageView(BaseModel):
    data_bytes_total: int
    data_bytes_used: int
    data_bytes_remaining: int
    voice_seconds_total: int
    voice_seconds_used: int
    voice_seconds_remaining: int
    #: The latest measurement's end, not the latest poll. A poll that returned
    #: nothing proves the poller is alive; it does not make an old figure newer.
    observed_at: datetime | None
    #: `fresh` | `stale` | `unknown`. `unknown` means nobody has ever measured
    #: this line, and the grant is all there is — which must not be presented
    #: as a measurement.
    freshness: str
    #: True when some counted usage is still provisional and may be revised.
    has_provisional: bool
    expires_at: datetime | None
    expired: bool


class RestrictionView(BaseModel):
    """Whether anything is stopping this line carrying traffic, and who said so."""

    suspended: bool
    #: `none` | `provider` | ... — who is actually enforcing a cap. `none` means
    #: nothing is enforcing one, which is not the same as having no cap set.
    enforcement: str
    control_state: str
    requested_limit_bytes: int | None
    #: What the supplier actually confirmed. Separate from the requested figure
    #: for the whole time a change is in flight, because showing the request as
    #: the cap tells a customer their limit moved when it has not.
    confirmed_limit_bytes: int | None
    detail: str | None


class TopUpView(BaseModel):
    #: Only top-ups that are actually spendable are counted here.
    applied_data_bytes: int
    applied_voice_seconds: int
    applied_extra_days: int
    #: Paid for, not yet usable. Shown so a customer who has paid is never told
    #: they have nothing pending.
    pending_count: int


class CallDestinationView(BaseModel):
    country: str
    destination_kind: str
    per_minute_amount: str
    setup_amount: str
    increment_seconds: int
    minimum_seconds: int


class TariffView(BaseModel):
    version: int
    currency: str
    destinations: list[CallDestinationView]


class CallingView(BaseModel):
    """Native calling and internet calling, deliberately kept apart.

    The approved calling amendment is explicit that these are distinct
    capabilities, and that launching the phone dialer proves nothing about which
    SIM was chosen, whether the line was attached, or whether a call happened.
    So this reports only what is *known* about each, and the app is built so
    that opening the dialer is guidance rather than an outcome.
    """

    native_available: bool
    native_unavailable_reason: str | None
    #: False until V04 is accepted and enabled. The app must not offer an
    #: internet dialer it does not have.
    internet_dialer_enabled: bool
    internet_dialer_reason: str | None
    #: True when this device may hold more than one line, so the customer has to
    #: be told how to pick this one. The client reports it; the server only says
    #: whether picking matters for this line at all.
    requires_line_selection: bool


class LineSummary(BaseModel):
    entitlement_id: UUID
    order_id: UUID
    order_reference: str
    product_name: str
    delivery: LineDelivery
    number_status: NumberStatus
    e164: str | None
    activation_state: str | None
    installation_state: str | None
    ready_to_use: bool
    expires_at: datetime | None
    expired: bool


class LineListResponse(BaseModel):
    lines: list[LineSummary]


class LineDetailResponse(BaseModel):
    entitlement_id: UUID
    order_id: UUID
    order_reference: str
    order_item_id: UUID
    product_id: UUID
    product_name: str
    delivery: LineDelivery
    ready_to_use: bool

    number_status: NumberStatus
    assigned_number: AssignedNumberView | None

    #: Null for an internet-calling grant: there is no profile and no line, and
    #: `not_installed` would be a false negative rather than a fact.
    installation: InstallationView | None
    line: LineStateView | None

    usage: UsageView
    restriction: RestrictionView | None
    top_ups: TopUpView
    tariff: TariffView | None
    calling: CallingView


class InstallationGrantResponse(BaseModel):
    """Authorization to fetch the profile once — never the profile itself.

    The token is returned here and is not stored server-side in a usable form;
    the row keeps a keyed fingerprint. A response that carried the activation
    code would put installation material into every log, proxy and crash report
    between here and the phone.
    """

    grant_token: str
    expires_at: datetime
    #: Repeated from the installation view so a client that went straight to a
    #: grant still knows it is spending a one-time profile.
    one_time_use: bool
    delivery_count: int


class InstallationRedeemRequest(BaseModel):
    grant_token: str


class InstallationCredentialResponse(BaseModel):
    """The profile, once.

    Served with `Cache-Control: no-store`. The `lpa` is the whole secret: anyone
    holding it can install the profile instead of the customer, and a Telnyx
    profile cannot be re-downloaded, so there is nothing to rotate afterwards.
    """

    entitlement_id: UUID
    #: `LPA:1$…` — the activation string a phone consumes, as a QR code or typed.
    lpa: str
    one_time_use: bool
    delivery_count: int
    #: Repeated here because this is the screen where it matters: after this,
    #: there is no second copy.
    reinstall_available: bool


class InstallationConfirmRequest(BaseModel):
    """The device reporting what it did.

    `installed: false` is accepted and recorded as *not* installed rather than
    ignored — a failed install that leaves the record saying "installed" is how
    a customer ends up being told their line is ready when nothing is on the
    phone.
    """

    installed: bool
