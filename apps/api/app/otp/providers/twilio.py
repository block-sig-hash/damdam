import httpx

from app.config import Settings
from app.i18n import normalize_locale
from app.otp.providers.base import OTPDispatch, OTPProviderError


class TwilioVerifyProvider:
    name = "twilio"

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.client = client or httpx.Client(
            base_url="https://verify.twilio.com/v2",
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            timeout=settings.otp_request_timeout_seconds,
        )

    def _credentials_ready(self) -> None:
        if not all(
            (
                self.settings.twilio_account_sid,
                self.settings.twilio_auth_token,
                self.settings.twilio_verify_service_sid,
            )
        ):
            raise OTPProviderError("Twilio Verify is not configured")

    @property
    def _service_path(self) -> str:
        return f"/Services/{self.settings.twilio_verify_service_sid}"

    def send(self, phone_number: str, locale: str = "en") -> OTPDispatch:
        self._credentials_ready()
        try:
            response = self.client.post(
                f"{self._service_path}/Verifications",
                data={
                    "To": phone_number,
                    "Channel": "sms",
                    "Locale": normalize_locale(locale),
                },
            )
            response.raise_for_status()
            reference = response.json().get("sid")
            if not reference:
                raise OTPProviderError("Twilio response omitted SID")
            return OTPDispatch(str(reference), str(reference))
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise OTPProviderError("Twilio send failed") from exc

    def verify(self, phone_number: str, code: str, reference: str) -> bool:
        del reference
        self._credentials_ready()
        try:
            response = self.client.post(
                f"{self._service_path}/VerificationCheck",
                data={"To": phone_number, "Code": code},
            )
            if response.status_code == 404:
                return False
            if response.status_code >= 500:
                raise OTPProviderError("Twilio Verify unavailable")
            if response.status_code >= 400:
                return False
            return bool(response.json().get("status") == "approved")
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise OTPProviderError("Twilio verification failed") from exc
