import base64
from decimal import Decimal
from typing import Any

import httpx

from app.config import Settings
from app.i18n.notifications import NotificationRenderer
from app.notifications.service import NotificationError


class ResendEmailSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.renderer = NotificationRenderer()

    def send_sos(
        self,
        email: str,
        pilgrim_name: str,
        pilgrim_phone: str,
        timestamp: str,
        maps_url: str | None,
        cancelled: bool,
        notification_id: str,
        locale: str = "en",
    ) -> None:
        content = self.renderer.email_sos(
            pilgrim_name,
            pilgrim_phone,
            timestamp,
            maps_url,
            cancelled,
            locale,
        )
        self._send(
            email,
            content.subject,
            content.html,
            idempotency_key=f"damdam-sos-notification-{notification_id}-v1",
        )

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
        self,
        email: str,
        operator_name: str,
        verification_url: str,
        locale: str = "en",
    ) -> None:
        content = self.renderer.email_verification(
            operator_name, verification_url, locale
        )
        self._send(email, content.subject, content.html)

    def send_approval(self, email: str, operator_name: str, locale: str = "en") -> None:
        content = self.renderer.email_approval(operator_name, locale)
        self._send(email, content.subject, content.html)

    def send_invoice(
        self,
        email: str,
        operator_name: str,
        order_id: str,
        total_ngn: Decimal,
        pdf: bytes,
        locale: str = "en",
    ) -> None:
        content = self.renderer.email_invoice(
            operator_name, order_id, total_ngn, locale
        )
        self._send(
            email,
            content.subject,
            content.html,
            [
                {
                    "content": base64.b64encode(pdf).decode(),
                    "filename": f"damdam-invoice-{order_id}.pdf",
                }
            ],
            idempotency_key=f"damdam-manifest-order-{order_id}-invoice-v1",
        )

    def send_receipt(
        self,
        email: str,
        tier_name: str,
        amount_ngn: Decimal,
        reference: str,
        locale: str = "en",
    ) -> None:
        content = self.renderer.email_receipt(tier_name, amount_ngn, reference, locale)
        self._send(
            email,
            content.subject,
            content.html,
            idempotency_key=f"damdam-retail-receipt-{reference}",
        )


class MetaWhatsAppSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.renderer = NotificationRenderer()

    def _send_template(
        self,
        phone_number: str,
        template_name: str,
        language: str = "en",
        parameters: list[dict[str, str]] | None = None,
    ) -> str | None:
        if not self.settings.whatsapp_access_token:
            raise NotificationError("WhatsApp is not configured")
        template: dict[str, Any] = {
            "name": template_name,
            "language": {"code": language},
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

    def send_approval(
        self, phone_number: str, operator_name: str, locale: str = "en"
    ) -> None:
        template = self.renderer.whatsapp_template(
            self.settings.whatsapp_approval_template,
            self.settings.whatsapp_approval_template_fr,
            locale,
        )
        self._send_template(
            phone_number,
            template.name,
            template.language,
            [{"type": "text", "text": operator_name}],
        )

    def send_esim_ready(
        self, phone_number: str, qr_code_url: str, locale: str = "en"
    ) -> None:
        template = self.renderer.whatsapp_template(
            self.settings.whatsapp_esim_ready_template,
            self.settings.whatsapp_esim_ready_template_fr,
            locale,
        )
        self._send_template(
            phone_number,
            template.name,
            template.language,
            [{"type": "text", "text": qr_code_url}],
        )

    def send_family_nomination(self, phone_number: str, locale: str = "en") -> None:
        template = self.renderer.whatsapp_template(
            self.settings.whatsapp_family_nomination_template,
            self.settings.whatsapp_family_nomination_template_fr,
            locale,
        )
        self._send_template(
            phone_number,
            template.name,
            template.language,
        )

    def send_activation(
        self,
        phone_number: str,
        pilgrim_name: str,
        tier_name: str,
        url: str,
        locale: str = "en",
    ) -> None:
        template = self.renderer.whatsapp_template(
            self.settings.whatsapp_activation_template,
            self.settings.whatsapp_activation_template_fr,
            locale,
        )
        self._send_template(
            phone_number,
            template.name,
            template.language,
            [
                {"type": "text", "text": pilgrim_name},
                {
                    "type": "text",
                    "text": self.renderer.tier_name(tier_name, locale),
                },
                {"type": "text", "text": url},
            ],
        )

    def send_receipt(
        self,
        phone_number: str,
        tier_name: str,
        amount_ngn: Decimal,
        reference: str,
        locale: str = "en",
    ) -> None:
        template = self.renderer.whatsapp_template(
            self.settings.whatsapp_receipt_template,
            self.settings.whatsapp_receipt_template_fr,
            locale,
        )
        self._send_template(
            phone_number,
            template.name,
            template.language,
            [
                {
                    "type": "text",
                    "text": self.renderer.tier_name(tier_name, locale),
                },
                {"type": "text", "text": self.renderer.amount_ngn(amount_ngn, locale)},
                {"type": "text", "text": reference},
            ],
        )

    def send_checkin(
        self,
        phone_number: str,
        pilgrim_name: str,
        checked_in_at: str,
        maps_url: str | None,
        locale: str = "en",
    ) -> str:
        template = self.renderer.whatsapp_template(
            self.settings.whatsapp_checkin_template,
            self.settings.whatsapp_checkin_template_fr,
            locale,
        )
        message_id = self._send_template(
            phone_number,
            template.name,
            template.language,
            [
                {"type": "text", "text": pilgrim_name},
                {
                    "type": "text",
                    "text": self.renderer.timestamp(checked_in_at, locale),
                },
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
        locale: str = "en",
    ) -> str:
        base_name = (
            self.settings.whatsapp_sos_cancelled_template
            if cancelled
            else self.settings.whatsapp_sos_template
        )
        french_name = (
            self.settings.whatsapp_sos_cancelled_template_fr
            if cancelled
            else self.settings.whatsapp_sos_template_fr
        )
        template = self.renderer.whatsapp_template(base_name, french_name, locale)
        message_id = self._send_template(
            phone_number,
            template.name,
            template.language,
            [
                {"type": "text", "text": pilgrim_name},
                {"type": "text", "text": self.renderer.timestamp(timestamp, locale)},
                {
                    "type": "text",
                    "text": maps_url or self.renderer.location_unavailable(locale),
                },
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
