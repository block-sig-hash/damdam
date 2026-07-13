from html import escape
from typing import Any

import httpx

from app.config import Settings
from app.notifications.service import NotificationError


class ResendEmailSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _send(self, to: str, subject: str, html: str) -> None:
        if not self.settings.resend_api_key:
            raise NotificationError("Resend is not configured")
        try:
            response = httpx.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {self.settings.resend_api_key}"},
                json={
                    "from": self.settings.resend_from_email,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
                timeout=self.settings.notification_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise NotificationError("Email delivery failed") from exc

    def send_verification(
        self, email: str, operator_name: str, verification_url: str
    ) -> None:
        safe_name = escape(operator_name)
        safe_url = escape(verification_url, quote=True)
        self._send(
            email,
            "Verify your DamDam operator account",
            (
                f"<p>Hello {safe_name},</p>"
                f'<p><a href="{safe_url}">Verify your email address</a>. '
                "This link expires in 24 hours.</p>"
            ),
        )

    def send_approval(self, email: str, operator_name: str) -> None:
        safe_name = escape(operator_name)
        self._send(
            email,
            "Your DamDam operator account is approved",
            f"<p>Hello {safe_name}, your DamDam operator account is approved.</p>",
        )


class MetaWhatsAppSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send_approval(self, phone_number: str, operator_name: str) -> None:
        if not self.settings.whatsapp_access_token:
            raise NotificationError("WhatsApp is not configured")
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": phone_number.removeprefix("+"),
            "type": "template",
            "template": {
                "name": self.settings.whatsapp_approval_template,
                "language": {"code": "en"},
                "components": [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": operator_name}],
                    }
                ],
            },
        }
        url = (
            f"https://graph.facebook.com/{self.settings.whatsapp_api_version}/"
            f"{self.settings.whatsapp_phone_number_id}/messages"
        )
        try:
            response = httpx.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.settings.whatsapp_access_token}"
                },
                json=payload,
                timeout=self.settings.notification_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise NotificationError("WhatsApp delivery failed") from exc
