"""Response shapes for the consumer session and service surface (US-37).

Nothing here is a claim the domain has not already made. `ready_to_use` is the
one derived field, and it is derived from separately recorded facts -- an
installation the *device* reported, an activation the *carrier* reported -- never
from the fact that we sold something.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from app.auth.models import Locale


class ServiceState(str, Enum):
    """The three states navigation and Home actually branch on (AC-37.1).

    `PENDING` is not a loading state. It means a real service exists and is not
    usable yet -- paid but unprovisioned, provisioned but not installed,
    installed but not activated. The app must be able to tell that apart from
    having nothing, because the route out is completely different: one is "buy
    something", the other is "here is where your order got to".
    """

    NONE = "none"
    PENDING = "pending"
    ACTIVE = "active"


class ServiceDelivery(str, Enum):
    """How a service reaches the customer.

    The calling amendment requires an internet-only journey that never asks for
    an eSIM installation. That is not a UI preference: an internet-calling grant
    has no carrier line and no profile to install, so asking would be asking for
    something that does not exist. This field is what the app branches on.
    `DeviceEligibilityRule.requires_esim` distinguishes the offer before
    provisioning; an installation or carrier-line row confirms carrier delivery
    once either exists. Product kind and product name are never discriminators.
    """

    CARRIER_ESIM = "carrier_esim"
    INTERNET = "internet"


class ServiceOwner(str, Enum):
    PERSONAL = "personal"
    ORGANIZATION = "organization"


class ServiceSummary(BaseModel):
    """One line of connectivity, as the customer's account sees it."""

    order_item_id: UUID
    order_id: UUID
    order_reference: str
    product_name: str
    delivery: ServiceDelivery
    owner: ServiceOwner
    #: Present only for an organization-provided service. AC-37 requires
    #: personal and work services to stay distinguishable on the same account.
    organization_id: UUID | None = None
    organization_name: str | None = None

    payment_state: str
    provisioning_state: str
    #: Null for an internet service: there is no profile, so "not installed"
    #: would be a false negative rather than a fact.
    installation_state: str | None = None
    activation_state: str | None = None

    requires_installation: bool
    ready_to_use: bool
    #: Set when the entitlement exists. Null before provisioning grants one.
    granted_at: datetime | None = None
    expires_at: datetime | None = None
    expired: bool = False


class ServicesResponse(BaseModel):
    service_state: ServiceState
    services: list[ServiceSummary]


class OrganizationMembershipSummary(BaseModel):
    organization_id: UUID
    name: str
    role: str


class SessionResponse(BaseModel):
    """Everything the app needs before it can draw its first authenticated frame.

    One request, deliberately: the alternative is a tab bar that renders, then
    re-renders once the service call lands, which is the flicker every "no
    service" screen in the old app had.
    """

    user_id: UUID
    locale: Locale
    #: Verified identifiers only. An unverified claim is not an identity, and
    #: showing it as one is how an invitation gets accepted by the wrong person.
    verified_emails: list[str]
    verified_phone_numbers: list[str]
    service_state: ServiceState
    organizations: list[OrganizationMembershipSummary]
    pending_invitations: int


class InvitationPreviewRequest(BaseModel):
    """The token travels in the body, not the path.

    A path segment reaches access logs, proxy logs and crash reports. An
    invitation token is a bearer credential for a membership, so it goes where
    those do not follow.
    """

    token: str


class InvitationPreviewState(str, Enum):
    PENDING = "pending"
    EXPIRED = "expired"
    ACCEPTED = "accepted"
    REVOKED = "revoked"


class InvitationPreviewResponse(BaseModel):
    """What an invitation link says, before anything is claimed.

    Returned to an authenticated caller only, and it never widens what that
    caller could otherwise learn: the address is masked, and `recipient_matches`
    answers "is this for me" without disclosing who else it might be for.
    """

    state: InvitationPreviewState
    organization_name: str
    role: str
    #: `j****e@example.com` -- enough for the invited person to recognize their
    #: own address, not enough for anyone else to learn it.
    invited_value_masked: str
    invited_kind: str
    expires_at: datetime | None = None
    recipient_matches: bool
    #: True when the caller is already an active member. The app shows "you are
    #: already in this organization" rather than an accept button that 409s.
    already_a_member: bool
