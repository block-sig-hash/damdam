"""The shared connectivity-adapter conformance suite (US-35, chunk 15).

**D1 is open.** No carrier has been contracted, there is no Telnyx account and
no call has been made. The chunk's instruction for exactly this case is to build
the adapter boundary and its contract tests and leave the live half explicitly
open — which is what this is.

The suite is a set of behaviours every connectivity adapter must exhibit,
expressed against `ConnectivityAdapter` and nothing else. Running it against a
new supplier is how that supplier is qualified. Running it against Telnyx today
is how we know the contract is satisfiable by a real integration rather than
only by a fake built to fit it.

What it deliberately does **not** do:

- It does not reach the network. Each case drives the adapter's injected
  transport, because the behaviours worth checking — a lost response mid-
  purchase, a partial delivery, a status nobody has seen before, a 202 that has
  not settled — are precisely the ones a sandbox will not produce on demand.
- It is therefore **not evidence of external compatibility.** `AGENTS.md`: a
  mock passing itself proves nothing about a vendor. What it proves is that the
  adapter obeys *our* contract; whether Telnyx obeys *its own documentation*
  needs an account, and D1 has not produced one.

Every case names the incident it prevents, because a conformance case whose
reason is unrecorded gets weakened by whoever next finds it inconvenient.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from app.connectivity.contract import (
    CARRIER_ONLY_CAPABILITIES,
    INTERNET_ONLY_CAPABILITIES,
    AdapterChannel,
    Capability,
    CapabilityNotAvailable,
    ConnectivityAdapter,
    ConnectivityError,
    ConnectivityOutcomeUnknown,
    ProviderLineState,
)


@dataclass
class ConformanceCase:
    """One required behaviour, and the incident it prevents."""

    name: str
    why: str
    run: Callable[[AdapterHarness], None]


@dataclass
class AdapterHarness:
    """Everything a case needs to drive one adapter deterministically.

    An adapter that cannot be driven this way cannot be qualified, and that is
    a deliberate barrier: a carrier integration nobody can test against a lost
    response is one whose lost responses are discovered in production, on the
    single most expensive failure path in the product.
    """

    adapter: ConnectivityAdapter
    #: Queue one response for the next transport call.
    respond: Callable[[int, dict[str, Any]], None]
    #: Make the next transport call time out — a response that never arrives.
    time_out: Callable[[], None]
    #: A supplier-shaped line payload, so cases stay vendor-neutral.
    line_payload: Callable[..., dict[str, Any]]
    #: The requests the adapter actually made, for the never-retried case.
    calls: list[tuple[str, str, dict[str, Any] | None]] = field(
        default_factory=list
    )


class ConformanceFailure(AssertionError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConformanceFailure(message)


# --- the cases ---------------------------------------------------------------


def _lost_response_is_unknown_not_failure(harness: AdapterHarness) -> None:
    """A purchase whose response never arrived is an unknown.

    The failure this prevents is the one `AGENTS.md` calls the most expensive in
    the product: a lost response classified as a failure looks retryable, the
    retry buys a second eSIM the supplier already sold us, and the customer is
    charged for two lines and installs one.
    """
    harness.time_out()
    try:
        harness.adapter.provision(uuid4(), 1, {})
    except ConnectivityOutcomeUnknown:
        return
    except ConnectivityError as exc:
        raise ConformanceFailure(
            f"a lost response was reported as a definite error ({exc.code}); "
            "a definite error is retryable and the retry double-purchases"
        ) from exc
    raise ConformanceFailure("a lost response was reported as a success")


def _lost_response_does_not_retry(harness: AdapterHarness) -> None:
    """The adapter must not retry the purchase itself.

    The failure: an adapter-level retry loop, which is invisible from above and
    defeats every guard the order state machine has, because the second purchase
    happens inside the call that the caller believes is one purchase.
    """
    before = len(harness.calls)
    harness.time_out()
    with contextlib.suppress(ConnectivityOutcomeUnknown):
        harness.adapter.provision(uuid4(), 1, {})
    attempts = len(harness.calls) - before
    _require(
        attempts == 1,
        f"the adapter made {attempts} purchase requests for one call; a "
        "purchase with no idempotency key must be sent exactly once",
    )


def _server_error_is_unknown(harness: AdapterHarness) -> None:
    """A 5xx after the request reached the supplier is also an unknown.

    The failure: treating 500 as a refusal. The request arrived; the supplier
    may well have acted on it before failing to tell us.
    """
    harness.respond(500, {"errors": [{"code": "10009", "title": "server error"}]})
    try:
        harness.adapter.provision(uuid4(), 1, {})
    except ConnectivityOutcomeUnknown:
        return
    except ConnectivityError as exc:
        raise ConformanceFailure(
            "a 5xx was reported as a definite refusal"
        ) from exc
    raise ConformanceFailure("a 5xx was reported as a success")


def _partial_delivery_is_visible(harness: AdapterHarness) -> None:
    """Fewer lines than requested is reported, not rounded up to success.

    The failure: reading only `data[0]` from a quantity-based purchase. An
    order for three lines that produced one would be marked fulfilled, and two
    recipients would wait forever for a line nobody is going to buy.
    """
    harness.respond(
        202,
        {
            "data": [harness.line_payload(id="sim-partial-1")],
            "errors": [{"code": "70001", "title": "not enough SIM cards"}],
        },
    )
    result = harness.adapter.provision(uuid4(), 3, {})
    _require(
        len(result.lines) == 1,
        f"expected one delivered line, got {len(result.lines)}",
    )
    _require(
        "70001" in result.errors,
        "the supplier's error code was dropped, so nothing above can tell a "
        "shortfall from a full delivery",
    )


def _undocumented_status_is_refused(harness: AdapterHarness) -> None:
    """A status nobody has transcribed stops the adapter.

    The failure: `active = status != "disabled"`, which turns every status a
    carrier invents into a working line. Refusing loudly means the contract
    record gets updated; guessing means a customer is told their line works.
    """
    harness.respond(202, {"data": [harness.line_payload(status="quantum")]})
    try:
        harness.adapter.provision(uuid4(), 1, {})
    except (ValueError, ConnectivityError):
        return
    raise ConformanceFailure(
        "an undocumented supplier status was accepted; the adapter is guessing"
    )


def _released_is_not_installed(harness: AdapterHarness) -> None:
    """A supplier saying a profile is released must not read as installed.

    The failure this prevents is a support screen telling somebody their eSIM is
    on their phone because a QR code was generated. No carrier can observe a
    handset; only the device can say.
    """
    harness.respond(
        202,
        {"data": [harness.line_payload(esim_installation_status="released")]},
    )
    result = harness.adapter.provision(uuid4(), 1, {})
    _require(bool(result.lines), "no line was returned for a successful purchase")
    line = result.lines[0]
    _require(
        line.installation_released is True,
        "the supplier's release state was lost",
    )
    _require(
        line.state is not ProviderLineState.ACTIVE
        or line.provider_status == "enabled",
        "a released profile was reported as an active line without the "
        "supplier saying the line was enabled",
    )


def _transitional_state_is_not_a_destination(harness: AdapterHarness) -> None:
    """A line mid-transition is reported as transitioning, not as arrived.

    The failure: mapping `enabling` to active. The next poll would have told the
    truth; acting on the transitional status tells the customer their line is
    live while it is still coming up.
    """
    harness.respond(202, {"data": [harness.line_payload(status="enabling")]})
    result = harness.adapter.provision(uuid4(), 1, {})
    _require(bool(result.lines), "no line was returned for a successful purchase")
    _require(
        result.lines[0].state is ProviderLineState.TRANSITIONING,
        f"a transitional status mapped to {result.lines[0].state.value}",
    )


def _state_change_is_not_instant(harness: AdapterHarness) -> None:
    """A 202 on a lifecycle action is unsettled, not confirmed.

    The failure: marking a line suspended on the 202. Telnyx documents every
    state change as asynchronous, so the line is still passing traffic and still
    billable while the app says it is off.
    """
    harness.respond(
        202,
        {
            "data": {
                "id": "action-1",
                "sim_card_id": "sim-1",
                "action_type": "set_standby",
                "status": {"value": "in-progress"},
            }
        },
    )
    action = harness.adapter.set_state("sim-1", ProviderLineState.SUSPENDED)
    _require(not action.settled, "an in-progress action was reported as settled")
    _require(
        action.succeeded is None,
        "an unsettled action claimed an outcome; 'not yet' is not 'no'",
    )


def _failed_action_is_not_a_success(harness: AdapterHarness) -> None:
    """A settled-but-failed action reports failure, distinctly from pending."""
    harness.respond(
        200,
        {
            "data": {
                "id": "action-2",
                "sim_card_id": "sim-1",
                "action_type": "enable",
                "status": {"value": "failed", "reason": "the data limit was exceeded"},
            }
        },
    )
    action = harness.adapter.fetch_action("action-2")
    _require(action is not None, "a known action was not returned")
    assert action is not None
    _require(action.settled, "a failed action was reported as still running")
    _require(action.succeeded is False, "a failed action was reported as succeeded")
    _require(
        bool(action.reason),
        "the supplier's failure reason was dropped, leaving nobody able to act",
    )


def _unverified_capability_is_refused(harness: AdapterHarness) -> None:
    """Asking for something the adapter does not advertise raises.

    The failure `market.py` exists to prevent, reached from the other side: a
    data-only supplier being asked for native voice must refuse, not return an
    empty success that reads as "no number yet".
    """
    capabilities = harness.adapter.capabilities()
    if capabilities.supports(Capability.NATIVE_VOICE):
        return  # verified for this account; nothing to refuse
    try:
        harness.adapter.enable_voice("sim-1")
    except CapabilityNotAvailable:
        return
    raise ConformanceFailure(
        "an unverified capability was exercised instead of refused"
    )


def _capability_absence_is_explained(harness: AdapterHarness) -> None:
    """Every withheld capability says why it is withheld.

    The failure: an adapter that simply lacks a capability, leaving a reviewer
    unable to tell "we checked the documentation and it is not there" from
    "nobody has looked yet". Those need different follow-up.
    """
    capabilities = harness.adapter.capabilities()
    # The other channel's capabilities need no explanation: they are structurally
    # unavailable, not an evidence gap somebody could close.
    out_of_channel = (
        INTERNET_ONLY_CAPABILITIES
        if capabilities.channel is AdapterChannel.CARRIER
        else CARRIER_ONLY_CAPABILITIES
    )
    withheld = {
        capability
        for capability in Capability
        if not capabilities.supports(capability) and capability not in out_of_channel
    }
    unexplained = {
        capability.value
        for capability in withheld
        if capability.value not in capabilities.undocumented
    }
    _require(
        not unexplained,
        f"capabilities withheld with no recorded reason: {sorted(unexplained)}",
    )


def _channels_do_not_overlap(harness: AdapterHarness) -> None:
    """A carrier adapter advertises no internet capability, and vice versa.

    The failure the calling amendment names outright: *"Evidence for WebRTC
    never closes carrier gates."* An adapter able to claim both lets a browser
    calling test stand in for proof that a handset can dial from its own dialer
    on a visited network, and those are not the same claim at all.
    """
    capabilities = harness.adapter.capabilities()
    forbidden = (
        INTERNET_ONLY_CAPABILITIES
        if capabilities.channel is AdapterChannel.CARRIER
        else CARRIER_ONLY_CAPABILITIES
    )
    overlap = capabilities.supported & forbidden
    _require(
        not overlap,
        f"a {capabilities.channel.value} adapter advertises "
        f"{sorted(capability.value for capability in overlap)}",
    )


def _reconciliation_admits_ignorance(harness: AdapterHarness) -> None:
    """A reconciliation that cannot answer returns `None`.

    The failure: an empty lookup read as "the purchase never landed". If the
    supplier's post-purchase lookup is not immediately consistent — and Telnyx
    does not document that it is — an empty result is the most dangerous
    possible answer, because it reads as safe to retry.
    """
    harness.respond(200, {"data": []})
    answer = harness.adapter.reconcile(uuid4(), 1)
    _require(
        answer is None,
        "an empty lookup was reported as a definite 'never landed'; with "
        "undocumented lookup consistency that authorises a double purchase",
    )


def _reconciliation_matches_the_operation(harness: AdapterHarness) -> None:
    """Only lines carrying this operation's own tag count.

    The failure: adopting whatever the lookup returned. Tags carry no
    documented uniqueness guarantee, so a filter that returns somebody else's
    line must not be read as this order's line.
    """
    operation = uuid4()
    harness.respond(
        200,
        {
            "data": [
                harness.line_payload(id="sim-someone-else", tags=["unrelated-tag"])
            ]
        },
    )
    answer = harness.adapter.reconcile(operation, 1)
    _require(
        answer is None or not answer.lines,
        "a line that does not carry this operation's tag was adopted as ours",
    )


def _activation_material_is_never_in_an_error(harness: AdapterHarness) -> None:
    """A failed credential fetch names the line, never the code.

    The failure: an exception message carrying an activation code into a log
    aggregator. A Telnyx eSIM code is one-time use, so a leaked one cannot be
    rotated — it is a paid-for profile somebody else can install.
    """
    harness.respond(404, {"errors": [{"code": "10005", "title": "not found"}]})
    try:
        harness.adapter.fetch_activation_credential("sim-1")
    except ConnectivityError as exc:
        _require(
            "LPA" not in str(exc) and "activation_code" not in str(exc),
            "an activation code reached an error message",
        )
        return
    raise ConformanceFailure("a 404 on the activation code was not reported")


def _activation_material_is_redacted(harness: AdapterHarness) -> None:
    """The credential type does not print its own secret."""
    harness.respond(200, {"data": {"activation_code": "LPA:1$smdp.example$MATCHING"}})
    credential = harness.adapter.fetch_activation_credential("sim-1")
    _require(
        "LPA" not in repr(credential) and "LPA" not in str(credential),
        "the activation credential printed its secret; every log line and "
        "traceback carrying one is a profile somebody else can install",
    )
    _require(
        credential.secret == "LPA:1$smdp.example$MATCHING",
        "the activation code did not round-trip",
    )


def _irreversible_operations_are_refused(harness: AdapterHarness) -> None:
    """Deleting a line is not something an adapter call does.

    The failure: a worker retry deleting an eSIM. Telnyx documents deletion as
    irreversible and the profile as unrecoverable, so it needs a person, not a
    queue.
    """
    try:
        harness.adapter.set_state("sim-1", ProviderLineState.TERMINATED)
    except ConnectivityError:
        return
    raise ConformanceFailure(
        "an irreversible operation was available to an ordinary caller"
    )


CASES: tuple[ConformanceCase, ...] = (
    ConformanceCase(
        "lost response is unknown",
        "a lost response read as a failure looks retryable, and the retry buys "
        "a second eSIM the supplier already sold us",
        _lost_response_is_unknown_not_failure,
    ),
    ConformanceCase(
        "lost response is not retried inside the adapter",
        "an adapter-level retry defeats every guard the order state machine has",
        _lost_response_does_not_retry,
    ),
    ConformanceCase(
        "server error is unknown",
        "the request arrived; the supplier may have acted on it",
        _server_error_is_unknown,
    ),
    ConformanceCase(
        "partial delivery is visible",
        "an order for three lines that produced one must not read as fulfilled",
        _partial_delivery_is_visible,
    ),
    ConformanceCase(
        "undocumented status is refused",
        "otherwise every status a carrier invents becomes a working line",
        _undocumented_status_is_refused,
    ),
    ConformanceCase(
        "released is not installed",
        "no carrier can observe a handset; only the device can say",
        _released_is_not_installed,
    ),
    ConformanceCase(
        "transitional state is not a destination",
        "'enabling' is not 'enabled', and the customer is told it is",
        _transitional_state_is_not_a_destination,
    ),
    ConformanceCase(
        "a state change is not instant",
        "a 202 read as done reports a line suspended while it still bills",
        _state_change_is_not_instant,
    ),
    ConformanceCase(
        "a failed action is not a success",
        "and 'not yet' is not 'no'",
        _failed_action_is_not_a_success,
    ),
    ConformanceCase(
        "unverified capability is refused",
        "a data-only supplier cannot satisfy a native-voice plan",
        _unverified_capability_is_refused,
    ),
    ConformanceCase(
        "withheld capabilities are explained",
        "'checked and absent' and 'nobody looked' need different follow-up",
        _capability_absence_is_explained,
    ),
    ConformanceCase(
        "carrier and internet capabilities do not overlap",
        "evidence for WebRTC never closes a carrier gate",
        _channels_do_not_overlap,
    ),
    ConformanceCase(
        "reconciliation admits ignorance",
        "an empty lookup read as 'never landed' authorises a double purchase",
        _reconciliation_admits_ignorance,
    ),
    ConformanceCase(
        "reconciliation matches the operation",
        "tags have no documented uniqueness guarantee",
        _reconciliation_matches_the_operation,
    ),
    ConformanceCase(
        "activation material never reaches an error",
        "a one-time-use profile that leaks cannot be rotated",
        _activation_material_is_never_in_an_error,
    ),
    ConformanceCase(
        "activation material is redacted in repr",
        "every traceback carrying one is a profile somebody else can install",
        _activation_material_is_redacted,
    ),
    ConformanceCase(
        "irreversible operations are refused",
        "deleting an eSIM needs a person, not a worker retry",
        _irreversible_operations_are_refused,
    ),
)


def run_all(harness_factory: Callable[[], AdapterHarness]) -> list[str]:
    """Run every case against a fresh harness, returning the failures.

    A fresh harness per case on purpose: a case that leaves a queued response
    behind would make the next one pass or fail for a reason that has nothing
    to do with what it is testing.
    """
    failures: list[str] = []
    for case in CASES:
        harness = harness_factory()
        try:
            case.run(harness)
        except ConformanceFailure as exc:
            failures.append(f"{case.name}: {exc} (prevents: {case.why})")
        except Exception as exc:  # noqa: BLE001 - see below
            # An adapter that raises where the contract expects a value has
            # failed the case, not crashed the suite. Letting it propagate
            # would stop the run at the first broken adapter and hide every
            # other thing wrong with it -- which is the opposite of what a
            # qualification suite is for.
            failures.append(
                f"{case.name}: raised {type(exc).__name__}: {exc} "
                f"(prevents: {case.why})"
            )
    return failures


def _unused(value: UUID) -> None:  # pragma: no cover - typing anchor
    del value
