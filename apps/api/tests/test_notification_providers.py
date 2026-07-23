from decimal import Decimal
from typing import Any

from app.config import Settings
from app.notifications.providers import (
    FirebasePushSender,
    MetaWhatsAppSender,
    ResendEmailSender,
    TermiiSmsSender,
)
from app.notifications.service import NotificationError


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


def test_meta_selects_the_approved_french_template_and_language(monkeypatch) -> None:
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
        whatsapp_family_nomination_template_fr="contact_familial_designe_v1",
    )

    MetaWhatsAppSender(settings).send_family_nomination("+221771234567", locale="fr")

    template = requests[0]["kwargs"]["json"]["template"]
    assert template["name"] == "contact_familial_designe_v1"
    assert template["language"] == {"code": "fr"}


def test_resend_renders_french_subject_and_body(monkeypatch) -> None:
    requests: list[dict[str, Any]] = []

    def fake_post(*args, **kwargs):
        requests.append({"args": args, "kwargs": kwargs})
        return FakeResponse()

    monkeypatch.setattr("app.notifications.providers.httpx.post", fake_post)
    settings = Settings(
        jwt_secret="test-secret-at-least-32-characters-long",
        resend_api_key="resend-token",
    )

    ResendEmailSender(settings).send_verification(
        "amina@example.com",
        "Amina",
        "https://damdam.app/verify",
        locale="fr",
    )

    payload = requests[0]["kwargs"]["json"]
    assert payload["subject"] == "Vérifiez votre compte opérateur DamDam"
    assert "Ce lien expire dans 24 heures." in payload["html"]


def test_french_receipt_localizes_tier_and_amount_parameters(monkeypatch) -> None:
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

    MetaWhatsAppSender(settings).send_receipt(
        "+221771234567",
        "Family",
        Decimal("128000.50"),
        "ref-fr",
        locale="fr",
    )

    parameters = requests[0]["kwargs"]["json"]["template"]["components"][0][
        "parameters"
    ]
    assert parameters[0]["text"] == "Famille"
    assert parameters[1]["text"] == "NGN 128\u202f000,50"


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


def test_firebase_push_sends_to_the_correct_topic(monkeypatch) -> None:
    """AC-19.1: an HTO alert must target that org's own topic, not a global one."""
    requests: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> FakeJsonResponse:
        requests.append({"url": url, **kwargs})
        return FakeJsonResponse({})

    monkeypatch.setattr("app.notifications.providers.httpx.post", fake_post)
    settings = Settings(
        jwt_secret="test-secret-at-least-32-characters-long",
        firebase_project_id="damdam-prod",
        firebase_access_token="firebase-oauth-token",
    )

    FirebasePushSender(settings).send_topic(
        "hto-org-1",
        "URGENT: pilgrim SOS",
        "Amina Yusuf needs help now.",
        {"sos_id": "n-1"},
    )

    assert requests[0]["url"] == (
        "https://fcm.googleapis.com/v1/projects/damdam-prod/messages:send"
    )
    assert requests[0]["headers"]["Authorization"] == "Bearer firebase-oauth-token"
    assert requests[0]["json"]["message"]["topic"] == "hto-org-1"
    assert requests[0]["json"]["message"]["notification"]["title"] == (
        "URGENT: pilgrim SOS"
    )


def test_firebase_push_send_topic_requires_configuration() -> None:
    settings = Settings(jwt_secret="test-secret-at-least-32-characters-long")
    try:
        FirebasePushSender(settings).send_topic("hto-org-1", "t", "b", {})
        raise AssertionError("expected NotificationError")
    except NotificationError as exc:
        assert "not configured" in str(exc)


def test_firebase_subscribe_topic_associates_the_token_via_instance_id_api(
    monkeypatch,
) -> None:
    """A browser's FCM registration token must be linked to the org's own
    topic (hto-{org_id}), not a shared/global one, via Firebase's Instance
    ID batchAdd endpoint — the real server-side half of the browser push
    subscription flow; getToken() alone never subscribes anything."""
    requests: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> FakeJsonResponse:
        requests.append({"url": url, **kwargs})
        return FakeJsonResponse({})

    monkeypatch.setattr("app.notifications.providers.httpx.post", fake_post)
    settings = Settings(
        jwt_secret="test-secret-at-least-32-characters-long",
        firebase_access_token="firebase-oauth-token",
    )

    FirebasePushSender(settings).subscribe_topic("browser-fcm-token", "hto-org-1")

    assert requests[0]["url"] == "https://iid.googleapis.com/iid/v1:batchAdd"
    assert requests[0]["headers"]["Authorization"] == "Bearer firebase-oauth-token"
    assert requests[0]["json"] == {
        "to": "/topics/hto-org-1",
        "registration_tokens": ["browser-fcm-token"],
    }


def test_firebase_subscribe_topic_requires_configuration() -> None:
    settings = Settings(jwt_secret="test-secret-at-least-32-characters-long")
    try:
        FirebasePushSender(settings).subscribe_topic("token", "hto-org-1")
        raise AssertionError("expected NotificationError")
    except NotificationError as exc:
        assert "not configured" in str(exc)


def test_firebase_subscribe_topic_wraps_http_errors(monkeypatch) -> None:
    import httpx

    def fake_post(url: str, **kwargs: Any):
        raise httpx.ConnectError("network unreachable")

    monkeypatch.setattr("app.notifications.providers.httpx.post", fake_post)
    settings = Settings(
        jwt_secret="test-secret-at-least-32-characters-long",
        firebase_access_token="firebase-oauth-token",
    )

    try:
        FirebasePushSender(settings).subscribe_topic("token", "hto-org-1")
        raise AssertionError("expected NotificationError")
    except NotificationError as exc:
        assert "subscription failed" in str(exc)
