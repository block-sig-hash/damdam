"""The Telnyx calling adapter, and the disabled adapter that stands in for it.

Two classes and one rule: **nothing here may be enabled by a mock passing.**
V01's go/no-go is GO for provider-neutral preparation and NO-GO for a live
Telnyx route until blockers B1–B5 close, so `TelnyxCallingAdapter` refuses every
command that can create exposure unless `Settings.calling_live_routes_enabled`
is explicitly on *and* the account-level containment evidence has been recorded.
Provider configuration may still select it while that flag is off so signed
terminal events, hangups and credential revocations remain available. A
deployment with no provider configuration gets `DisabledCallingAdapter`, which
refuses honestly rather than half-working.

The capability set is where this chunk is most careful. Everything declared
below is documented Telnyx behaviour, checked on 9 September 2026 and recorded in
`docs/implementation/voice/CAPABILITY-MATRIX.md`. `EMERGENCY_CONTAINMENT` is
**not** declared, because no documentation can establish it — B1 needs an account
test — and a route that cannot prove containment does not carry traffic.

Two request-shape uncertainties are carried forward from V01 rather than papered
over:

- **Bridge field name.** Official generated examples use
  `call_control_id_to_bridge_with`; other official schema and tutorial text still
  shows `call_control_id` (reuse item F2). The adapter sends both and records
  that it is doing so, because guessing one and being wrong fails at the moment a
  customer is waiting on a ringing destination leg. The probe must settle it
  before live traffic.
- **Event identity.** Telnyx's `data.id` is used as the deduplication key. If an
  account test shows it is not unique per delivery, the inbox key is wrong and
  this is where that changes.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.auth.models import utc_now
from app.calling.contract import (
    CallingCapabilities,
    CallingCapability,
    CallingError,
    CallOutcomeUnknown,
    IssuedClientSession,
    ProviderEvent,
    ProviderLegHandle,
    RouteDisabled,
)
from app.config import Settings

#: Checked against current official Telnyx documentation on this date. Every
#: capability below is a reading of a published page, not an observed behaviour;
#: `AGENTS.md` requires the date to travel with the claim.
CAPABILITY_EVIDENCE_DATE = datetime(2026, 9, 9, tzinfo=timezone.utc)
CAPABILITY_EVIDENCE = "docs/implementation/voice/CAPABILITY-MATRIX.md (2026-09-09)"


class DisabledCallingAdapter:
    """The adapter a correctly configured deployment has today.

    It advertises nothing and refuses everything with `RouteDisabled`. That is
    not a stub standing in for missing work — it is the accurate representation
    of a product whose live route is externally blocked, and it means every code
    path above it is exercised against a refusal rather than against a fake
    success that would make the route look ready.
    """

    name = "disabled"

    def capabilities(self) -> CallingCapabilities:
        return CallingCapabilities(
            name=self.name,
            supported=frozenset(),
            evidence_reference="no provider configured",
            undocumented={
                capability.value: "no calling provider is enabled"
                for capability in CallingCapability
            },
        )

    def _refuse(self) -> RouteDisabled:
        return RouteDisabled(
            "no calling provider is enabled on this deployment; V01's live "
            "route remains blocked on B1–B5"
        )

    def issue_client_session(
        self,
        *,
        operation_reference: UUID,
        device_label: str,
        provider_credential_id: str | None = None,
        sip_identity: str | None = None,
        credential_expires_at: datetime | None = None,
    ) -> IssuedClientSession:
        raise self._refuse()

    def revoke_client_credential(self, provider_credential_id: str) -> None:
        raise self._refuse()

    def create_destination_leg(
        self,
        *,
        operation_reference: UUID,
        destination: str,
        identity: str,
        time_limit_seconds: int,
        correlation: str,
    ) -> ProviderLegHandle:
        raise self._refuse()

    def reconcile_operation(
        self, operation_reference: UUID
    ) -> ProviderLegHandle | None:
        raise self._refuse()

    def bridge(self, *, operation_reference: UUID, first: str, second: str) -> None:
        raise self._refuse()

    def hangup(self, *, operation_reference: UUID, control_id: str) -> None:
        raise self._refuse()

    def parse_event(self, body: bytes, headers: dict[str, str]) -> ProviderEvent:
        raise self._refuse()


class TelnyxCallingAdapter:
    """Telnyx call control, behind the provider-neutral contract.

    Every mutating method is gated on `_require_live`. Signature verification is
    **not**, because an event must be authenticable even on a disabled route: a
    deployment that turned the route off mid-call still has to recognise the
    hangup events for the calls it already started, and refusing to verify them
    would be the "disabling new calling also disabled termination" failure the
    assignment forbids.
    """

    name = "telnyx"

    def __init__(
        self, settings: Settings, *, clock: Callable[[], datetime] = utc_now,
        transport: Callable[..., httpx.Response] | None = None,
    ) -> None:
        self.settings = settings
        self.clock = clock
        if transport is not None and settings.app_env != "test":
            raise ValueError("Calling fixture transport is test-only")
        self._transport = transport

    # --- capabilities -------------------------------------------------------

    def capabilities(self) -> CallingCapabilities:
        return CallingCapabilities(
            name=self.name,
            supported=frozenset(
                {
                    CallingCapability.PARKED_ORIGINATION,
                    CallingCapability.SERVER_ORIGINATION,
                    CallingCapability.BRIDGE,
                    CallingCapability.HANGUP,
                    CallingCapability.LEG_TIME_LIMIT,
                    CallingCapability.PER_DEVICE_CREDENTIAL,
                }
            ),
            evidence_reference=CAPABILITY_EVIDENCE,
            verified_at=CAPABILITY_EVIDENCE_DATE,
            # Documented maximum for `time_limit_secs` on a Dial-created leg.
            max_leg_seconds=14400,
            undocumented={
                # The one that matters. B1 is open and only an account test can
                # close it; declaring it from documentation would be exactly the
                # substitution `AGENTS.md` forbids.
                CallingCapability.EMERGENCY_CONTAINMENT.value: (
                    "Telnyx documents that country-matched emergency calls "
                    "bypass Park Outbound Calls. Whether a credential "
                    "connection can be configured to block them is not "
                    "documented and requires an account test (blocker B1)"
                ),
            },
        )

    @property
    def live(self) -> bool:
        """Configured *and* deliberately enabled *and* evidenced.

        Three conditions, not one. Credentials alone must not turn a route on:
        the containment reference is a recorded account-test artifact, and
        without it the deployment has not proven the thing B1 asks for.
        """
        return bool(
            self.settings.calling_live_routes_enabled
            and self._transport is not None
            and self.settings.telnyx_api_key
            and self.settings.telnyx_connection_id
            and self.settings.calling_containment_evidence_reference
        )

    def _require_live(self) -> None:
        if not self.live:
            raise RouteDisabled(
                "live Telnyx calling is disabled: it requires "
                "calling_live_routes_enabled, provider credentials and a "
                "recorded containment-evidence reference (blocker B1)"
            )

    # --- client sessions ----------------------------------------------------

    def issue_client_session(
        self,
        *,
        operation_reference: UUID,
        device_label: str,
        provider_credential_id: str | None = None,
        sip_identity: str | None = None,
        credential_expires_at: datetime | None = None,
    ) -> IssuedClientSession:
        """One credential per device, and a short token from it.

        The account API key never leaves the server. The credential is created
        with a per-device name so that revoking one installation does not touch
        the customer's other devices (reuse item F4).
        """
        self._require_live()
        if provider_credential_id is None:
            credential = self._request(
                "POST",
                "/telephony_credentials",
                json={
                    "connection_id": self.settings.telnyx_connection_id,
                    "name": f"damdam-device-{operation_reference}",
                    "tag": "damdam-internet-calling",
                },
                operation_reference=operation_reference,
            )
            data = _object(credential, "credential")
            credential_id = _text(data, "id", "credential")
            identity = _text(data, "sip_username", "credential")
            expiry = _expiry(data, self.clock())
        else:
            if not sip_identity or credential_expires_at is None:
                raise CallingError("stored_credential_incomplete")
            credential_id = provider_credential_id
            identity = sip_identity
            expiry = credential_expires_at
        token = self._request(
            "POST",
            f"/telephony_credentials/{credential_id}/token",
            expect_text=True,
        )
        return IssuedClientSession(
            token=str(token),
            identity=identity,
            # Read from the provider's own response, never computed from the
            # local clock: F4 records that the retired code added 24 hours to
            # `now`, which silently outlives a credential expired earlier.
            expires_at=expiry,
            provider_credential_id=credential_id,
            provider_connection_id=self.settings.telnyx_connection_id or None,
        )

    def revoke_client_credential(self, provider_credential_id: str) -> None:
        # Not gated on `live`. Revocation is a containment action, and a
        # deployment that has just switched its route off is precisely when
        # outstanding credentials most need withdrawing.
        self._request("DELETE", f"/telephony_credentials/{provider_credential_id}")

    # --- call control -------------------------------------------------------

    def create_destination_leg(
        self,
        *,
        operation_reference: UUID,
        destination: str,
        identity: str,
        time_limit_seconds: int,
        correlation: str,
    ) -> ProviderLegHandle:
        """Dial the destination with a provider-enforced duration bound.

        `time_limit_secs` is the only control V01 evidenced as surviving this
        process dying mid-call, so it is set unconditionally and clamped to the
        provider's documented maximum rather than sent as whatever we hold.

        `command_id` carries our operation id. Telnyx deduplicates it for 60
        seconds, which is useful and is not the guarantee we rely on — that is
        `call_operations` plus `ux_call_legs_live_destination`.
        """
        self._require_live()
        bound = max(1, min(time_limit_seconds, 14400))
        payload = self._request(
            "POST",
            "/calls",
            json={
                "connection_id": self.settings.telnyx_connection_id,
                "from": identity,
                "to": destination,
                "time_limit_secs": bound,
                "command_id": str(operation_reference),
                "client_state": _client_state(
                    {
                        "attempt_id": correlation,
                        "operation_id": str(operation_reference),
                    }
                ),
            },
            operation_reference=operation_reference,
        )
        return _handle(_object(payload, "call"))

    def reconcile_operation(
        self, operation_reference: UUID
    ) -> ProviderLegHandle | None:
        """Ask what one command produced.

        Returns `None` honestly. Telnyx does not document a lookup by
        `command_id`, so there is no way to answer this from the public API, and
        an adapter that invented an answer would be worse than one that admits
        it cannot. `None` routes the operation to `held_for_review`, which is a
        human deciding rather than a worker dialling again — the correct outcome
        while B1/B2 are open.
        """
        return None

    def bridge(self, *, operation_reference: UUID, first: str, second: str) -> None:
        """Join two legs, sending both candidate field names.

        Reuse item F2: the current official material disagrees with itself about
        whether the peer field is `call_control_id` or
        `call_control_id_to_bridge_with`. Sending both is not sloppiness — it is
        the only shape that works whichever the account accepts, and the probe
        exists to replace it with the single correct field. This is recorded as a
        known deviation rather than hidden.
        """
        self._require_live()
        self._request(
            "POST",
            f"/calls/{first}/actions/bridge",
            json={
                "call_control_id": second,
                "call_control_id_to_bridge_with": second,
                "command_id": str(operation_reference),
            },
            operation_reference=operation_reference,
        )

    def hangup(self, *, operation_reference: UUID, control_id: str) -> None:
        # Not gated on `live`: ending a call must keep working after the route is
        # switched off, or disabling calling would strand connected calls.
        self._request(
            "POST",
            f"/calls/{control_id}/actions/hangup",
            json={"command_id": str(operation_reference)},
            operation_reference=operation_reference,
        )

    # --- events -------------------------------------------------------------

    def parse_event(self, body: bytes, headers: dict[str, str]) -> ProviderEvent:
        """Verify the signature over the **raw** body, then read it.

        Over the raw bytes, before any decoding: a signature checked against
        re-serialized JSON verifies what our parser produced rather than what was
        sent, and the two differ the moment key order or number formatting does.

        The timestamp tolerance bounds how old accepted traffic may be. It is not
        replay protection — the same valid event inside the window verifies
        again — and `call_events`' unique id is what makes it single-use.
        """
        self._verify(body, headers)
        try:
            envelope = json.loads(body)
            data = envelope["data"]
            payload = data["payload"]
            if not isinstance(data, dict) or not isinstance(payload, dict):
                raise TypeError
            event_id = str(data["id"])
            event_type = str(data["event_type"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise CallingError("invalid_webhook_payload") from exc

        occurred_raw = data.get("occurred_at") or payload.get("start_time")
        return ProviderEvent(
            event_id=event_id,
            event_type=event_type,
            occurred_at=_timestamp(occurred_raw, self.clock()),
            leg=ProviderLegHandle(
                control_id=str(payload.get("call_control_id") or ""),
                leg_id=_optional(payload.get("call_leg_id")),
                session_id=_optional(payload.get("call_session_id")),
                connection_id=_optional(payload.get("connection_id")),
                # Which device credential the provider says originated this leg.
                # Validated against the grant before any destination command.
                credential_id=_optional(
                    payload.get("telephony_credential_id")
                    or payload.get("credential_id")
                ),
            ),
            claimed_destination=_optional(payload.get("to")),
            client_state=_decode_client_state(payload.get("client_state")),
            hangup_cause=_optional(payload.get("hangup_cause")),
            raw=envelope if isinstance(envelope, dict) else {},
        )

    def _verify(self, body: bytes, headers: dict[str, str]) -> None:
        timestamp = headers.get("telnyx-timestamp", "")
        signature = headers.get("telnyx-signature-ed25519", "")
        if not self.settings.telnyx_public_key:
            # An unconfigured key must reject, never accept. A verifier that
            # passes when it has nothing to verify against is worse than no
            # verifier, because it looks like one.
            raise CallingError(
                "webhook_verification_unconfigured",
                "no Telnyx public key is configured, so no event can be trusted",
            )
        try:
            sent_at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
            if (
                abs((self.clock() - sent_at).total_seconds())
                > self.settings.telnyx_webhook_tolerance_seconds
            ):
                raise ValueError("timestamp outside tolerance")
            public_key = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(self.settings.telnyx_public_key, validate=True)
            )
            public_key.verify(
                base64.b64decode(signature, validate=True),
                timestamp.encode() + b"|" + body,
            )
        except (ValueError, TypeError, binascii.Error, InvalidSignature) as exc:
            raise CallingError("invalid_webhook_signature") from exc

    # --- transport ----------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        expect_text: bool = False,
        operation_reference: UUID | None = None,
    ) -> object:
        """One HTTP call, with a lost response reported as unknown.

        The `except` clauses are the contract. A timeout or a transport error
        means the request may have been processed — `CallOutcomeUnknown`. A 4xx
        means it definitely was not — `CallingError`. A 5xx is genuinely
        ambiguous and is treated as unknown, because a gateway that failed after
        accepting the call has still created the leg.
        """
        if not self.settings.telnyx_api_key:
            raise CallingError("telnyx_not_configured")
        try:
            response = (self._transport or httpx.request)(
                method,
                f"{self.settings.telnyx_base_url.rstrip('/')}{path}",
                headers={"Authorization": f"Bearer {self.settings.telnyx_api_key}"},
                json=json,
                timeout=self.settings.voice_request_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise CallOutcomeUnknown(
                f"timeout calling {path}", operation_reference
            ) from exc
        except httpx.HTTPError as exc:
            raise CallOutcomeUnknown(
                f"transport failure calling {path}", operation_reference
            ) from exc
        if response.status_code >= 500:
            raise CallOutcomeUnknown(
                f"provider returned {response.status_code} for {path}",
                operation_reference,
            )
        if response.status_code >= 400:
            raise CallingError(
                "provider_rejected",
                f"{response.status_code} from {path}",
            )
        if expect_text:
            return response.text.strip('"')
        try:
            return response.json()
        except ValueError as exc:
            raise CallingError("invalid_provider_response") from exc


# --- payload helpers --------------------------------------------------------


def _object(payload: object, what: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CallingError("invalid_provider_response", f"malformed {what} response")
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise CallingError("invalid_provider_response", f"malformed {what} response")
    return data


def _text(data: dict[str, Any], key: str, what: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise CallingError(
            "invalid_provider_response", f"{what} response has no {key}"
        )
    return value


def _optional(value: object) -> str | None:
    return str(value) if isinstance(value, str | int) and str(value) else None


def _handle(data: dict[str, Any]) -> ProviderLegHandle:
    return ProviderLegHandle(
        control_id=_text(data, "call_control_id", "call"),
        leg_id=_optional(data.get("call_leg_id")),
        session_id=_optional(data.get("call_session_id")),
        connection_id=_optional(data.get("connection_id")),
    )


def _client_state(value: dict[str, str]) -> str:
    return base64.b64encode(
        json.dumps(value, separators=(",", ":")).encode()
    ).decode()


def _decode_client_state(value: object) -> dict[str, object]:
    """Decode the echoed correlation hint, tolerating every kind of rubbish.

    Returns an empty mapping rather than raising for anything malformed. This
    value has no integrity of its own (V01 §4) and is only ever used to *look up*
    an attempt whose ownership is then re-validated, so a corrupt one is a missed
    hint and not an error (N7).
    """
    if not isinstance(value, str) or not value:
        return {}
    try:
        decoded = json.loads(base64.b64decode(value, validate=True))
    except (binascii.Error, ValueError, TypeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _timestamp(value: object, fallback: datetime) -> datetime:
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return fallback


def _expiry(data: dict[str, Any], fallback: datetime) -> datetime:
    """The credential's own expiry, as stated. Never inferred from `now`."""
    stated = data.get("expires_at")
    if isinstance(stated, str) and stated:
        return _timestamp(stated, fallback)
    raise CallingError(
        "credential_expiry_unknown",
        "the provider did not state a credential expiry; a locally computed "
        "one can outlive the credential it describes",
    )
