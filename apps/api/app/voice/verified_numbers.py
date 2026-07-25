from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import Settings


class PhoneVerificationProviderError(Exception):
    pass


@dataclass(frozen=True)
class PhoneVerificationAttempt:
    reference: str


class PhoneVerificationProvider(Protocol):
    """Phone-possession proof, decoupled from account login OTP (AC-14.1)."""

    def start_verification(self, phone_number: str) -> PhoneVerificationAttempt: ...

    def confirm_verification(self, reference: str, code: str) -> bool: ...


class TelnyxVerifiedNumbersProvider:
    """The only Telnyx-specific code in the phone-verification flow."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def start_verification(self, phone_number: str) -> PhoneVerificationAttempt:
        payload = self._request(
            "POST",
            "/verified_numbers",
            json={"phone_number": phone_number, "verification_method": "sms"},
        )
        try:
            if not isinstance(payload, dict):
                raise TypeError
            data = payload["data"]
            if not isinstance(data, dict):
                raise TypeError
            return PhoneVerificationAttempt(reference=str(data["id"]))
        except (KeyError, TypeError) as exc:
            raise PhoneVerificationProviderError(
                "invalid verification response"
            ) from exc

    def confirm_verification(self, reference: str, code: str) -> bool:
        payload = self._request(
            "POST",
            f"/verified_numbers/{reference}/actions/verify",
            json={"verification_code": code},
        )
        try:
            if not isinstance(payload, dict):
                raise TypeError
            data = payload["data"]
            if not isinstance(data, dict):
                raise TypeError
            return str(data.get("status")) == "verified"
        except (KeyError, TypeError) as exc:
            raise PhoneVerificationProviderError(
                "invalid verification response"
            ) from exc

    def _request(
        self, method: str, path: str, *, json: dict[str, object] | None = None
    ) -> object:
        if not self.settings.telnyx_api_key:
            raise PhoneVerificationProviderError("Telnyx is not configured")
        try:
            response = httpx.request(
                method,
                f"{self.settings.telnyx_base_url.rstrip('/')}{path}",
                headers={"Authorization": f"Bearer {self.settings.telnyx_api_key}"},
                json=json,
                timeout=self.settings.voice_request_timeout_seconds,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PhoneVerificationProviderError("Telnyx request failed") from exc


class IdentityVerificationProviderError(Exception):
    pass


@dataclass(frozen=True)
class IdentityVerificationResult:
    status: str
    nin_msisdn_match_status: str


class IdentityVerificationProvider(Protocol):
    def verify_identity(
        self, nin: str, phone_number: str
    ) -> IdentityVerificationResult: ...


class MockIdentityProvider:
    """LABELED MOCK -- never wire a real identity provider behind this class
    without the founder/legal sign-off in docs/verified-cli-scoping.md §4.
    NIN identity verification has no legal basis resolved yet; this mock
    always reports `rejected`/`unavailable` so a misconfiguration can never
    silently grant identity-verified status. Only reachable at all when
    Settings.nin_verification_enabled is True, which defaults to False.
    """

    def verify_identity(
        self, nin: str, phone_number: str
    ) -> IdentityVerificationResult:
        del nin, phone_number
        return IdentityVerificationResult(
            status="rejected", nin_msisdn_match_status="unavailable"
        )
