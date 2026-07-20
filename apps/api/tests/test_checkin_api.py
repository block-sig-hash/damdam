import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
from sqlmodel import select

from app.auth.dependencies import get_current_user
from app.auth.models import (
    HTOApprovalStatus,
    Manifest,
    ManifestPilgrim,
    ManifestStatus,
    ManifestValidationStatus,
    Organization,
    OrganizationType,
    PricingTier,
    User,
)
from app.auth.routes import request_otp, verify_otp
from app.auth.schemas import OTPRequest, OTPVerifyRequest
from app.checkins.models import CheckIn, CheckInNotification
from app.esim.service import HtoPilgrimService
from app.main import create_app
from app.packages.models import Package, PackageSource, PackageStatus
from app.profile.models import FamilyContact


class RecordingCheckInScheduler:
    def __init__(self) -> None:
        self.dispatches: list[UUID] = []
        self.fallbacks: list[tuple[UUID, int]] = []
        self.fail_dispatch = False

    def schedule_dispatch(self, notification_id: UUID) -> None:
        if self.fail_dispatch:
            raise RuntimeError("broker unavailable")
        self.dispatches.append(notification_id)

    def schedule_fallback(self, notification_id: UUID, countdown: int) -> None:
        self.fallbacks.append((notification_id, countdown))


class RecordingWhatsAppSender:
    def __init__(self) -> None:
        self.checkins: list[tuple[str, str, str, str | None]] = []
        self.fail = False

    def send_checkin(
        self, phone_number: str, pilgrim_name: str, checked_in_at: str,
        maps_url: str | None,
    ) -> str:
        if self.fail:
            from app.notifications.service import NotificationError

            raise NotificationError("whatsapp unavailable")
        self.checkins.append((phone_number, pilgrim_name, checked_in_at, maps_url))
        return f"wamid.{len(self.checkins)}"


class RecordingSmsSender:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.fail = False

    def send(self, phone_number: str, message: str) -> str:
        if self.fail:
            from app.notifications.service import NotificationError

            raise NotificationError("sms unavailable")
        self.messages.append((phone_number, message))
        return f"termii-sms-{len(self.messages)}"


class ApiClient:
    """ASGI client that avoids the local Conda blocking-portal regression."""

    def __init__(self, api, headers: dict[str, str]) -> None:
        self.api = api
        self.headers = headers

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        async def run() -> httpx.Response:
            headers = {**self.headers, **kwargs.pop("headers", {})}
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.api),
                base_url="http://testserver",
                headers=headers,
            ) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(run())

    def post(self, path: str, **kwargs) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self.request("GET", path, **kwargs)


def _build_api(
    settings, redis_client, providers, scheduler, session_factory, clock,
    whatsapp, sms, checkin_scheduler,
):
    return create_app(
        settings=settings.model_copy(
            update={
                "whatsapp_app_secret": "meta-app-secret",
                "whatsapp_webhook_verify_token": "meta-verify-token",
            }
        ),
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
        whatsapp_sender=whatsapp,
        sms_sender=sms,
        checkin_scheduler=checkin_scheduler,
    )


def _authenticated(api) -> tuple[ApiClient, UUID]:
    request = SimpleNamespace(app=api)
    request_otp(OTPRequest(phone_number="08012345678"), request)
    auth = verify_otp(
        OTPVerifyRequest(
            phone_number="08012345678", otp="123456", platform="android"
        ),
        request,
    )
    async def current_user_override():
        return auth.user

    api.dependency_overrides[get_current_user] = current_user_override
    return (
        ApiClient(api, headers={"Authorization": f"Bearer {auth.access_token}"}),
        auth.user.id,
    )


def _api_dependencies(
    settings, redis_client, providers, scheduler, session_factory, clock
):
    whatsapp = RecordingWhatsAppSender()
    sms = RecordingSmsSender()
    notification_scheduler = RecordingCheckInScheduler()
    api = _build_api(
        settings, redis_client, providers, scheduler, session_factory, clock,
        whatsapp, sms, notification_scheduler,
    )
    return api, whatsapp, sms, notification_scheduler


def test_family_notification_channel_order_is_wired_from_settings(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    configured = settings.model_copy(
        update={
            "family_notify_channel_primary": "sms",
            "family_notify_channel_secondary": "whatsapp",
        }
    )
    api = _build_api(
        configured,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        RecordingWhatsAppSender(),
        RecordingSmsSender(),
        RecordingCheckInScheduler(),
    )

    service = api.state.checkin_notification_service
    assert service.primary_channel == "sms"
    assert service.secondary_channel == "whatsapp"


def test_checkin_records_tap_time_location_and_queues_one_notification(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-15.2/15.3/15.5/15.6/15.7: persist immediately and enqueue delivery."""
    api, _, _, notification_scheduler = _api_dependencies(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)
    with session_factory() as session:
        tier = PricingTier(
            name="Check-in retention",
            usd_reference_price=Decimal("10.00"),
            data_gb=1,
            pstn_minutes=10,
            wholesale_usd_price=Decimal("8.00"),
            ngn_price=Decimal("1000.00"),
        )
        session.add(tier)
        session.flush()
        session.add(
            Package(
                user_id=user_id,
                pricing_tier_id=tier.id,
                source=PackageSource.RETAIL,
                status=PackageStatus.ACTIVE,
                data_gb_total=1,
                data_gb_remaining=Decimal("1.00"),
                pstn_minutes_total=10,
                pstn_minutes_remaining=Decimal("10.00"),
                purchased_at=clock(),
                expires_at=clock() + timedelta(days=30),
            )
        )
        session.add(FamilyContact(user_id=user_id, phone_number="+2349012345678"))
        session.commit()
    client_id = uuid4()
    timestamp = "2026-07-13T08:05:00Z"

    response = client.post(
        "/v1/checkins",
        json={
            "client_generated_id": str(client_id),
            "timestamp": timestamp,
            "latitude": 21.422487,
            "longitude": 39.826206,
        },
    )

    assert response.status_code == 200
    assert response.json()["received_at"] == clock().isoformat().replace("+00:00", "Z")
    with session_factory() as session:
        checkin = session.exec(select(CheckIn)).one()
        notification = session.exec(select(CheckInNotification)).one()
        assert checkin.user_id == user_id
        assert checkin.client_generated_id == client_id
        stored_timestamp = checkin.timestamp
        if stored_timestamp.tzinfo is None:
            stored_timestamp = stored_timestamp.replace(tzinfo=timezone.utc)
        assert stored_timestamp == datetime(2026, 7, 13, 8, 5, tzinfo=timezone.utc)
        retention_due = checkin.location_retention_due_at
        if retention_due.tzinfo is None:
            retention_due = retention_due.replace(tzinfo=timezone.utc)
        assert retention_due == clock() + timedelta(days=120)
        assert float(checkin.latitude) == 21.422487
        assert float(checkin.longitude) == 39.826206
        assert notification.check_in_id == checkin.id
        assert notification_scheduler.dispatches == [notification.id]


def test_retry_with_same_client_id_returns_same_row_and_never_resends(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-15.4: a lost response retry cannot duplicate check-ins or WhatsApp."""
    api, _, _, notification_scheduler = _api_dependencies(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)
    with session_factory() as session:
        session.add(FamilyContact(user_id=user_id, phone_number="+2349012345678"))
        session.commit()
    payload = {
        "client_generated_id": str(uuid4()),
        "timestamp": "2026-07-13T08:05:00Z",
    }

    first = client.post("/v1/checkins", json=payload)
    second = client.post("/v1/checkins", json=payload)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    with session_factory() as session:
        assert len(session.exec(select(CheckIn)).all()) == 1
        assert len(session.exec(select(CheckInNotification)).all()) == 1
    assert len(notification_scheduler.dispatches) == 1


def test_redis_rate_limit_blocks_a_different_checkin_for_fifteen_minutes(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-15.9: limiter is shared in Redis and keyed per user."""
    api, _, _, _ = _api_dependencies(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)
    first = client.post(
        "/v1/checkins",
        json={"client_generated_id": str(uuid4()), "timestamp": clock().isoformat()},
    )
    second = client.post(
        "/v1/checkins",
        json={"client_generated_id": str(uuid4()), "timestamp": clock().isoformat()},
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"] == "checkin_rate_limited"
    assert 0 < redis_client.ttl(f"checkin:rate:{user_id}") <= 900


def test_redis_outage_fails_open_but_postgres_ceiling_caps_notifications(
    settings,
    redis_client,
    providers,
    scheduler,
    session_factory,
    clock,
    monkeypatch,
) -> None:
    """During a sustained Redis outage, every distinct check-in is still
    persisted (the safety-critical write is never blocked), but only the
    first one within the 15-minute window triggers a family WhatsApp/SMS
    notification. The Postgres-backed fallback ceiling in
    `_recent_checkin_already_notified` closes the gap Redis would otherwise
    have covered: unlimited notification-triggering spam during an outage."""
    api, whatsapp, _, notification_scheduler = _api_dependencies(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)
    with session_factory() as session:
        session.add(FamilyContact(user_id=user_id, phone_number="+2349012345678"))
        session.commit()

    def redis_unavailable(*args, **kwargs):
        del args, kwargs
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(redis_client, "set", redis_unavailable)

    responses = [
        client.post(
            "/v1/checkins",
            json={
                "client_generated_id": str(uuid4()),
                "timestamp": clock().isoformat(),
            },
        )
        for _ in range(5)
    ]

    assert [r.status_code for r in responses] == [200] * 5
    with session_factory() as session:
        assert len(session.exec(select(CheckIn)).all()) == 5
        assert len(session.exec(select(CheckInNotification)).all()) == 1
    assert len(notification_scheduler.dispatches) == 1
    assert len(whatsapp.checkins) == 0  # dispatch is scheduled, not sent inline


def test_recent_checkin_ceiling_never_applies_when_redis_is_available(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """The Postgres fallback ceiling only activates on Redis failure. With
    Redis healthy, a second distinct check-in inside the window is still
    rejected outright by the existing Redis limiter (429), proving the new
    check does not change the normal, non-outage path."""
    api, _, _, notification_scheduler = _api_dependencies(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)
    with session_factory() as session:
        session.add(FamilyContact(user_id=user_id, phone_number="+2349012345678"))
        session.commit()

    first = client.post(
        "/v1/checkins",
        json={"client_generated_id": str(uuid4()), "timestamp": clock().isoformat()},
    )
    second = client.post(
        "/v1/checkins",
        json={"client_generated_id": str(uuid4()), "timestamp": clock().isoformat()},
    )

    assert first.status_code == 200
    assert second.status_code == 429
    with session_factory() as session:
        assert len(session.exec(select(CheckIn)).all()) == 1
    assert len(notification_scheduler.dispatches) == 1


def test_redis_outage_fails_open_without_losing_the_checkin(
    settings,
    redis_client,
    providers,
    scheduler,
    session_factory,
    clock,
    monkeypatch,
) -> None:
    """§14.4.1: rate-limit infrastructure cannot block the safety write."""
    api, _, _, notification_scheduler = _api_dependencies(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)
    with session_factory() as session:
        session.add(FamilyContact(user_id=user_id, phone_number="+2349012345678"))
        session.commit()

    def redis_unavailable(*args, **kwargs):
        del args, kwargs
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(redis_client, "set", redis_unavailable)
    response = client.post(
        "/v1/checkins",
        json={"client_generated_id": str(uuid4()), "timestamp": clock().isoformat()},
    )

    assert response.status_code == 200
    with session_factory() as session:
        assert len(session.exec(select(CheckIn)).all()) == 1
        assert len(session.exec(select(CheckInNotification)).all()) == 1
    assert len(notification_scheduler.dispatches) == 1


def test_recent_history_is_owned_limited_and_newest_first(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-15.8: Home can read the pilgrim's latest successful check-in."""
    api, _, _, _ = _api_dependencies(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)
    with session_factory() as session:
        for index in range(12):
            session.add(
                CheckIn(
                    user_id=user_id,
                    client_generated_id=uuid4(),
                    timestamp=clock() + timedelta(minutes=index),
                    received_at=clock() + timedelta(minutes=index),
                )
            )
        other = User(phone_number="+2348099999999", platform="android")
        session.add(other)
        session.flush()
        session.add(
            CheckIn(
                user_id=other.id,
                client_generated_id=uuid4(),
                timestamp=clock() + timedelta(days=1),
                received_at=clock() + timedelta(days=1),
            )
        )
        session.commit()

    response = client.get("/v1/me/checkins?limit=10")

    assert response.status_code == 200
    assert len(response.json()["checkins"]) == 10
    timestamps = [row["timestamp"] for row in response.json()["checkins"]]
    assert timestamps == sorted(timestamps, reverse=True)


def test_whatsapp_copy_maps_link_and_sms_fallback_fire_at_sixty_seconds(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-15.6/15.7/15.10: fallback is due at 60s, not merely present."""
    api, whatsapp, sms, notification_scheduler = _api_dependencies(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)
    with session_factory() as session:
        user = session.get(User, user_id)
        assert user is not None
        user.first_name = "Amina"
        user.last_name = "Yusuf"
        session.add(user)
        session.add(FamilyContact(user_id=user_id, phone_number="+2349012345678"))
        session.commit()
    response = client.post(
        "/v1/checkins",
        json={
            "client_generated_id": str(uuid4()),
            "timestamp": "2026-07-13T08:05:00Z",
            "latitude": 21.422487,
            "longitude": 39.826206,
        },
    )
    notification_id = notification_scheduler.dispatches[0]

    with session_factory() as session:
        service = api.state.checkin_notification_service
        assert service.dispatch_whatsapp(session, notification_id) is True
    assert whatsapp.checkins == [
        (
            "+2349012345678",
            "Amina Yusuf",
            "13 Jul 2026, 09:05 WAT",
            "https://www.google.com/maps?q=21.422487,39.826206",
        )
    ]
    assert notification_scheduler.fallbacks == [(notification_id, 60)]

    clock.advance(seconds=59)
    with session_factory() as session:
        assert service.send_sms_fallback(session, notification_id) is False
    assert sms.messages == []

    clock.advance(seconds=1)
    with session_factory() as session:
        assert service.send_sms_fallback(session, notification_id) is True
    assert sms.messages == [
        (
            "+2349012345678",
            "Amina Yusuf checked in safely at 13 Jul 2026, 09:05 WAT. All is well. "
            "https://www.google.com/maps?q=21.422487,39.826206",
        )
    ]
    assert response.status_code == 200


def test_confirmed_whatsapp_delivery_cancels_sms_fallback(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-15.10: a delivery confirmation before 60s prevents duplicate SMS."""
    api, _, sms, notification_scheduler = _api_dependencies(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)
    with session_factory() as session:
        session.add(FamilyContact(user_id=user_id, phone_number="+2349012345678"))
        session.commit()
    client.post(
        "/v1/checkins",
        json={"client_generated_id": str(uuid4()), "timestamp": clock().isoformat()},
    )
    notification_id = notification_scheduler.dispatches[0]
    service = api.state.checkin_notification_service
    with session_factory() as session:
        service.dispatch_whatsapp(session, notification_id)
        assert service.confirm_whatsapp_delivery(session, "wamid.1") is True
    clock.advance(seconds=60)
    with session_factory() as session:
        assert service.send_sms_fallback(session, notification_id) is False
    assert sms.messages == []


def test_signed_meta_delivery_webhook_marks_message_delivered(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-15.10: real delivery status reaches the fallback decision securely."""
    api, _, sms, notification_scheduler = _api_dependencies(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)
    with session_factory() as session:
        session.add(FamilyContact(user_id=user_id, phone_number="+2349012345678"))
        session.commit()
    client.post(
        "/v1/checkins",
        json={"client_generated_id": str(uuid4()), "timestamp": clock().isoformat()},
    )
    notification_id = notification_scheduler.dispatches[0]
    with session_factory() as session:
        api.state.checkin_notification_service.dispatch_whatsapp(
            session, notification_id
        )
    body = json.dumps(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {"id": "wamid.1", "status": "delivered"}
                                ]
                            }
                        }
                    ]
                }
            ]
        },
        separators=(",", ":"),
    ).encode()
    signature = "sha256=" + hmac.new(
        b"meta-app-secret", body, hashlib.sha256
    ).hexdigest()

    unsigned = client.post(
        "/v1/webhooks/meta/whatsapp", content=body,
        headers={"content-type": "application/json"},
    )
    delivered = client.post(
        "/v1/webhooks/meta/whatsapp", content=body,
        headers={"x-hub-signature-256": signature, "content-type": "application/json"},
    )
    clock.advance(seconds=60)
    with session_factory() as session:
        fallback = api.state.checkin_notification_service.send_sms_fallback(
            session, notification_id
        )

    assert unsigned.status_code == 401
    assert unsigned.json()["error"] == "invalid_webhook_signature"
    assert delivered.status_code == 200
    assert delivered.json() == {"processed": 1}
    assert fallback is False
    assert sms.messages == []


def test_meta_webhook_signed_with_wrong_secret_is_rejected(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-15.10: a well-formed signature computed with the wrong app secret
    must be rejected, not just a request missing the header entirely."""
    api, _, sms, notification_scheduler = _api_dependencies(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)
    with session_factory() as session:
        session.add(FamilyContact(user_id=user_id, phone_number="+2349012345678"))
        session.commit()
    client.post(
        "/v1/checkins",
        json={"client_generated_id": str(uuid4()), "timestamp": clock().isoformat()},
    )
    notification_id = notification_scheduler.dispatches[0]
    with session_factory() as session:
        api.state.checkin_notification_service.dispatch_whatsapp(
            session, notification_id
        )
    body = json.dumps(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {"id": "wamid.1", "status": "delivered"}
                                ]
                            }
                        }
                    ]
                }
            ]
        },
        separators=(",", ":"),
    ).encode()
    wrong_secret_signature = "sha256=" + hmac.new(
        b"attacker-guessed-secret", body, hashlib.sha256
    ).hexdigest()

    response = client.post(
        "/v1/webhooks/meta/whatsapp",
        content=body,
        headers={
            "x-hub-signature-256": wrong_secret_signature,
            "content-type": "application/json",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_webhook_signature"
    clock.advance(seconds=60)
    with session_factory() as session:
        fallback = api.state.checkin_notification_service.send_sms_fallback(
            session, notification_id
        )
    assert fallback is True
    assert len(sms.messages) == 1


def test_missing_family_contact_never_rolls_back_the_checkin(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-15.3: notification availability cannot lose the safety record."""
    api, _, _, notification_scheduler = _api_dependencies(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, _ = _authenticated(api)
    response = client.post(
        "/v1/checkins",
        json={"client_generated_id": str(uuid4()), "timestamp": clock().isoformat()},
    )

    assert response.status_code == 200
    with session_factory() as session:
        assert len(session.exec(select(CheckIn)).all()) == 1
        assert len(session.exec(select(CheckInNotification)).all()) == 0
    assert notification_scheduler.dispatches == []


def test_broker_outage_leaves_durable_pending_notification(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-15.6: a Celery outage cannot roll back or lose family notification."""
    api, _, _, notification_scheduler = _api_dependencies(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    notification_scheduler.fail_dispatch = True
    client, user_id = _authenticated(api)
    with session_factory() as session:
        session.add(FamilyContact(user_id=user_id, phone_number="+2349012345678"))
        session.commit()

    response = client.post(
        "/v1/checkins",
        json={"client_generated_id": str(uuid4()), "timestamp": clock().isoformat()},
    )

    assert response.status_code == 200
    with session_factory() as session:
        notification = session.exec(select(CheckInNotification)).one()
        assert notification.whatsapp_status.value == "pending"


def test_removed_family_contact_terminates_due_fallback(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    api, _, _, notification_scheduler = _api_dependencies(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)
    with session_factory() as session:
        session.add(FamilyContact(user_id=user_id, phone_number="+2349012345678"))
        session.commit()
    client.post(
        "/v1/checkins",
        json={"client_generated_id": str(uuid4()), "timestamp": clock().isoformat()},
    )
    notification_id = notification_scheduler.dispatches[0]
    service = api.state.checkin_notification_service
    with session_factory() as session:
        service.dispatch_whatsapp(session, notification_id)
        contact = session.exec(
            select(FamilyContact).where(FamilyContact.user_id == user_id)
        ).one()
        session.delete(contact)
        session.commit()
    clock.advance(seconds=60)

    with session_factory() as session:
        assert service.send_sms_fallback(session, notification_id) is False
        notification = session.get(CheckInNotification, notification_id)
        assert notification is not None
        assert notification.admin_queued_at is not None
        assert notification.sms_failure_reason == "family contact unavailable"


def test_failed_sms_retries_three_times_then_enters_admin_queue(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """PRD §5.6: fallback failure retries three times, then becomes operable."""
    api, _, sms, notification_scheduler = _api_dependencies(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)
    with session_factory() as session:
        session.add(FamilyContact(user_id=user_id, phone_number="+2349012345678"))
        session.commit()
    client.post(
        "/v1/checkins",
        json={"client_generated_id": str(uuid4()), "timestamp": clock().isoformat()},
    )
    notification_id = notification_scheduler.dispatches[0]
    service = api.state.checkin_notification_service
    with session_factory() as session:
        service.dispatch_whatsapp(session, notification_id)
    sms.fail = True
    clock.advance(seconds=60)

    for attempt in range(3):
        with session_factory() as session:
            assert service.send_sms_fallback(session, notification_id) is False
        if attempt < 2:
            clock.advance(seconds=30)

    with session_factory() as session:
        notification = session.get(CheckInNotification, notification_id)
        assert notification is not None
        assert notification.sms_attempt_count == 3
        assert notification.admin_queued_at is not None


def test_hto_pilgrim_monitoring_reads_latest_checkin_for_its_own_pilgrim(
    session_factory, clock
) -> None:
    """AC-15.5: successful receipt updates the existing HTO last-seen field."""
    with session_factory() as session:
        organization = Organization(
            org_type=OrganizationType.HTO_OPERATOR,
            name="Safe Hajj Ltd",
            primary_contact_name="Operator",
            email="operator@example.com",
            password_hash="hash",
            phone_number="+2348011111111",
            nahcon_licence_number="NAHCON-1",
            email_verified=True,
            approval_status=HTOApprovalStatus.APPROVED,
        )
        user = User(phone_number="+2348012345678", platform="android")
        session.add(organization)
        session.add(user)
        session.flush()
        manifest = Manifest(
            organization_id=organization.id,
            status=ManifestStatus.VALIDATED,
            valid_rows=1,
        )
        session.add(manifest)
        session.flush()
        pilgrim = ManifestPilgrim(
            manifest_id=manifest.id,
            first_name="Amina",
            last_name="Yusuf",
            phone_number=user.phone_number,
            row_number=2,
            validation_status=ManifestValidationStatus.VALID,
            user_id=user.id,
        )
        session.add(pilgrim)
        session.add(
            CheckIn(
                user_id=user.id,
                client_generated_id=uuid4(),
                timestamp=clock(),
                received_at=clock(),
            )
        )
        session.commit()
        result = HtoPilgrimService().list_pilgrims(session, organization, None)

    assert result[0].last_checkin_at == clock().isoformat()
