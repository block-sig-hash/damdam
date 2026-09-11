"""Telnyx Wireless, behind the provider-neutral connectivity contract.

US-35, chunk 15. Every request this adapter makes and every field it reads comes
from `app/connectivity/telnyx_contract.py`, which is a transcription of Telnyx's
published documentation and OpenAPI source, re-verified **10 September 2026**.

**No call has been made.** D1 is open: there is no Telnyx account, no test
credentials, no rate deck and no commercial confirmation. The transport is
injected, and `build_transport` refuses to construct a live one without an API
key and an explicit enable flag. What this adapter proves today is that our
request construction and response parsing match the documented contract — which
is not the same as proving Telnyx behaves as documented, and `AGENTS.md` is
explicit that a passing mock is not evidence of the latter.

Four behaviours are worth reading closely, because each of them is a decision
that could have gone the cheap way:

**The purchase has no idempotency key, so it is never retried.** Telnyx
documents none — no header, no body field. A lost response is therefore
`ConnectivityOutcomeUnknown`, and the only safe next step is the tag lookup in
`reconcile`. This adapter has no code path that retries a purchase.

**A 202 is not a completed state change.** Telnyx: *"All state changes return
202 with a SIM Card Action — they are not instant."* So `set_state` and
`enable_voice` return a `ProviderAction` whose `succeeded` is `None` until
`fetch_action` says otherwise.

**`esim_installation_status: released` is not an installation.** It means the
profile was released for download. Nobody at Telnyx can see a handset. The
adapter reports it as `installation_released` and never as installed.

**Voice is beta and its request/response schemas are still absent.** The
endpoints are named in the documentation and in the action-type enum; the
detailed contract is "coming soon". So `NATIVE_VOICE` is advertised only when
the caller explicitly says it has been verified for this account, and the reason
it is otherwise withheld is recorded in `undocumented`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.auth.models import utc_now
from app.connectivity.contract import (
    ActivationCredential,
    AdapterCapabilities,
    AdapterChannel,
    Capability,
    ConnectivityError,
    ConnectivityOutcomeUnknown,
    ProviderAction,
    ProviderLine,
    ProviderLineState,
    ProvisionResult,
)
from app.connectivity.telnyx_contract import (
    ACTIVATION_CODE_PATH,
    API_BASE_URL,
    DISABLE_PATH,
    ENABLE_PATH,
    ENABLE_VOICE_PATH,
    LIST_SIM_CARDS_PATH,
    SET_STANDBY_PATH,
    SIM_CARD_ACTION_PATH,
    SIM_CARD_PATH,
    TRANSITIONAL_STATUSES,
    ActivationCode,
    ContractViolation,
    ESimPurchaseRequest,
    ESimPurchaseResponse,
    SimCard,
    SimCardAction,
    SimCardActionStatus,
    SimCardStatus,
    operation_tag,
)


@dataclass(frozen=True)
class TelnyxResponse:
    status_code: int
    payload: dict[str, Any]


class TelnyxTransportTimeout(Exception):
    """The request may have been received. Never collapse this into an error."""


#: `(method, path, json_body, params) -> TelnyxResponse`. Injected rather than
#: imported so the conformance suite can produce a lost response, a partial
#: purchase and an undocumented status on demand — none of which a sandbox
#: produces when you ask it to.
TelnyxTransport = Callable[
    [str, str, dict[str, Any] | None, dict[str, Any] | None], TelnyxResponse
]


#: How Telnyx's SIM statuses map onto the one question this adapter is allowed
#: to answer: what does the *supplier* say. Turning these into our activation
#: and network states happens in `app/connectivity/service.py`, once, so a new
#: supplier status changes one table rather than every caller.
_STATE_BY_STATUS: dict[SimCardStatus, ProviderLineState] = {
    SimCardStatus.ENABLED: ProviderLineState.ACTIVE,
    SimCardStatus.DISABLED: ProviderLineState.SUSPENDED,
    SimCardStatus.STANDBY: ProviderLineState.SUSPENDED,
    SimCardStatus.REGISTERING: ProviderLineState.TRANSITIONING,
    SimCardStatus.ENABLING: ProviderLineState.TRANSITIONING,
    SimCardStatus.DISABLING: ProviderLineState.TRANSITIONING,
    SimCardStatus.SETTING_STANDBY: ProviderLineState.TRANSITIONING,
    # System-imposed. Not "suspended": we did not do it, and treating a data
    # cap as our own suspension would let a resume request look like it should
    # work when only raising the limit will.
    SimCardStatus.DATA_LIMIT_EXCEEDED: ProviderLineState.RESTRICTED,
    SimCardStatus.UNAUTHORIZED_IMEI: ProviderLineState.RESTRICTED,
    SimCardStatus.BLOCKED: ProviderLineState.RESTRICTED,
    SimCardStatus.ABOLISHED: ProviderLineState.TERMINATED,
}

#: The documented reasons a capability is withheld. Recorded rather than
#: implied, so a reviewer can tell "checked, absent" from "nobody looked".
UNDOCUMENTED_REASONS = {
    Capability.NATIVE_VOICE.value: (
        "VoLTE is labelled beta and the API reference is 'coming soon'; the "
        "enable_voice request/response schemas are not published. Verified "
        "2026-09-10."
    ),
    Capability.NUMBER_ASSIGNMENT.value: (
        "mobile_phone_numbers is documented as a resource but its schemas are "
        "part of the beta VoLTE contract that is not yet published. Verified "
        "2026-09-10."
    ),
    Capability.SPENDING_ENFORCEMENT.value: (
        "data_limit is documented per SIM and per group, but its enforcement "
        "latency is not, and no voice spending cap is documented anywhere. A "
        "cap with an unquantified overshoot window is not a hard cap. Verified "
        "2026-09-10."
    ),
    Capability.USAGE_EVENTS.value: (
        "Wireless Detail Records exist, but the OpenAPI source documents only "
        "the report envelope -- no per-record schema and no unique record id, "
        "so records cannot be deduplicated from documented fields alone. "
        "Verified 2026-09-10."
    ),
    Capability.TOPUP.value: (
        "No documented endpoint adds allowance to an existing eSIM. Raising a "
        "data_limit changes a cap, which is not the same as selling more "
        "allowance. Verified 2026-09-10."
    ),
}


class TelnyxConnectivityAdapter:
    """Telnyx Wireless as a connectivity supplier.

    `verified_capabilities` is a constructor argument rather than a constant
    because which capabilities are real depends on the *account*, and there is
    no account. Passing a capability in means somebody has evidence for it and
    named the evidence; the default is the honest one, which is data only.
    """

    name = "telnyx"

    def __init__(
        self,
        transport: TelnyxTransport,
        *,
        base_url: str = API_BASE_URL,
        sim_card_group_id: UUID | None = None,
        whitelabel_name: str | None = None,
        initial_status: SimCardStatus = SimCardStatus.STANDBY,
        verified_capabilities: frozenset[Capability] | None = None,
        evidence_reference: str | None = None,
        verified_at: datetime | None = None,
        usage_latency_seconds: int | None = None,
        lookup_is_trusted: bool = False,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.transport = transport
        self.base_url = base_url.rstrip("/")
        self.sim_card_group_id = sim_card_group_id
        self.whitelabel_name = whitelabel_name
        # Standby, not enabled: a profile nobody has installed should not be
        # billing $2/month as an active SIM, and Telnyx charges $0.20 for a
        # standby one. `enable` happens when the customer installs it.
        self.initial_status = initial_status
        self._verified = frozenset(
            verified_capabilities
            if verified_capabilities is not None
            # Data and the activation credential are documented outright, and
            # the cumulative counter is a documented field on the SIM. Nothing
            # else is claimed by default.
            else {
                Capability.DATA,
                Capability.ACTIVATION_CREDENTIAL,
                Capability.USAGE_COUNTER,
                Capability.SUSPENSION,
            }
        )
        self.evidence_reference = evidence_reference
        self.verified_at = verified_at
        self.usage_latency_seconds = usage_latency_seconds
        #: Whether a just-created eSIM is immediately visible to `filter[tags]`
        #: is undocumented (API-CONTRACTS.md §2.3 q2). Until somebody proves it
        #: against a live account, an empty lookup is an unknown, not a "no".
        self.lookup_is_trusted = lookup_is_trusted
        self.clock = clock

    # --- capabilities -----------------------------------------------------

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supported=self._verified,
            usage_latency_seconds=self.usage_latency_seconds,
            evidence_reference=self.evidence_reference,
            verified_at=self.verified_at,
            undocumented={
                capability: reason
                for capability, reason in UNDOCUMENTED_REASONS.items()
                if Capability(capability) not in self._verified
            },
            # Telnyx Wireless is a *carrier* adapter. Its WebRTC product is a
            # different integration behind a different adapter (V02), and the
            # calling amendment is explicit that evidence for one never closes
            # the other's gate.
            channel=AdapterChannel.CARRIER,
        )

    # --- provisioning -----------------------------------------------------

    def provision(
        self,
        operation_reference: UUID,
        quantity: int,
        options: dict[str, Any] | None = None,
    ) -> ProvisionResult:
        """Buy `quantity` eSIMs, tagged with the operation reference.

        The tag is the only client-supplied field Telnyx will later let us
        filter on, so it is the only reconciliation handle that exists. It is a
        uuid rather than anything human-meaningful precisely because tags carry
        no documented uniqueness guarantee — two operations must not be able to
        collide by someone choosing a tidy name.
        """
        options = options or {}
        request = ESimPurchaseRequest(
            amount=quantity,
            operation_reference=operation_reference,
            sim_card_group_id=options.get("sim_card_group_id", self.sim_card_group_id),
            product="whitelabel" if self.whitelabel_name else None,
            whitelabel_name=self.whitelabel_name,
            status=options.get("status", self.initial_status),
        )
        try:
            response = self._call(
                "POST", "/actions/purchase/esims", body=request.to_body()
            )
        except TelnyxTransportTimeout as exc:
            # The single most expensive branch in the product. The purchase may
            # have been accepted and charged. It is not retried here, ever.
            raise ConnectivityOutcomeUnknown(
                f"eSIM purchase for operation {operation_reference} did not "
                f"return: {exc}. Reconcile against the operation tag; do not "
                "purchase again."
            ) from exc

        if response.status_code >= 500:
            # A 5xx after the request reached Telnyx is indistinguishable from
            # a lost response. Treating it as a failure would make it look
            # retryable.
            raise ConnectivityOutcomeUnknown(
                f"eSIM purchase returned {response.status_code}; the request "
                "may have been accepted"
            )
        if response.status_code >= 400:
            errors = _error_codes(response.payload)
            raise ConnectivityError(
                "purchase_rejected",
                f"Telnyx refused the purchase ({response.status_code}): "
                f"{', '.join(errors) or 'no error code returned'}",
            )

        parsed = ESimPurchaseResponse.from_payload(response.payload)
        return ProvisionResult(
            lines=tuple(self._line(card) for card in parsed.sim_cards),
            errors=tuple(error.code for error in parsed.errors),
            rejection_reason=(
                None
                if parsed.sim_cards
                else "; ".join(
                    filter(None, (error.title or error.code for error in parsed.errors))
                )
                or "Telnyx returned no eSIMs and no error"
            ),
        )

    def reconcile(
        self, operation_reference: UUID, quantity: int
    ) -> ProvisionResult | None:
        """What did that purchase actually create?

        Deliberately does **not** filter by status. The documented
        `filter[status]` enum omits the transitional states, so a SIM mid-
        registration would be invisible to a status-filtered lookup — and
        invisible reads as "never landed", which reads as "safe to retry".

        Returns `None` when the lookup itself cannot be trusted to answer. The
        caller escalates; it does not guess.
        """
        try:
            response = self._call(
                "GET",
                LIST_SIM_CARDS_PATH,
                params={
                    "filter[tags][]": operation_tag(operation_reference),
                    "page[size]": 250,
                },
            )
        except TelnyxTransportTimeout:
            # We could not ask. That is not evidence of anything.
            return None
        if response.status_code >= 400:
            return None

        data = response.payload.get("data")
        if not isinstance(data, list):
            raise ContractViolation("sim card listing 'data' must be an array")
        cards = tuple(SimCard.from_payload(item) for item in data)

        from app.connectivity.reconciliation import reconcile_purchase

        decision = reconcile_purchase(
            requested_amount=quantity,
            operation_reference=operation_reference,
            sim_cards=cards,
            lookup_is_trusted=self.lookup_is_trusted,
        )
        if decision.requires_manual_review:
            # An ambiguous lookup is not an answer. Saying so is what stops the
            # caller resolving the attempt one way or the other.
            return None
        return ProvisionResult(
            lines=tuple(self._line(card) for card in decision.matched),
            rejection_reason=(
                None if decision.matched else "the purchase never reached Telnyx"
            ),
        )

    # --- line state -------------------------------------------------------

    def fetch_line(self, provider_reference: str) -> ProviderLine | None:
        response = self._call(
            "GET", SIM_CARD_PATH.format(id=provider_reference)
        )
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise ConnectivityError(
                "line_lookup_failed",
                f"Telnyx returned {response.status_code} for a SIM lookup",
            )
        payload = response.payload.get("data")
        if not isinstance(payload, dict):
            raise ContractViolation("SIM card response has no 'data' object")
        return self._line(SimCard.from_payload(payload))

    def fetch_activation_credential(
        self, provider_reference: str
    ) -> ActivationCredential:
        """`GET /sim_cards/{id}/activation_code`.

        Verified present in the OpenAPI source on 2026-09-10; chunk 03's record
        had missed it, which is why that record now carries a recheck section.

        The value is one-time use — Telnyx documents that a lost profile cannot
        be re-downloaded — so it is never logged and never returned in an error
        message. The exception below deliberately names the SIM, not the code.
        """
        self.capabilities().require(Capability.ACTIVATION_CREDENTIAL)
        response = self._call(
            "GET", ACTIVATION_CODE_PATH.format(id=provider_reference)
        )
        if response.status_code >= 400:
            raise ConnectivityError(
                "activation_code_unavailable",
                f"Telnyx returned {response.status_code} for the activation "
                f"code of SIM {provider_reference}",
            )
        payload = response.payload.get("data")
        if not isinstance(payload, dict):
            raise ContractViolation("activation code response has no 'data' object")
        code = ActivationCode.from_payload(payload)
        return ActivationCredential(secret=code.value, one_time_use=True)

    def enable_voice(self, provider_reference: str) -> ProviderAction:
        """`POST /sim_cards/{id}/actions/enable_voice`, asynchronous.

        Refused unless somebody has verified native voice for this account. The
        endpoint is named in the documentation and in the action-type enum, but
        its request and response schemas are part of the beta contract that is
        still unpublished — so calling it on the strength of the name alone
        would be exactly the "do not implement against assumed field shapes"
        case chunk 03 warned about.
        """
        self.capabilities().require(Capability.NATIVE_VOICE)
        return self._action(
            "POST", ENABLE_VOICE_PATH.format(id=provider_reference)
        )

    def assigned_number(self, provider_reference: str) -> str | None:
        """The number Telnyx assigned, read from the SIM's own `msisdn`.

        `GET /mobile_phone_numbers` would be the richer source, but its schema
        belongs to the unpublished beta contract. `msisdn` is a documented
        field on the SIM card resource with a documented meaning, so this reads
        the fact we can actually cite.
        """
        self.capabilities().require(Capability.NUMBER_ASSIGNMENT)
        line = self.fetch_line(provider_reference)
        return None if line is None else line.msisdn

    def set_state(
        self, provider_reference: str, target: ProviderLineState
    ) -> ProviderAction:
        """Request a lifecycle transition. Returns an unsettled action.

        `SUSPENDED` maps to standby rather than disable: the two differ only in
        whether the IP is preserved, and standby is the one a line can come
        back from cleanly. Termination is **not** offered — `DELETE
        /sim_cards/{id}` is documented as irreversible and an eSIM deleted that
        way cannot be re-registered, so it is not something this adapter will
        do on a worker's say-so.
        """
        self.capabilities().require(Capability.SUSPENSION)
        if target is ProviderLineState.ACTIVE:
            path = ENABLE_PATH
        elif target is ProviderLineState.SUSPENDED:
            path = SET_STANDBY_PATH
        elif target is ProviderLineState.TERMINATED:
            raise ConnectivityError(
                "irreversible_operation_refused",
                "deleting a Telnyx eSIM is documented as irreversible and the "
                "profile cannot be re-registered; termination is an explicit "
                "operator decision, not an adapter call",
            )
        else:
            raise ConnectivityError(
                "unsupported_target_state",
                f"{target.value} is not a state Telnyx can be asked for",
            )
        return self._action("POST", path.format(id=provider_reference))

    def disable(self, provider_reference: str) -> ProviderAction:
        """`disable` rather than `standby`, for when the IP need not survive."""
        self.capabilities().require(Capability.SUSPENSION)
        return self._action("POST", DISABLE_PATH.format(id=provider_reference))

    def fetch_action(self, provider_action_reference: str) -> ProviderAction | None:
        response = self._call(
            "GET", SIM_CARD_ACTION_PATH.format(id=provider_action_reference)
        )
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise ConnectivityError(
                "action_lookup_failed",
                f"Telnyx returned {response.status_code} for a SIM card action",
            )
        payload = response.payload.get("data")
        if not isinstance(payload, dict):
            raise ContractViolation("action response has no 'data' object")
        return _provider_action(SimCardAction.from_payload(payload))

    # --- internals --------------------------------------------------------

    def _action(self, method: str, path: str) -> ProviderAction:
        try:
            response = self._call(method, path)
        except TelnyxTransportTimeout as exc:
            # A lifecycle request whose response was lost may still be in
            # flight. Re-sending it races the first one, and Telnyx refuses a
            # transition while another is in progress, so the honest answer is
            # "ask the actions list", not "try again".
            raise ConnectivityOutcomeUnknown(
                f"lifecycle request to {path} did not return: {exc}. Look the "
                "action up before requesting it again."
            ) from exc
        if response.status_code >= 500:
            raise ConnectivityOutcomeUnknown(
                f"lifecycle request to {path} returned {response.status_code}"
            )
        if response.status_code >= 400:
            raise ConnectivityError(
                "lifecycle_request_rejected",
                f"Telnyx refused {path} ({response.status_code}): "
                f"{', '.join(_error_codes(response.payload)) or 'no error code'}",
            )
        payload = response.payload.get("data")
        if not isinstance(payload, dict):
            raise ContractViolation("lifecycle response has no 'data' object")
        return _provider_action(SimCardAction.from_payload(payload))

    def _call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> TelnyxResponse:
        response = self.transport(method, f"{self.base_url}{path}", body, params)
        if not isinstance(response, TelnyxResponse):  # pragma: no cover
            raise ConnectivityError(
                "transport_contract_violation",
                "the transport must return a TelnyxResponse",
            )
        return response

    def _line(self, card: SimCard) -> ProviderLine:
        return ProviderLine(
            provider_reference=card.id,
            state=_STATE_BY_STATUS[card.status],
            provider_status=card.status.value,
            iccid=card.iccid,
            msisdn=card.msisdn,
            voice_enabled=card.voice_enabled,
            # Released for download. Not installed. Nobody at Telnyx can see a
            # handset, and this field is the one somebody will eventually try
            # to read as proof that a customer's phone has the profile.
            installation_released=(
                None
                if card.esim_installation_status is None
                else card.esim_installation_status == "released"
            ),
            actions_in_progress=(
                card.actions_in_progress
                if card.actions_in_progress is not None
                else card.status in TRANSITIONAL_STATUSES
            ),
            consumed_bytes=(
                None if card.consumed_data is None else card.consumed_data.bytes
            ),
            data_limit_bytes=(
                None if card.data_limit is None else card.data_limit.bytes
            ),
            observed_at=self.clock(),
        )


def _provider_action(action: SimCardAction) -> ProviderAction:
    return ProviderAction(
        provider_reference=action.id,
        # `None` while in flight. Not `False`: "we do not know yet" and "it
        # failed" lead to different next steps.
        succeeded=None if not action.is_settled else action.succeeded,
        settled=action.is_settled,
        provider_status=action.status.value,
        reason=action.reason,
    )


def _error_codes(payload: dict[str, Any]) -> list[str]:
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return []
    return [
        str(error.get("code"))
        for error in errors
        if isinstance(error, dict) and error.get("code") is not None
    ]


def build_transport(
    api_key: str,
    *,
    live_enabled: bool,
    timeout_seconds: int = 30,
) -> TelnyxTransport:
    """A real HTTP transport, hard-gated.

    D1 is open, so this has never been run against Telnyx and no claim is made
    that it works. The gate exists so that turning it on is a deliberate act
    with a credential behind it, rather than something that starts happening
    because an environment variable was set somewhere.
    """
    if not live_enabled:
        raise ConnectivityError(
            "telnyx_live_disabled",
            "TELNYX_LIVE_ENABLED is false; D1 has not selected Telnyx and no "
            "account exists. Inject a transport explicitly for tests.",
        )
    if not api_key:
        raise ConnectivityError(
            "telnyx_api_key_missing", "no Telnyx API key is configured"
        )

    import httpx

    def transport(
        method: str,
        url: str,
        body: dict[str, Any] | None,
        params: dict[str, Any] | None,
    ) -> TelnyxResponse:
        try:
            response = httpx.request(
                method,
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                json=body,
                params=params,
                timeout=timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise TelnyxTransportTimeout(str(exc)) from exc
        except httpx.HTTPError as exc:
            # A transport error is not a refusal. We do not know whether the
            # request arrived, and the caller must not learn otherwise.
            raise TelnyxTransportTimeout(str(exc)) from exc
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return TelnyxResponse(
            status_code=response.status_code,
            payload=payload if isinstance(payload, dict) else {},
        )

    return transport


__all__ = [
    "SimCardActionStatus",
    "TelnyxConnectivityAdapter",
    "TelnyxResponse",
    "TelnyxTransport",
    "TelnyxTransportTimeout",
    "build_transport",
]
