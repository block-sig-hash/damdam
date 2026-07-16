import base64
from decimal import Decimal
from html import escape
from typing import Any

import httpx

from app.config import Settings
from app.notifications.service import NotificationError


class ResendEmailSender:
    def send_sos(
        self,
        email: str,
        pilgrim_name: str,
        pilgrim_phone: str,
        timestamp: str,
        maps_url: str | None,
        cancelled: bool,
        notification_id: str,
    ) -> None:
        verb = "cancelled their SOS" if cancelled else "triggered an SOS and needs help"
        location = (
            f'<p><a href="{escape(maps_url, quote=True)}">View location</a></p>'
            if maps_url
            else "<p>Location unavailable.</p>"
        )
        self._send(
            email,
            "SOS cancelled" if cancelled else "URGENT: pilgrim SOS",
            (
                f"<p>{escape(pilgrim_name)} ({escape(pilgrim_phone)}) "
                f"{verb} at {escape(timestamp)}.</p>{location}"
            ),
            idempotency_key=f"damdam-sos-notification-{notification_id}-v1",
        )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _send(
        self,
        to: str,
        subject: str,
        html: str,
        attachments: list[dict[str, str]] | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        if not self.settings.resend_api_key:
            raise NotificationError("Resend is not configured")
        try:
            response = httpx.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {self.settings.resend_api_key}",
                    **({"Idempotency-Key": idempotency_key} if idempotency_key else {}),
                },
                json={
                    "from": self.settings.resend_from_email,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                    **({"attachments": attachments} if attachments else {}),
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

    def send_invoice(
        self,
        email: str,
        operator_name: str,
        order_id: str,
        total_ngn: Decimal,
        pdf: bytes,
    ) -> None:
        safe_name = escape(operator_name)
        safe_order = escape(order_id)
        self._send(
            email,
            f"DamDam invoice {safe_order}",
            (
                f"<p>Hello {safe_name},</p>"
                f"<p>Your HTO order invoice for NGN {total_ngn:,.2f} is attached. "
                f"Use {safe_order} as the bank-transfer reference.</p>"
            ),
            [
                {
                    "content": base64.b64encode(pdf).decode(),
                    "filename": f"damdam-invoice-{order_id}.pdf",
                }
            ],
            idempotency_key=f"damdam-manifest-order-{order_id}-invoice-v1",
        )

    def send_receipt(
        self, email: str, tier_name: str, amount_ngn: Decimal, reference: str
    ) -> None:
        safe_tier = escape(tier_name)
        safe_reference = escape(reference)
        self._send(
            email,
            "Your DamDam payment receipt",
            (
                f"<p>Payment received for your {safe_tier} package.</p>"
                f"<p>Amount: NGN {amount_ngn:,.2f}<br>"
                f"Reference: {safe_reference}</p>"
            ),
            idempotency_key=f"damdam-retail-receipt-{reference}",
        )


class MetaWhatsAppSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _send_template(
        self,
        phone_number: str,
        template_name: str,
        parameters: list[dict[str, str]] | None = None,
    ) -> str | None:
        if not self.settings.whatsapp_access_token:
            raise NotificationError("WhatsApp is not configured")
        template: dict[str, Any] = {
            "name": template_name,
            "language": {"code": "en"},
        }
        if parameters:
            template["components"] = [{"type": "body", "parameters": parameters}]
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": phone_number.removeprefix("+"),
            "type": "template",
            "template": template,
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
            response_json = getattr(response, "json", None)
            if callable(response_json):
                data = response_json()
                messages = data.get("messages", []) if isinstance(data, dict) else []
                if messages and messages[0].get("id"):
                    return str(messages[0]["id"])
            return None
        except httpx.HTTPError as exc:
            raise NotificationError("WhatsApp delivery failed") from exc

    def send_approval(self, phone_number: str, operator_name: str) -> None:
        self._send_template(
            phone_number,
            self.settings.whatsapp_approval_template,
            [{"type": "text", "text": operator_name}],
        )

    def send_esim_ready(self, phone_number: str, qr_code_url: str) -> None:
        self._send_template(
            phone_number,
            self.settings.whatsapp_esim_ready_template,
            [{"type": "text", "text": qr_code_url}],
        )

    def send_family_nomination(self, phone_number: str) -> None:
        self._send_template(
            phone_number,
            self.settings.whatsapp_family_nomination_template,
        )

    def send_activation(
        self, phone_number: str, pilgrim_name: str, tier_name: str, url: str
    ) -> None:
        self._send_template(
            phone_number,
            self.settings.whatsapp_activation_template,
            [
                {"type": "text", "text": pilgrim_name},
                {"type": "text", "text": tier_name},
                {"type": "text", "text": url},
            ],
        )

    def send_receipt(
        self, phone_number: str, tier_name: str, amount_ngn: Decimal, reference: str
    ) -> None:
        self._send_template(
            phone_number,
            self.settings.whatsapp_receipt_template,
            [
                {"type": "text", "text": tier_name},
                {"type": "text", "text": f"NGN {amount_ngn:,.2f}"},
                {"type": "text", "text": reference},
            ],
        )

    def send_checkin(
        self,
        phone_number: str,
        pilgrim_name: str,
        checked_in_at: str,
        maps_url: str | None,
    ) -> str:
        message_id = self._send_template(
            phone_number,
            self.settings.whatsapp_checkin_template,
            [
                {"type": "text", "text": pilgrim_name},
                {"type": "text", "text": checked_in_at},
                {"type": "text", "text": maps_url or ""},
            ],
        )
        if not message_id:
            raise NotificationError("WhatsApp response omitted message ID")
        return message_id

    def send_sos(
        self,
        phone_number: str,
        pilgrim_name: str,
        timestamp: str,
        maps_url: str | None,
        hto_phone: str,
        cancelled: bool,
    ) -> str:
        message_id = self._send_template(
            phone_number,
            self.settings.whatsapp_sos_cancelled_template
            if cancelled
            else self.settings.whatsapp_sos_template,
            [
                {"type": "text", "text": pilgrim_name},
                {"type": "text", "text": timestamp},
                {"type": "text", "text": maps_url or "Location unavailable"},
                {"type": "text", "text": hto_phone},
            ],
        )
        if not message_id:
            raise NotificationError("WhatsApp response omitted message ID")
        return message_id


class FirebasePushSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send_topic(
        self, topic: str, title: str, body: str, data: dict[str, str]
    ) -> None:
        if (
            not self.settings.firebase_project_id
            or not self.settings.firebase_access_token
        ):
            raise NotificationError("Firebase push is not configured")
        try:
            response = httpx.post(
                f"https://fcm.googleapis.com/v1/projects/{self.settings.firebase_project_id}/messages:send",
                headers={
                    "Authorization": f"Bearer {self.settings.firebase_access_token}"
                },
                json={
                    "message": {
                        "topic": topic,
                        "notification": {"title": title, "body": body},
                        "data": data,
                    }
                },
                timeout=self.settings.notification_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise NotificationError("Firebase push delivery failed") from exc

    def subscribe_topic(self, token: str, topic: str) -> None:
        """Associates a browser's FCM registration token with a topic via
        the Instance ID API, so a later send_topic(topic, ...) call reaches
        it. Subscription is a one-time, server-side operation — the browser
        cannot subscribe itself directly, it can only obtain the token."""
        if not self.settings.firebase_access_token:
            raise NotificationError("Firebase push is not configured")
        try:
            response = httpx.post(
                "https://iid.googleapis.com/iid/v1:batchAdd",
                headers={
                    "Authorization": f"Bearer {self.settings.firebase_access_token}",
                    "access_token_auth": "true",
                },
                json={"to": f"/topics/{topic}", "registration_tokens": [token]},
                timeout=self.settings.notification_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise NotificationError("Firebase topic subscription failed") from exc


class TermiiSmsSender:
    """Outbound family notification SMS, distinct from Termii's OTP endpoint."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.client = client or httpx.Client(
            base_url=settings.termii_base_url,
            timeout=settings.notification_timeout_seconds,
        )

    def send(self, phone_number: str, message: str) -> str:
        if not self.settings.termii_api_key:
            raise NotificationError("Termii SMS is not configured")
        try:
            response = self.client.post(
                "/api/sms/send",
                json={
                    "api_key": self.settings.termii_api_key,
                    "to": phone_number.removeprefix("+"),
                    "from": self.settings.termii_sender_id,
                    "sms": message,
                    "type": "plain",
                    "channel": "generic",
                },
            )
            response.raise_for_status()
            data = response.json()
            message_id = data.get("message_id") or data.get("message_id_str")
            if not message_id:
                raise NotificationError("Termii SMS response omitted message ID")
            return str(message_id)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise NotificationError("Termii SMS delivery failed") from exc
