from typing import Any

import httpx

from app.config import Settings
from app.i18n import normalize_locale
from app.otp.providers.base import OTPDispatch, OTPProviderError


class TermiiProvider:
    name = "termii"

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.client = client or httpx.Client(
            base_url=settings.termii_base_url,
            timeout=settings.otp_request_timeout_seconds,
        )

    def _credentials_ready(self) -> None:
        if not self.settings.termii_api_key:
            raise OTPProviderError("Termii is not configured")

    def send(self, phone_number: str, locale: str = "en") -> OTPDispatch:
        self._credentials_ready()
        payload: dict[str, Any] = {
            "api_key": self.settings.termii_api_key,
            "pin_type": "NUMERIC",
            "message_type": "NUMERIC",
            "to": phone_number.removeprefix("+"),
            "from": self.settings.termii_sender_id,
            "channel": "generic",
            "pin_attempts": self.settings.otp_attempt_limit,
            "pin_time_to_live": self.settings.otp_ttl_seconds // 60,
            "pin_length": 6,
            "pin_placeholder": "< 123456 >",
            "message_text": (
                "Votre code de vérification DamDam est < 123456 >"
                if normalize_locale(locale) == "fr"
                else "Your DamDam verification code is < 123456 >"
            ),
        }
        try:
            response = self.client.post("/api/sms/otp/send", json=payload)
            response.raise_for_status()
            data = response.json()
            reference = data.get("pin_id") or data.get("pinId")
            delivery_reference = data.get("message_id_str")
            if not reference or not delivery_reference:
                raise OTPProviderError("Termii response omitted references")
            return OTPDispatch(str(reference), str(delivery_reference))
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise OTPProviderError("Termii send failed") from exc

    def verify(self, phone_number: str, code: str, reference: str) -> bool:
        del phone_number
        self._credentials_ready()
        try:
            response = self.client.post(
                "/api/sms/otp/verify",
                json={
                    "api_key": self.settings.termii_api_key,
                    "pin_id": reference,
                    "pin": code,
                },
            )
            if response.status_code >= 500:
                raise OTPProviderError("Termii verify unavailable")
            if response.status_code >= 400:
                return False
            return str(response.json().get("verified", "")).lower() == "true"
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise OTPProviderError("Termii verify failed") from exc
