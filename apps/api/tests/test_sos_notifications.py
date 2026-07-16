"""Direct coverage of SOSProviderAdapter's per-channel routing.

Every existing SOS API/model test dispatches through RecordingSOSSender, a
generic double implementing the SOSChannelSender Protocol directly — it
never exercises SOSProviderAdapter itself, so nothing proves the adapter
actually routes each of the four channels to its real vendor call, with the
right destination and arguments, rather than e.g. two channels silently
hitting the same function or WhatsApp operator/family destinations being
swapped.
"""

from dataclasses import dataclass

import pytest

from app.notifications.service import NotificationError, NotificationService
from app.sos.models import SOSNotificationChannel, SOSNotificationEvent
from app.sos.notifications import SOSDeliveryContext, SOSProviderAdapter


@dataclass
class FakePush:
    calls: list[tuple[str, str, str, dict[str, str]]]

    def __init__(self) -> None:
        self.calls = []

    def send_topic(
        self, topic: str, title: str, body: str, data: dict[str, str]
    ) -> None:
        self.calls.append((topic, title, body, data))


class FakeEmail:
    def __init__(self) -> None:
        self.sos_calls: list[tuple] = []

    def send_sos(
        self, email, pilgrim_name, pilgrim_phone, timestamp, maps_url, cancelled,
        notification_id,
    ) -> None:
        self.sos_calls.append(
            (email, pilgrim_name, pilgrim_phone, timestamp, maps_url, cancelled,
             notification_id)
        )

    def send_verification(self, *a, **k):
        raise AssertionError("not used by SOS")

    def send_approval(self, *a, **k):
        raise AssertionError("not used by SOS")

    def send_invoice(self, *a, **k):
        raise AssertionError("not used by SOS")

    def send_receipt(self, *a, **k):
        raise AssertionError("not used by SOS")


class FakeWhatsApp:
    def __init__(self) -> None:
        self.sos_calls: list[tuple] = []

    def send_sos(
        self, phone_number, pilgrim_name, timestamp, maps_url, hto_phone, cancelled,
    ) -> str:
        self.sos_calls.append(
            (phone_number, pilgrim_name, timestamp, maps_url, hto_phone, cancelled)
        )
        return "wamid.sos.1"

    def send_approval(self, *a, **k):
        raise AssertionError("not used by SOS")

    def send_family_nomination(self, *a, **k):
        raise AssertionError("not used by SOS")

    def send_activation(self, *a, **k):
        raise AssertionError("not used by SOS")

    def send_receipt(self, *a, **k):
        raise AssertionError("not used by SOS")

    def send_esim_ready(self, *a, **k):
        raise AssertionError("not used by SOS")

    def send_checkin(self, *a, **k):
        raise AssertionError("not used by SOS")


def _context(
    channel: SOSNotificationChannel, family_phone: str | None
) -> SOSDeliveryContext:
    from uuid import uuid4

    return SOSDeliveryContext(
        notification_id=uuid4(),
        channel=channel,
        event=SOSNotificationEvent.TRIGGERED,
        pilgrim_name="Amina Yusuf",
        pilgrim_phone="+2348012345678",
        hto_name="Barakah Hajj",
        hto_phone="+2348099999999",
        hto_email="ops@barakah.example",
        family_phone=family_phone,
        timestamp="16 Jul 2026, 09:05 WAT",
        maps_url="https://www.google.com/maps?q=21.422487,39.826206",
        hto_topic="hto-org-1",
    )


def test_push_channel_sends_topic_notification_to_hto() -> None:
    push = FakePush()
    adapter = SOSProviderAdapter(
        NotificationService(email=FakeEmail(), whatsapp=FakeWhatsApp()), push
    )

    adapter.send(_context(SOSNotificationChannel.PUSH, "+2348088888888"))

    assert len(push.calls) == 1
    topic, title, body, data = push.calls[0]
    assert topic == "hto-org-1"
    assert title == "URGENT: pilgrim SOS"
    assert "Amina Yusuf" in body and "needs help now" in body
    assert data["event"] == "triggered"


def test_email_channel_reaches_email_sender_with_hto_address() -> None:
    email = FakeEmail()
    adapter = SOSProviderAdapter(
        NotificationService(email=email, whatsapp=FakeWhatsApp()), FakePush()
    )

    adapter.send(_context(SOSNotificationChannel.EMAIL, "+2348088888888"))

    assert len(email.sos_calls) == 1
    assert email.sos_calls[0][0] == "ops@barakah.example"
    assert email.sos_calls[0][1] == "Amina Yusuf"
    assert email.sos_calls[0][5] is False  # cancelled


def test_whatsapp_operator_channel_sends_to_hto_phone_not_family() -> None:
    whatsapp = FakeWhatsApp()
    adapter = SOSProviderAdapter(
        NotificationService(email=FakeEmail(), whatsapp=whatsapp), FakePush()
    )

    adapter.send(
        _context(SOSNotificationChannel.WHATSAPP_OPERATOR, "+2348088888888")
    )

    assert len(whatsapp.sos_calls) == 1
    assert whatsapp.sos_calls[0][0] == "+2348099999999"  # hto_phone destination


def test_whatsapp_family_channel_sends_to_family_phone_not_operator() -> None:
    whatsapp = FakeWhatsApp()
    adapter = SOSProviderAdapter(
        NotificationService(email=FakeEmail(), whatsapp=whatsapp), FakePush()
    )

    adapter.send(
        _context(SOSNotificationChannel.WHATSAPP_FAMILY, "+2348088888888")
    )

    assert len(whatsapp.sos_calls) == 1
    assert whatsapp.sos_calls[0][0] == "+2348088888888"  # family_phone destination


def test_whatsapp_family_channel_without_a_family_contact_raises() -> None:
    whatsapp = FakeWhatsApp()
    adapter = SOSProviderAdapter(
        NotificationService(email=FakeEmail(), whatsapp=whatsapp), FakePush()
    )

    with pytest.raises(NotificationError, match="family contact unavailable"):
        adapter.send(_context(SOSNotificationChannel.WHATSAPP_FAMILY, None))

    assert whatsapp.sos_calls == []
