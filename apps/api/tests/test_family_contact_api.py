from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.auth.routes import request_otp, verify_otp
from app.auth.schemas import OTPRequest, OTPVerifyRequest
from app.main import create_app
from app.notifications.service import NotificationError
from app.profile.models import FamilyContact

PILGRIM_PHONE = "08012345678"
CONTACT_PHONE = "09012345678"
UPDATED_CONTACT_PHONE = "08123456789"


class FakeWhatsAppSender:
    def __init__(self) -> None:
        self.approvals: list[tuple[str, str]] = []
        self.nominations: list[str] = []
        self.fail_nomination = False

    def send_approval(self, phone_number: str, operator_name: str) -> None:
        self.approvals.append((phone_number, operator_name))

    def send_family_nomination(self, phone_number: str) -> None:
        if self.fail_nomination:
            raise NotificationError("WhatsApp unavailable")
        self.nominations.append(phone_number)


@pytest.fixture
def whatsapp_sender() -> FakeWhatsAppSender:
    return FakeWhatsAppSender()


@pytest.fixture
def family_api(
    settings,
    redis_client,
    providers,
    scheduler,
    clock,
    session_factory,
    whatsapp_sender,
):
    return create_app(
        settings=settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
        whatsapp_sender=whatsapp_sender,
    )


def authenticated_client(api, phone_number: str = PILGRIM_PHONE) -> TestClient:
    request = SimpleNamespace(app=api)
    request_otp(OTPRequest(phone_number=phone_number), request)
    auth = verify_otp(
        OTPVerifyRequest(
            phone_number=phone_number,
            otp="123456",
            platform="android",
        ),
        request,
    )
    return TestClient(
        api,
        headers={"Authorization": f"Bearer {auth.access_token}"},
    )


def test_nomination_accepts_nigerian_number_and_sends_whatsapp(
    family_api, session_factory, whatsapp_sender
) -> None:
    """AC-03.1/03.2: save an E.164 contact and notify without confirmation."""
    client = authenticated_client(family_api)

    response = client.post(
        "/v1/me/family-contact",
        json={"phone_number": CONTACT_PHONE, "name": "Hauwa Yusuf"},
    )

    assert response.status_code == 201
    assert response.json() == {
        "id": response.json()["id"],
        "phone_number": "+2349012345678",
        "name": "Hauwa Yusuf",
        "notified_of_nomination": True,
    }
    assert whatsapp_sender.nominations == ["+2349012345678"]
    with session_factory() as session:
        contact = session.exec(select(FamilyContact)).one()
        assert contact.phone_number == "+2349012345678"
        assert contact.notified_of_nomination is True


@pytest.mark.parametrize(
    "phone_number",
    ["+2349012345678", "0901234567", "06012345678", "not-a-number"],
)
def test_nomination_rejects_non_nigerian_or_invalid_numbers(
    family_api, whatsapp_sender, phone_number
) -> None:
    """AC-03.1: accept only the local Nigerian mobile format."""
    client = authenticated_client(family_api)

    response = client.post(
        "/v1/me/family-contact", json={"phone_number": phone_number}
    )

    assert response.status_code == 422
    assert whatsapp_sender.nominations == []


def test_only_one_family_contact_can_be_created_per_pilgrim(
    family_api, session_factory, whatsapp_sender
) -> None:
    """AC-03.4: a second POST cannot create another contact for one pilgrim."""
    client = authenticated_client(family_api)
    first = client.post(
        "/v1/me/family-contact", json={"phone_number": CONTACT_PHONE}
    )

    duplicate = client.post(
        "/v1/me/family-contact", json={"phone_number": UPDATED_CONTACT_PHONE}
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["error"] == "family_contact_exists"
    assert whatsapp_sender.nominations == ["+2349012345678"]
    with session_factory() as session:
        assert len(session.exec(select(FamilyContact)).all()) == 1


def test_family_contact_can_be_updated_without_creating_a_second_row(
    family_api, session_factory, whatsapp_sender
) -> None:
    """AC-03.3/03.4: PATCH replaces the number and notifies the new contact."""
    client = authenticated_client(family_api)
    created = client.post(
        "/v1/me/family-contact",
        json={"phone_number": CONTACT_PHONE, "name": "Hauwa"},
    )

    updated = client.patch(
        "/v1/me/family-contact",
        json={"phone_number": UPDATED_CONTACT_PHONE, "name": "Maryam"},
    )

    assert updated.status_code == 200
    assert updated.json() == {
        "id": created.json()["id"],
        "phone_number": "+2348123456789",
        "name": "Maryam",
        "notified_of_nomination": True,
    }
    assert whatsapp_sender.nominations == [
        "+2349012345678",
        "+2348123456789",
    ]
    with session_factory() as session:
        assert len(session.exec(select(FamilyContact)).all()) == 1


def test_name_only_update_does_not_repeat_nomination_message(
    family_api, whatsapp_sender
) -> None:
    """AC-03.2/03.3: profile edits do not duplicate a delivered nomination."""
    client = authenticated_client(family_api)
    client.post("/v1/me/family-contact", json={"phone_number": CONTACT_PHONE})

    updated = client.patch("/v1/me/family-contact", json={"name": "Hauwa"})

    assert updated.status_code == 200
    assert updated.json()["name"] == "Hauwa"
    assert whatsapp_sender.nominations == ["+2349012345678"]


def test_pilgrim_cannot_update_another_pilgrims_family_contact(
    family_api, session_factory
) -> None:
    """AC-03.3/03.4: PATCH is scoped to the authenticated pilgrim."""
    owner = authenticated_client(family_api)
    owner.post("/v1/me/family-contact", json={"phone_number": CONTACT_PHONE})
    other_pilgrim = authenticated_client(family_api, "08100000000")

    response = other_pilgrim.patch(
        "/v1/me/family-contact", json={"phone_number": UPDATED_CONTACT_PHONE}
    )

    assert response.status_code == 404
    assert response.json()["error"] == "family_contact_not_found"
    with session_factory() as session:
        contact = session.exec(select(FamilyContact)).one()
        assert contact.phone_number == "+2349012345678"


def test_failed_notification_is_retryable_without_losing_nomination(
    family_api, session_factory, whatsapp_sender
) -> None:
    """AC-03.2: retain an undelivered nomination and retry the same number."""
    client = authenticated_client(family_api)
    whatsapp_sender.fail_nomination = True

    failed = client.post(
        "/v1/me/family-contact", json={"phone_number": CONTACT_PHONE}
    )

    assert failed.status_code == 503
    assert failed.json()["error"] == "notification_unavailable"
    with session_factory() as session:
        contact = session.exec(select(FamilyContact)).one()
        assert contact.notified_of_nomination is False

    whatsapp_sender.fail_nomination = False
    retried = client.patch(
        "/v1/me/family-contact", json={"phone_number": CONTACT_PHONE}
    )

    assert retried.status_code == 200
    assert retried.json()["notified_of_nomination"] is True
    assert whatsapp_sender.nominations == ["+2349012345678"]


def test_family_contact_endpoints_require_pilgrim_authentication(family_api) -> None:
    """AC-03.4: family-contact ownership derives from the pilgrim session."""
    client = TestClient(family_api)

    response = client.post(
        "/v1/me/family-contact", json={"phone_number": CONTACT_PHONE}
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_access_token"
