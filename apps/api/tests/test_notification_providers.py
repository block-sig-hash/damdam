from decimal import Decimal
from typing import Any

from app.config import Settings
from app.notifications.providers import (
    MetaWhatsAppSender,
    ResendEmailSender,
    TermiiSmsSender,
)


class FakeResponse:
    def raise_for_status(self) -> None:
        return None


class FakeJsonResponse(FakeResponse):
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def json(self) -> dict[str, Any]:
        return self.payload


def test_resend_invoice_uses_stable_idempotency_key_and_pdf_attachment(
    monkeypatch,
) -> None:
    """AC-06.4: an invoice retry cannot create a second Resend email."""
    requests: list[dict[str, Any]] = []

    def fake_post(*args, **kwargs):
        requests.append({"args": args, "kwargs": kwargs})
        return FakeResponse()

    monkeypatch.setattr("app.notifications.providers.httpx.post", fake_post)
    settings = Settings(
        jwt_secret="test-secret-at-least-32-characters-long",
        resend_api_key="resend-token",
    )

    ResendEmailSender(settings).send_invoice(
        "operator@example.com",
        "Amina",
        "order-123",
        Decimal("128000.00"),
        b"%PDF-test",
    )

    request = requests[0]["kwargs"]
    assert request["headers"]["Idempotency-Key"] == (
        "damdam-manifest-order-order-123-invoice-v1"
    )
    assert request["json"]["attachments"] == [
        {
            "content": "JVBERi10ZXN0",
            "filename": "damdam-invoice-order-123.pdf",
        }
    ]


def test_resend_sos_uses_notification_id_as_idempotency_key(monkeypatch) -> None:
    """A retry is stable without collisions between pilgrims sharing a name/time."""
    requests: list[dict[str, Any]] = []

    def fake_post(*args, **kwargs):
        requests.append({"args": args, "kwargs": kwargs})
        return FakeResponse()

    monkeypatch.setattr("app.notifications.providers.httpx.post", fake_post)
    settings = Settings(
        jwt_secret="test-secret-at-least-32-characters-long",
        resend_api_key="resend-token",
    )

    ResendEmailSender(settings).send_sos(
        "operator@example.com",
        "Amina Yusuf",
        "+2348012345678",
        "16 Jul 2026, 09:05 WAT",
        None,
        False,
        "notification-123",
    )

    assert requests[0]["kwargs"]["headers"]["Idempotency-Key"] == (
        "damdam-sos-notification-notification-123-v1"
    )


def test_meta_family_nomination_uses_configured_template(monkeypatch) -> None:
    """AC-03.2: the provider sends the approved nomination template via Meta."""
    requests: list[dict[str, Any]] = []

    def fake_post(*args, **kwargs):
        requests.append({"args": args, "kwargs": kwargs})
        return FakeResponse()

    monkeypatch.setattr("app.notifications.providers.httpx.post", fake_post)
    settings = Settings(
        jwt_secret="test-secret-at-least-32-characters-long",
        whatsapp_access_token="meta-token",
        whatsapp_phone_number_id="phone-id",
        whatsapp_family_nomination_template="family_contact_nominated_v1",
    )

    MetaWhatsAppSender(settings).send_family_nomination("+2349012345678")

    assert requests[0]["kwargs"]["json"] == {
        "messaging_product": "whatsapp",
        "to": "2349012345678",
        "type": "template",
        "template": {
            "name": "family_contact_nominated_v1",
            "language": {"code": "en"},
        },
    }


def test_meta_approval_template_keeps_operator_name_parameter(monkeypatch) -> None:
    """US-04 regression: shared template dispatch retains approval parameters."""
    requests: list[dict[str, Any]] = []

    def fake_post(*args, **kwargs):
        requests.append({"args": args, "kwargs": kwargs})
        return FakeResponse()

    monkeypatch.setattr("app.notifications.providers.httpx.post", fake_post)
    settings = Settings(
        jwt_secret="test-secret-at-least-32-characters-long",
        whatsapp_access_token="meta-token",
        whatsapp_phone_number_id="phone-id",
    )

    MetaWhatsAppSender(settings).send_approval("+2348012345678", "Amina")

    assert requests[0]["kwargs"]["json"]["template"]["components"] == [
        {
            "type": "body",
            "parameters": [{"type": "text", "text": "Amina"}],
        }
    ]


def test_meta_checkin_returns_message_id_for_delivery_tracking(monkeypatch) -> None:
    """AC-15.6/15.10: accepted WhatsApp has a durable status correlation ID."""
    requests: list[dict[str, Any]] = []

    def fake_post(*args, **kwargs):
        requests.append({"args": args, "kwargs": kwargs})
        return FakeJsonResponse({"messages": [{"id": "wamid.checkin-1"}]})

    monkeypatch.setattr("app.notifications.providers.httpx.post", fake_post)
    settings = Settings(
        jwt_secret="test-secret-at-least-32-characters-long",
        whatsapp_access_token="meta-token",
        whatsapp_phone_number_id="phone-id",
        whatsapp_checkin_template="pilgrim_safe_checkin_v1",
    )

    message_id = MetaWhatsAppSender(settings).send_checkin(
        "+2349012345678",
        "Amina Yusuf",
        "13 Jul 2026, 09:05 WAT",
        "https://www.google.com/maps?q=21.422487,39.826206",
    )

    assert message_id == "wamid.checkin-1"
    assert requests[0]["kwargs"]["json"]["template"]["name"] == (
        "pilgrim_safe_checkin_v1"
    )


def test_termii_family_sms_uses_plain_message_endpoint() -> None:
    """AC-15.10: fallback uses Termii outbound SMS, not the OTP endpoint."""
    class Client:
        def __init__(self) -> None:
            self.requests: list[tuple[str, dict[str, Any]]] = []

        def post(self, path: str, json: dict[str, Any]) -> FakeJsonResponse:
            self.requests.append((path, json))
            return FakeJsonResponse({"message_id": "termii-family-1"})

    client = Client()
    settings = Settings(
        jwt_secret="test-secret-at-least-32-characters-long",
        termii_api_key="termii-key",
        termii_sender_id="DamDam",
    )
    message_id = TermiiSmsSender(settings, client).send(  # type: ignore[arg-type]
        "+2349012345678", "Amina checked in safely. All is well."
    )

    assert message_id == "termii-family-1"
    path, payload = client.requests[0]
    assert path == "/api/sms/send"
    assert payload["to"] == "2349012345678"
    assert payload["type"] == "plain"
    assert payload["sms"] == "Amina checked in safely. All is well."
