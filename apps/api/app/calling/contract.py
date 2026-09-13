"""The provider-neutral calling boundary. No Telnyx noun appears below.

`AGENTS.md` requires every vendor integration behind an internal abstraction and
requires each adapter to advertise what it is verified to do. This is that
surface for call control, and it is deliberately *not* `app/connectivity`'s
`ConnectivityAdapter`: that one buys and manages lines, this one authorizes and
steers individual calls, and a supplier can be excellent at one and absent from
the other. Merging them would let an eSIM adapter's evidence stand in for a
calling adapter's — the substitution the calling amendment exists to prevent.

Two things here carry V01's reviewed findings directly:

- `CallingCapability.PARKED_ORIGINATION` and `SERVER_ORIGINATION` are separate
  capabilities because V01 selected the first as the preparation route and kept
  the second as a conditional fallback. An adapter declares which it can do;
  neither is assumed, and the domain above works the same either way.
- `CallOutcomeUnknown` is a distinct exception from `CallingError` for the same
  reason chunk 15 separated them: a lost response is not a refusal. Here the
  cost of collapsing them is a second PSTN leg to the same destination, billed
  twice and answered once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol
from uuid import UUID


class CallingCapability(str, Enum):
    """One thing a calling adapter is verified to do."""

    #: The client SDK originates, the provider holds the call, and the backend
    #: decides. V01's selected preparation topology.
    PARKED_ORIGINATION = "parked_origination"
    #: The backend originates both legs, including one to a registered client.
    #: V01's fallback; it keeps the destination out of the client entirely.
    SERVER_ORIGINATION = "server_origination"
    #: Join two legs the backend already knows about.
    BRIDGE = "bridge"
    #: End a leg on command.
    HANGUP = "hangup"
    #: A provider-enforced maximum duration on a leg the backend created. This
    #: is the only bound that survives the backend dying mid-call, which is why
    #: it is a named capability and not an option.
    LEG_TIME_LIMIT = "leg_time_limit"
    #: Short-lived client credentials, one per device, revocable individually.
    PER_DEVICE_CREDENTIAL = "per_device_credential"
    #: Account-proven evidence that a credential cannot reach emergency or
    #: direct PSTN routing on its own. **Nothing may declare this from
    #: documentation.** It is blocker B1, and it is the gate on live traffic.
    EMERGENCY_CONTAINMENT = "emergency_containment"


class LegRole(str, Enum):
    """Which side of the call a provider leg is.

    Named by role rather than by order because the two topologies create them in
    opposite orders: parked origination makes the client leg first, server
    origination may make either first. Everything downstream reasons about
    "the destination leg", which is the billable one, in both.
    """

    CLIENT = "client"
    DESTINATION = "destination"


class LegState(str, Enum):
    """What we know about a leg, from provider semantics rather than our hopes.

    `UNKNOWN` is not a placeholder for "not started". It is the state of a leg we
    asked the provider to create and then lost the answer to, and it is the only
    state from which reconciliation — never a retry — is the correct next move.
    """

    CREATED = "created"
    #: Accepted by the provider and held for a backend decision.
    PARKED = "parked"
    RINGING = "ringing"
    ANSWERED = "answered"
    BRIDGED = "bridged"
    ENDED = "ended"
    UNKNOWN = "unknown"


TERMINAL_LEG_STATES = frozenset({LegState.ENDED})

#: Ordering for convergence. A late or reordered event may not move a leg
#: backwards: a `call.answered` delivered after `call.hangup` describes an
#: earlier moment, not a resurrection, and applying it would produce a negative
#: duration and an answered leg that already has a hangup cause (N10).
LEG_STATE_RANK: dict[LegState, int] = {
    LegState.CREATED: 0,
    LegState.PARKED: 1,
    LegState.RINGING: 2,
    LegState.ANSWERED: 3,
    LegState.BRIDGED: 4,
    LegState.ENDED: 5,
    # Unknown sits below everything: any real observation supersedes it, and it
    # never overwrites a state we actually saw.
    LegState.UNKNOWN: -1,
}


@dataclass(frozen=True)
class CallingCapabilities:
    """What one adapter can do, and what established each claim.

    `evidence_reference` exists because a mock passing itself is not evidence.
    An adapter claiming `EMERGENCY_CONTAINMENT` against a fixture is claiming
    nothing at all, and this is where a reviewer looks to find out which it is.
    """

    name: str
    supported: frozenset[CallingCapability]
    evidence_reference: str | None = None
    verified_at: datetime | None = None
    #: Capabilities the provider's documentation neither grants nor denies, with
    #: the reason. Kept apart from plain absence so a reviewer can distinguish
    #: "we checked and it is not there" from "nobody looked".
    undocumented: dict[str, str] = field(default_factory=dict)
    #: Maximum `time_limit` the provider accepts on a created leg, when it
    #: documents one. `None` means undocumented, which is not the same as
    #: unlimited and must not be treated as a bound.
    max_leg_seconds: int | None = None

    def supports(self, capability: CallingCapability) -> bool:
        return capability in self.supported

    def require(self, capability: CallingCapability) -> None:
        if capability not in self.supported:
            raise CapabilityNotAvailable(capability, self.undocumented.get(
                capability.value
            ))


class CallingError(Exception):
    """The provider refused, definitively, or we could not form the request."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


class CallOutcomeUnknown(Exception):
    """The command may or may not have taken effect.

    Deliberately not a subclass of `CallingError`. An `except CallingError` that
    swallowed this would turn a lost originate response into a refusal, a
    refusal looks retryable, and the retry is a second PSTN leg to a destination
    that is already ringing.
    """

    def __init__(self, reason: str, operation_reference: UUID | None = None) -> None:
        self.reason = reason
        self.operation_reference = operation_reference
        super().__init__(reason)


class CapabilityNotAvailable(CallingError):
    def __init__(
        self, capability: CallingCapability, reason: str | None = None
    ) -> None:
        self.capability = capability
        super().__init__(
            "capability_not_available",
            reason or f"this adapter does not advertise {capability.value}",
        )


class RouteDisabled(CallingError):
    """Live provider traffic is switched off, and this is the honest refusal.

    V01's go/no-go is NO-GO for a live route until blockers B1–B5 close. An
    adapter raising this is not broken; it is configured correctly for today.
    """

    def __init__(self, detail: str) -> None:
        super().__init__("calling_route_disabled", detail)


@dataclass(frozen=True)
class ProviderLegHandle:
    """Every identifier a provider gave us for one leg. All of them, kept.

    V01's contract is explicit that no single provider identifier may be the only
    correlation key: public documentation does not establish that independently
    created legs share a session id, so DamDam's own attempt-to-leg table is
    authoritative and these are supporting evidence (invariant 7).
    """

    control_id: str
    leg_id: str | None = None
    session_id: str | None = None
    connection_id: str | None = None
    credential_id: str | None = None


@dataclass(frozen=True)
class IssuedClientSession:
    """A short-lived client credential, as the provider actually returned it.

    `expires_at` is whatever the provider stated. Reuse item F4: the retired code
    computed an expiry by adding 24 hours to the local clock, which is a guess
    that silently outlives a credential the provider expired earlier.
    """

    token: str
    identity: str
    expires_at: datetime
    provider_credential_id: str
    provider_connection_id: str | None = None

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"IssuedClientSession(<redacted>, identity={self.identity!r}, "
            f"expires_at={self.expires_at!r})"
        )

    __str__ = __repr__


@dataclass(frozen=True)
class ProviderEvent:
    """One signed provider event, after authentication and before any decision.

    `event_id` is the deduplication key and is required: an event a provider
    cannot identify uniquely cannot be applied exactly once, and V01 review
    finding 3 is specifically that signature freshness is not replay protection.
    """

    event_id: str
    event_type: str
    occurred_at: datetime
    leg: ProviderLegHandle
    #: The destination the *client* asked for. A claim, never authority (N4).
    claimed_destination: str | None = None
    #: Decoded `client_state`. A correlation hint with no integrity of its own;
    #: it may name an attempt but may never authorize one (N7).
    client_state: dict[str, object] = field(default_factory=dict)
    hangup_cause: str | None = None
    raw: dict[str, object] = field(default_factory=dict)


class CallingAdapter(Protocol):
    """The whole surface a calling provider must present.

    Every command takes an `operation_reference` that the caller has **already
    persisted**. That is not a convenience: it is what makes an unknown outcome
    recoverable, because reconciliation asks the provider about exactly this
    operation rather than guessing which of several in-flight commands it means.
    """

    name: str

    def capabilities(self) -> CallingCapabilities: ...

    def issue_client_session(
        self,
        *,
        operation_reference: UUID,
        device_label: str,
        provider_credential_id: str | None = None,
        sip_identity: str | None = None,
        credential_expires_at: datetime | None = None,
    ) -> IssuedClientSession:
        """Create or refresh one device's credential and return a short session."""
        ...

    def revoke_client_credential(self, provider_credential_id: str) -> None:
        """Withdraw one device's credential without touching the user's others."""
        ...

    def create_destination_leg(
        self,
        *,
        operation_reference: UUID,
        destination: str,
        identity: str,
        time_limit_seconds: int,
        correlation: str,
    ) -> ProviderLegHandle:
        """Dial the destination. Raises `CallOutcomeUnknown` on a lost response."""
        ...

    def reconcile_operation(
        self, operation_reference: UUID
    ) -> ProviderLegHandle | None:
        """What did that exact command produce? `None` if the provider cannot say.

        `None` is a real answer and the most important one: it means stop and
        escalate, never retry.
        """
        ...

    def bridge(
        self, *, operation_reference: UUID, first: str, second: str
    ) -> None: ...

    def hangup(self, *, operation_reference: UUID, control_id: str) -> None: ...

    def parse_event(
        self, body: bytes, headers: dict[str, str]
    ) -> ProviderEvent:
        """Authenticate the payload, then read it. Raises on a bad signature.

        Authentication happens inside the adapter and before parsing because the
        order is the security property (reuse item R4): a parser that runs first
        is a parser exposed to unauthenticated input.
        """
        ...
