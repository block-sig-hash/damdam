import base64
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

import httpx

from app.config import Settings


class VoiceProviderError(Exception):
    pass


@dataclass(frozen=True)
class ProvisionedVoiceCredential:
    credential_id: str
    sip_username: str


@dataclass(frozen=True)
class VoiceAccessToken:
    token: str
    expires_at: datetime


class VoiceProvider(Protocol):
    def create_credential(self, user_id: str) -> ProvisionedVoiceCredential: ...

    def issue_token(self, credential_id: str) -> VoiceAccessToken: ...

    def initiate_call(
        self,
        *,
        webrtc_call_control_id: str,
        user_id: str,
        caller_id: str,
        to_number: str,
        time_limit_seconds: int,
        verified_caller_identity_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> None: ...

    def bridge_call(self, call_control_id: str, peer_call_control_id: str) -> None: ...


class TelnyxVoiceProvider:
    """The only Telnyx-specific code in the voice feature."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create_credential(self, user_id: str) -> ProvisionedVoiceCredential:
        payload = self._request(
            "POST",
            "/telephony_credentials",
            json={
                "connection_id": self.settings.telnyx_connection_id,
                "name": f"damdam-{user_id}",
                "tag": "damdam-pilgrim",
            },
        )
        try:
            if not isinstance(payload, dict):
                raise TypeError
            data = payload["data"]
            if not isinstance(data, dict):
                raise TypeError
            return ProvisionedVoiceCredential(
                credential_id=str(data["id"]),
                sip_username=str(data["sip_username"]),
            )
        except (KeyError, TypeError) as exc:
            raise VoiceProviderError("invalid credential response") from exc

    def issue_token(self, credential_id: str) -> VoiceAccessToken:
        token = self._request(
            "POST", f"/telephony_credentials/{credential_id}/token", expect_text=True
        )
        # Telnyx's current token endpoint fixes JWT lifetime at 24 hours (or the
        # parent credential expiry, whichever comes first). The app requests a
        # fresh token for each call and never stores the account API key.
        return VoiceAccessToken(
            token=str(token),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )

    def initiate_call(
        self,
        *,
        webrtc_call_control_id: str,
        user_id: str,
        caller_id: str,
        to_number: str,
        time_limit_seconds: int,
        verified_caller_identity_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        state = base64.b64encode(
            json.dumps(
                {
                    "user_id": user_id,
                    "webrtc_call_control_id": webrtc_call_control_id,
                    "verified_caller_identity_id": verified_caller_identity_id,
                    "idempotency_key": idempotency_key,
                },
                separators=(",", ":"),
            ).encode()
        ).decode()
        self._request(
            "POST",
            "/calls",
            json={
                "connection_id": self.settings.telnyx_connection_id,
                "from": caller_id,
                "to": to_number,
                "client_state": state,
                "time_limit_secs": max(1, time_limit_seconds),
            },
        )

    def bridge_call(self, call_control_id: str, peer_call_control_id: str) -> None:
        self._request(
            "POST",
            f"/calls/{call_control_id}/actions/bridge",
            json={"call_control_id": peer_call_control_id},
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        expect_text: bool = False,
    ) -> object:
        if not self.settings.telnyx_api_key:
            raise VoiceProviderError("Telnyx is not configured")
        try:
            response = httpx.request(
                method,
                f"{self.settings.telnyx_base_url.rstrip('/')}{path}",
                headers={"Authorization": f"Bearer {self.settings.telnyx_api_key}"},
                json=json,
                timeout=self.settings.voice_request_timeout_seconds,
            )
            response.raise_for_status()
            return response.text.strip('"') if expect_text else response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise VoiceProviderError("Telnyx request failed") from exc


class IDTExpressVoiceProvider:
    """Unreachable stub for the Phase 2+ IDT Express BYOC migration
    (prd.md §5.5) -- a termination-cost layer under Telnyx, not a
    reliability change. `Settings.idt_calling_enabled` is validated False
    at startup (config.py's `idt_calling_is_not_yet_supported`), so this
    class is never constructed in production; it exists only to give
    `CallLog.requested_provider`'s `idt` value and the real future adapter
    a documented landing spot, per verified-cli-scoping.md §5's
    "config-shaped stub" recommendation."""

    def __init__(self, settings: Settings) -> None:
        del settings
        raise VoiceProviderError("idt_calling_not_supported")
