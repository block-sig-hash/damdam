"""The provider-neutral connectivity contract (US-35, chunk 15).

Every carrier is reached through this, and nothing above it knows which one it
is talking to. `AGENTS.md` states the rule directly: *all third-party vendor
integrations go through an internal abstraction layer, never called directly
from route handlers or UI components*, and *each adapter advertises its
capabilities*.

The capability half is the part that does real work here. A supplier's data
footprint says nothing about whether it can issue a voice-capable profile, and
selling a native-voice plan against a data-only adapter produces a customer
holding a line that cannot make calls. So an adapter does not get to be
"connected" or "not connected" — it declares, one capability at a time, what it
can actually do, with the evidence that established each claim.

Three rules the surface below enforces rather than documents:

1. **A capability that has not been verified does not exist.** `Capability` is
   an explicit set; anything absent is absent. There is no default-true.
2. **An unknown outcome is not a failure.** `ConnectivityOutcomeUnknown` is a
   distinct exception from `ConnectivityError` because a lost response routes
   to reconciliation and a refusal routes to a retry, and collapsing them is
   how a customer's eSIM gets bought twice.
3. **Delivering a profile is not installing it, and installing it is not being
   on a network.** The three results below are separate types for that reason,
   and no adapter method returns a state it did not observe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol
from uuid import UUID


class Capability(str, Enum):
    """One thing an adapter can do, verified.

    These line up deliberately with `ProviderOffering`'s boolean columns
    (chunk 09), which is what lets the catalog refuse to publish a native-voice
    product against an adapter that cannot issue one. A capability listed here
    and absent from the offering is a configuration mistake; a capability on the
    offering and absent here is an adapter that cannot deliver what was sold.
    """

    DATA = "data"
    NATIVE_VOICE = "native_voice"
    NUMBER_ASSIGNMENT = "number_assignment"
    #: Can the *profile itself* be handed to a customer to install? Separate
    #: from DATA because a supplier can sell connectivity through a channel
    #: that never exposes an activation code to us.
    ACTIVATION_CREDENTIAL = "activation_credential"
    SUSPENSION = "suspension"
    TOPUP = "topup"
    #: A supplier-side hard limit that stops usage without the app's help.
    #: Chunk 17 will not present an app-side balance as a hard cap without it.
    SPENDING_ENFORCEMENT = "spending_enforcement"
    #: A cumulative consumption counter on the line.
    USAGE_COUNTER = "usage_counter"
    #: Per-session or per-event usage records. Chunk 16 needs one of these two,
    #: and they reconcile very differently.
    USAGE_EVENTS = "usage_events"


@dataclass(frozen=True)
class AdapterCapabilities:
    """What one adapter can do, and what established each claim.

    `evidence_reference` is not decoration. `AGENTS.md`: *a mock passing itself
    is not evidence of external compatibility.* An adapter that claims native
    voice on the strength of its own fake is claiming nothing, and the evidence
    reference is where a reviewer looks to find out which it is.
    """

    supported: frozenset[Capability]
    #: How stale a usage reading from this supplier can be, when documented.
    #: `None` means *undocumented*, which is different from zero and must be
    #: surfaced to the customer as "we do not know", not as "up to date".
    usage_latency_seconds: int | None = None
    evidence_reference: str | None = None
    verified_at: datetime | None = None
    #: Capabilities the supplier's documentation neither grants nor denies,
    #: with the reason. Kept apart from plain absence so a reviewer can tell
    #: "we checked and it is not there" from "nobody looked".
    undocumented: dict[str, str] = field(default_factory=dict)

    def supports(self, capability: Capability) -> bool:
        return capability in self.supported

    def require(self, capability: Capability) -> None:
        if capability not in self.supported:
            raise CapabilityNotAvailable(capability, self.undocumented.get(
                capability.value
            ))


class ConnectivityError(Exception):
    """The supplier refused, definitively, or we could not form the request."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


class ConnectivityOutcomeUnknown(Exception):
    """The request may or may not have been accepted. That is the point.

    Deliberately not a subclass of `ConnectivityError`: an `except
    ConnectivityError` that swallowed this would turn a lost response into a
    refusal, and a refusal looks retryable. That retry is the double purchase.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class CapabilityNotAvailable(ConnectivityError):
    """Asked for something this supplier is not verified to do.

    Raised rather than returned so it cannot be ignored by a caller that only
    checks a result for truthiness.
    """

    def __init__(self, capability: Capability, reason: str | None = None) -> None:
        self.capability = capability
        super().__init__(
            "capability_not_available",
            reason
            or f"this adapter does not advertise {capability.value}",
        )


class ProviderLineState(str, Enum):
    """What the supplier says about a line, before we interpret it.

    Kept separate from `ActivationState` and `NetworkState` on purpose. This is
    a supplier's vocabulary; ours is a set of independent questions. Mapping
    happens in one named place (`app/connectivity/service.py`), so a supplier
    inventing a new status changes one function rather than every call site.
    """

    #: The supplier has the line but it is not usable yet.
    PROVISIONED = "provisioned"
    #: In the middle of a transition. Ask again; do not act on it.
    TRANSITIONING = "transitioning"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    #: The supplier stopped it for a reason of its own — a data cap, a device
    #: restriction, a billing problem. Not the same as us suspending it.
    RESTRICTED = "restricted"
    TERMINATED = "terminated"


@dataclass(frozen=True)
class ProviderLine:
    """One line as the supplier currently describes it.

    `installation_released` is named for what the supplier actually knows.
    Telnyx's `esim_installation_status: released` means the profile was released
    for download — **not** that it reached a handset, which nobody at the
    supplier can observe. Calling this field `installed` would be the single
    most tempting lie in this integration.
    """

    provider_reference: str
    state: ProviderLineState
    #: The supplier's own status string, kept verbatim for reconciliation and
    #: support. An operator asking "what does Telnyx think" gets an answer.
    provider_status: str
    iccid: str | None = None
    msisdn: str | None = None
    voice_enabled: bool | None = None
    installation_released: bool | None = None
    #: True while the supplier reports an action in flight. A snapshot taken
    #: mid-transition is not evidence of the destination.
    actions_in_progress: bool | None = None
    consumed_bytes: int | None = None
    data_limit_bytes: int | None = None
    observed_at: datetime | None = None


@dataclass(frozen=True)
class ProviderAction:
    """An asynchronous state change the supplier accepted but has not finished.

    Every Telnyx lifecycle endpoint returns 202 with one of these: *"All state
    changes return 202 with a SIM Card Action — they are not instant."* A
    caller that treats the 202 as the change having happened will tell a
    customer their line is suspended while it is still passing traffic.
    """

    provider_reference: str
    #: `None` while the supplier has not settled it.
    succeeded: bool | None
    settled: bool
    provider_status: str
    reason: str | None = None


@dataclass(frozen=True)
class ProvisionResult:
    """What one provisioning request produced.

    A quantity-based supplier can partially succeed — Telnyx's purchase
    endpoint returns `data` and `errors` in the same 202 — so this carries the
    lines it actually got and refuses to pretend a shortfall is a failure.
    """

    lines: tuple[ProviderLine, ...]
    #: Supplier error codes returned alongside whatever succeeded.
    errors: tuple[str, ...] = ()
    #: Set when the supplier definitively refused everything.
    rejection_reason: str | None = None

    @property
    def accepted(self) -> bool:
        return bool(self.lines)


@dataclass(frozen=True)
class ActivationCredential:
    """Installation material for one line. Handle as a secret.

    `secret` is the LPA activation string. It is one-time use with Telnyx: a
    lost profile cannot be re-downloaded and needs a fresh purchase, so leaking
    it into a log is not an information disclosure that can be shrugged off —
    it is a disclosure of something that cannot be rotated.
    """

    secret: str
    one_time_use: bool = True

    def __repr__(self) -> str:
        return f"ActivationCredential(<redacted>, one_time_use={self.one_time_use})"

    __str__ = __repr__


class ConnectivityAdapter(Protocol):
    """The whole surface a carrier must present. Deliberately small.

    D1 is open. This is written to be satisfiable by whichever supplier is
    eventually contracted rather than shaped around Telnyx's API, which is why
    nothing in the signatures below is a Telnyx noun.
    """

    name: str

    def capabilities(self) -> AdapterCapabilities: ...

    def provision(
        self, operation_reference: UUID, quantity: int, options: dict[str, Any]
    ) -> ProvisionResult:
        """Buy lines. Raises `ConnectivityOutcomeUnknown` on a lost response."""
        ...

    def reconcile(
        self, operation_reference: UUID, quantity: int
    ) -> ProvisionResult | None:
        """What did that exact request produce? `None` if unknowable.

        `None` is a real answer and the most important one. It means the
        supplier cannot tell us, and the caller must stop rather than guess.
        """
        ...

    def fetch_line(self, provider_reference: str) -> ProviderLine | None: ...

    def fetch_activation_credential(
        self, provider_reference: str
    ) -> ActivationCredential:
        """Retrieve the installation material. Requires ACTIVATION_CREDENTIAL."""
        ...

    def enable_voice(self, provider_reference: str) -> ProviderAction:
        """Request voice on the line. Requires NATIVE_VOICE."""
        ...

    def assigned_number(self, provider_reference: str) -> str | None:
        """The E.164 number the supplier assigned, if any yet."""
        ...

    def set_state(
        self, provider_reference: str, target: ProviderLineState
    ) -> ProviderAction:
        """Request a lifecycle transition. Asynchronous by contract."""
        ...

    def fetch_action(self, provider_action_reference: str) -> ProviderAction | None:
        """Has that asynchronous change settled, and did it work?"""
        ...
