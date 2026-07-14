from typing import Any

from app.config import Settings
from app.notifications.providers import MetaWhatsAppSender


class FakeResponse:
    def raise_for_status(self) -> None:
        return None


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
