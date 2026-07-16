"""US-16 executable acceptance tests, committed before implementation."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
from sqlmodel import select

from app.admin.routes import _retry_sos_rows
from app.auth.dependencies import get_current_organization, get_current_user
from app.auth.models import (
    HTOApprovalStatus,
    Manifest,
    ManifestPilgrim,
    ManifestStatus,
    ManifestValidationStatus,
    Organization,
    OrganizationType,
    Platform,
    User,
)
from app.main import create_app
from app.profile.models import FamilyContact
from app.sos.models import (
    SOSAlert,
    SOSNotification,
    SOSNotificationChannel,
    SOSNotificationEvent,
    SOSNotificationStatus,
    SOSStatus,
)


class ApiClient:
    def __init__(self, api) -> None:
        self.api = api

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        async def run() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.api), base_url="http://test"
            ) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(run())

    def post(self, path: str, **kwargs) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self.request("GET", path, **kwargs)


class RecordingSOSScheduler:
    def __init__(self) -> None:
        self.dispatches: list[tuple[object, object]] = []
        self.fallbacks: list[tuple[object, int]] = []
        self.fail_dispatch = False

    def schedule_dispatch(self, notification_id, channel) -> None:
        if self.fail_dispatch:
            raise RuntimeError("broker unavailable")
        self.dispatches.append((notification_id, channel))

    def schedule_fallback(self, notification_id, countdown) -> None:
        self.fallbacks.append((notification_id, countdown))


class RecordingSOSSender:
    def __init__(self) -> None:
        self.fail = False
        self.sent = []

    def send(self, context):
        if self.fail:
            raise RuntimeError("provider unavailable")
        self.sent.append(context)
        return f"wamid.sos.{len(self.sent)}"


class ChannelSelectiveSOSSender:
    """Fails only one channel, succeeds the rest, so a single trigger event
    can prove the four channels fail and recover independently."""

    def __init__(self, failing_channel: SOSNotificationChannel) -> None:
        self.failing_channel = failing_channel
        self.sent: list[SOSNotificationChannel] = []

    def send(self, context) -> None:
        if context.channel == self.failing_channel:
            raise RuntimeError("provider unavailable for this channel")
        self.sent.append(context.channel)


class RecordingPushManager:
    def __init__(self) -> None:
        self.fail = False
        self.subscriptions: list[tuple[str, str]] = []

    def subscribe_topic(self, token: str, topic: str) -> None:
        if self.fail:
            from app.notifications.service import NotificationError

            raise NotificationError("provider unavailable")
        self.subscriptions.append((token, topic))


def _setup(
    settings, redis_client, providers, scheduler, session_factory, clock,
    sender=None, push_manager=None,
):
    sos_scheduler = RecordingSOSScheduler()
    sos_sender = sender if sender is not None else RecordingSOSSender()
    push_subscription_manager = (
        push_manager if push_manager is not None else RecordingPushManager()
    )
    api = create_app(
        settings=settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
        sos_scheduler=sos_scheduler,
        sos_sender=sos_sender,
        push_subscription_manager=push_subscription_manager,
    )
    user = User(
        phone_number="+2348012345678",
        first_name="Amina",
        last_name="Yusuf",
        platform=Platform.ANDROID,
    )
    organization = Organization(
        org_type=OrganizationType.HTO_OPERATOR,
        name="Barakah Hajj",
        primary_contact_name="Musa Bello",
        email="musa@example.test",
        password_hash="not-used-in-this-test",
        phone_number="+2348099999999",
        nahcon_licence_number="NAHCON-16",
        email_verified=True,
        approval_status=HTOApprovalStatus.APPROVED,
    )
    with session_factory() as session:
        session.add(user)
        session.add(organization)
        session.flush()
        manifest = Manifest(
            organization_id=organization.id,
            name="Hajj 2027",
            status=ManifestStatus.VALIDATED,
        )
        session.add(manifest)
        session.flush()
        session.add(
            ManifestPilgrim(
                manifest_id=manifest.id,
                first_name="Amina",
                last_name="Yusuf",
                phone_number=user.phone_number,
                row_number=1,
                validation_status=ManifestValidationStatus.VALID,
                user_id=user.id,
            )
        )
        session.add(
            FamilyContact(
                user_id=user.id,
                phone_number="+2348088888888",
                name="Zainab",
            )
        )
        session.commit()
        session.refresh(user)
        session.refresh(organization)
        session.expunge(user)
        session.expunge(organization)

    async def pilgrim_override():
        return user

    async def operator_override():
        return organization

    api.dependency_overrides[get_current_user] = pilgrim_override
    api.dependency_overrides[get_current_organization] = operator_override
    return api, ApiClient(api), user, organization, sos_scheduler


def _payload(client_id=None):
    return {
        "client_generated_id": str(client_id or uuid4()),
        "timestamp": "2026-07-16T08:05:00Z",
        "latitude": 21.422487,
        "longitude": 39.826206,
    }


def test_confirmed_sos_persists_location_and_four_channel_rows_before_dispatch(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-16.3: durable alert + four channel queue rows precede dispatch.
    SMS_FAMILY (AC-22.3) is deliberately excluded here: it's created lazily
    only if the WhatsApp family leg needs the fallback, never eagerly at
    trigger time alongside the other four."""
    api, client, user, _, sos_scheduler = _setup(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    response = client.post("/v1/sos", json=_payload())
    assert response.status_code == 200
    assert response.json()["status"] == "active"
    with session_factory() as session:
        alert = session.exec(select(SOSAlert)).one()
        notifications = session.exec(select(SOSNotification)).all()
        assert alert.user_id == user.id
        assert float(alert.latitude) == 21.422487
        assert {row.channel for row in notifications} == {
            SOSNotificationChannel.PUSH,
            SOSNotificationChannel.EMAIL,
            SOSNotificationChannel.WHATSAPP_OPERATOR,
            SOSNotificationChannel.WHATSAPP_FAMILY,
        }
        assert len(sos_scheduler.dispatches) == 4


def test_same_client_id_is_idempotent_and_has_no_rate_limit_for_distinct_ids(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-16.7: retries collapse; distinct deliberate events remain allowed."""
    _, client, _, _, sos_scheduler = _setup(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    first_id = uuid4()
    responses = [client.post("/v1/sos", json=_payload(first_id)) for _ in range(3)]
    distinct = client.post("/v1/sos", json=_payload())
    assert [row.status_code for row in responses] == [200, 200, 200]
    assert len({row.json()["id"] for row in responses}) == 1
    assert distinct.status_code == 200
    assert len(sos_scheduler.dispatches) == 8


def test_pilgrim_cancel_and_hto_resolve_are_separate_transitions(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-16.5/16.6: cancellation notifies; HTO resolution is a distinct actor path."""
    _, client, _, _, scheduler_recorder = _setup(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    alert_id = client.post("/v1/sos", json=_payload()).json()["id"]
    cancelled = client.post(f"/v1/sos/{alert_id}/cancel")
    assert cancelled.json() == {"status": "cancelled"}
    assert len(scheduler_recorder.dispatches) == 8

    second_id = client.post("/v1/sos", json=_payload()).json()["id"]
    resolved = client.post(f"/v1/hto/sos-alerts/{second_id}/resolve")
    assert resolved.json() == {"status": "resolved"}
    with session_factory() as session:
        assert session.get(SOSAlert, UUID(alert_id)).status == SOSStatus.CANCELLED
        assert session.get(SOSAlert, UUID(second_id)).status == SOSStatus.RESOLVED


def test_resolved_alert_cannot_then_be_cancelled(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """The cancel/resolve state machine must be mutually exclusive: once an
    HTO has resolved an alert, a pilgrim cancel attempt must be rejected,
    not silently override the resolution or fire a redundant notification
    batch."""
    _, client, _, _, scheduler_recorder = _setup(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    alert_id = client.post("/v1/sos", json=_payload()).json()["id"]
    resolved = client.post(f"/v1/hto/sos-alerts/{alert_id}/resolve")
    assert resolved.json() == {"status": "resolved"}
    scheduler_recorder.dispatches.clear()

    blocked_cancel = client.post(f"/v1/sos/{alert_id}/cancel")

    assert blocked_cancel.status_code == 409
    assert blocked_cancel.json()["error"] == "sos_already_resolved"
    assert scheduler_recorder.dispatches == []
    with session_factory() as session:
        assert session.get(SOSAlert, UUID(alert_id)).status == SOSStatus.RESOLVED


def test_cancelled_alert_cannot_then_be_resolved(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """The reverse of the above: once a pilgrim has cancelled, an HTO
    resolve attempt must be rejected, not override the cancellation."""
    _, client, _, _, scheduler_recorder = _setup(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    alert_id = client.post("/v1/sos", json=_payload()).json()["id"]
    cancelled = client.post(f"/v1/sos/{alert_id}/cancel")
    assert cancelled.json() == {"status": "cancelled"}
    scheduler_recorder.dispatches.clear()

    blocked_resolve = client.post(f"/v1/hto/sos-alerts/{alert_id}/resolve")

    assert blocked_resolve.status_code == 409
    assert blocked_resolve.json()["error"] == "sos_already_cancelled"
    assert scheduler_recorder.dispatches == []
    with session_factory() as session:
        assert session.get(SOSAlert, UUID(alert_id)).status == SOSStatus.CANCELLED


def test_cancelling_an_already_cancelled_alert_is_an_idempotent_noop(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """A duplicate cancel request (double-tap, retried request) must not
    create a second batch of cancellation notifications."""
    _, client, _, _, scheduler_recorder = _setup(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    alert_id = client.post("/v1/sos", json=_payload()).json()["id"]
    first_cancel = client.post(f"/v1/sos/{alert_id}/cancel")
    assert first_cancel.json() == {"status": "cancelled"}
    dispatch_count_after_first = len(scheduler_recorder.dispatches)

    second_cancel = client.post(f"/v1/sos/{alert_id}/cancel")

    assert second_cancel.status_code == 200
    assert second_cancel.json() == {"status": "cancelled"}
    assert len(scheduler_recorder.dispatches) == dispatch_count_after_first


def test_cancel_of_nonexistent_or_unowned_alert_is_rejected(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    _, client, _, _, _ = _setup(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    response = client.post(f"/v1/sos/{uuid4()}/cancel")
    assert response.status_code == 404
    assert response.json()["error"] == "sos_not_found"


def test_hto_token_cannot_cancel_and_pilgrim_token_cannot_resolve(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-16.5/16.6: cross-actor requests are rejected by real auth, not
    merely routed to a different service method. No dependency override is
    used here — both tokens are minted the same way the real login flows
    mint them, and presented over real HTTP to the wrong-actor endpoint."""
    import jwt

    from app.auth.tokens import TokenService

    sos_scheduler = RecordingSOSScheduler()
    sos_sender = RecordingSOSSender()
    api = create_app(
        settings=settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
        sos_scheduler=sos_scheduler,
        sos_sender=sos_sender,
    )
    user = User(
        phone_number="+2348012345678",
        first_name="Amina",
        last_name="Yusuf",
        platform=Platform.ANDROID,
    )
    organization = Organization(
        org_type=OrganizationType.HTO_OPERATOR,
        name="Barakah Hajj",
        primary_contact_name="Musa Bello",
        email="musa@example.test",
        password_hash="not-used-in-this-test",
        phone_number="+2348099999999",
        nahcon_licence_number="NAHCON-16",
        email_verified=True,
        approval_status=HTOApprovalStatus.APPROVED,
    )
    with session_factory() as session:
        session.add(user)
        session.add(organization)
        session.flush()
        manifest = Manifest(
            organization_id=organization.id,
            name="Hajj 2027",
            status=ManifestStatus.VALIDATED,
        )
        session.add(manifest)
        session.flush()
        session.add(
            ManifestPilgrim(
                manifest_id=manifest.id,
                first_name="Amina",
                last_name="Yusuf",
                phone_number=user.phone_number,
                row_number=1,
                validation_status=ManifestValidationStatus.VALID,
                user_id=user.id,
            )
        )
        pilgrim_tokens = TokenService(settings).issue(session, user, clock())
        session.commit()
        session.refresh(user)
        session.refresh(organization)
        session.expunge(user)
        session.expunge(organization)

    now = clock()
    organization_access_token = jwt.encode(
        {
            "sub": str(organization.id),
            "aud": "hto_dashboard",
            "type": "access",
            "jti": str(uuid4()),
            "iat": now,
            "exp": now.replace(year=now.year + 1),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )

    alert_id = ApiClient(api).post(
        "/v1/sos",
        json=_payload(),
        headers={"Authorization": f"Bearer {pilgrim_tokens.access_token}"},
    ).json()["id"]

    hto_tries_cancel = ApiClient(api).post(
        f"/v1/sos/{alert_id}/cancel",
        headers={"Authorization": f"Bearer {organization_access_token}"},
    )
    pilgrim_tries_resolve = ApiClient(api).post(
        f"/v1/hto/sos-alerts/{alert_id}/resolve",
        headers={"Authorization": f"Bearer {pilgrim_tokens.access_token}"},
    )

    assert hto_tries_cancel.status_code == 401
    assert hto_tries_cancel.json()["error"] == "invalid_access_token"
    assert pilgrim_tries_resolve.status_code == 401
    assert pilgrim_tries_resolve.json()["error"] == "invalid_operator_token"
    with session_factory() as session:
        assert session.get(SOSAlert, UUID(alert_id)).status == SOSStatus.ACTIVE


def test_operator_push_subscription_subscribes_to_own_org_topic(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-19.1: an operator's browser token must be tied to their own
    organization's topic, so send_topic(f"hto-{org_id}", ...) later reaches
    it — this is the server-side half of the browser push subscription
    flow that was previously entirely missing."""
    api, client, _, organization, _ = _setup(
        settings, redis_client, providers, scheduler, session_factory, clock
    )

    response = client.post(
        "/v1/hto/push-subscriptions", json={"fcm_token": "browser-token-abc"}
    )

    assert response.status_code == 204
    manager = api.state.push_subscription_service.manager
    assert manager.subscriptions == [("browser-token-abc", f"hto-{organization.id}")]


def test_push_subscription_requires_real_operator_auth_not_a_pilgrim_token(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """A pilgrim's real access token (not a dependency override — _setup()
    unconditionally overrides get_current_organization, which would make
    this check meaningless) must be rejected by this HTO-only endpoint,
    same evidence bar as the cancel/resolve actor boundary test above."""
    from app.auth.tokens import TokenService

    api = create_app(
        settings=settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
        sos_scheduler=RecordingSOSScheduler(),
        sos_sender=RecordingSOSSender(),
        push_subscription_manager=RecordingPushManager(),
    )
    user = User(
        phone_number="+2348012345679", first_name="Amina", last_name="Yusuf",
        platform=Platform.ANDROID,
    )
    with session_factory() as session:
        session.add(user)
        session.flush()
        pilgrim_tokens = TokenService(settings).issue(session, user, clock())
        session.commit()

    response = ApiClient(api).post(
        "/v1/hto/push-subscriptions",
        json={"fcm_token": "browser-token-abc"},
        headers={"Authorization": f"Bearer {pilgrim_tokens.access_token}"},
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_operator_token"


def test_push_subscription_rejects_an_empty_token(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    _, client, _, _, _ = _setup(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    response = client.post("/v1/hto/push-subscriptions", json={"fcm_token": ""})
    assert response.status_code == 422


def test_push_subscription_failure_surfaces_as_service_unavailable(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    failing_manager = RecordingPushManager()
    failing_manager.fail = True
    api, client, _, _, _ = _setup(
        settings, redis_client, providers, scheduler, session_factory, clock,
        push_manager=failing_manager,
    )

    response = client.post(
        "/v1/hto/push-subscriptions", json={"fcm_token": "browser-token-abc"}
    )

    assert response.status_code == 503
    assert response.json()["error"] == "push_subscription_failed"


def test_broker_outage_at_trigger_leaves_durable_pending_rows(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """A Celery/broker outage while scheduling the four trigger dispatches
    must not roll back the alert or the notification rows — they stay
    PENDING as the durable recovery queue, exactly as the code comment in
    SOSService._schedule claims but nothing previously verified."""
    _, client, _, _, scheduler_recorder = _setup(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    scheduler_recorder.fail_dispatch = True

    response = client.post("/v1/sos", json=_payload())

    assert response.status_code == 200
    assert scheduler_recorder.dispatches == []
    with session_factory() as session:
        alert = session.get(SOSAlert, UUID(response.json()["id"]))
        assert alert.status == SOSStatus.ACTIVE
        notifications = session.exec(
            select(SOSNotification).where(SOSNotification.sos_alert_id == alert.id)
        ).all()
        assert len(notifications) == 4
        assert all(
            row.status == SOSNotificationStatus.PENDING for row in notifications
        )


def test_hto_list_is_tenant_scoped_and_active_first(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    _, client, _, _, _ = _setup(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client.post("/v1/sos", json=_payload())
    response = client.get("/v1/hto/sos-alerts?status=active")
    assert response.status_code == 200
    assert response.json()["alerts"][0]["pilgrim_name"] == "Amina Yusuf"
    assert response.json()["alerts"][0]["pilgrim_phone"] == "+2348012345678"


def test_notification_failure_enters_admin_queue_without_changing_alert(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """Required chaos case: three delivery failures never roll back the SOS."""
    api, client, _, _, recorder = _setup(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    alert_id = UUID(client.post("/v1/sos", json=_payload()).json()["id"])
    notification_id = recorder.dispatches[0][0]
    service = api.state.sos_notification_service
    service.sender.fail = True
    with session_factory() as session:
        assert service.dispatch(session, notification_id) is False
        assert service.dispatch(session, notification_id) is False
        assert service.dispatch(session, notification_id) is False
        notification = session.get(SOSNotification, notification_id)
        assert notification.status == SOSNotificationStatus.FAILED
        assert notification.admin_queued_at is not None
        assert session.get(SOSAlert, alert_id).status == SOSStatus.ACTIVE


def test_channels_fail_and_recover_independently_within_one_trigger(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-16.3: a WhatsApp-only outage must not touch push/email/the other
    WhatsApp leg's rows, and the alert itself stays untouched throughout —
    the check-in equivalent only had one channel, SOS has four that must
    fail and recover independently of each other."""
    api, client, _, _, _ = _setup(
        settings, redis_client, providers, scheduler, session_factory, clock,
        sender=ChannelSelectiveSOSSender(SOSNotificationChannel.WHATSAPP_FAMILY),
    )
    alert_id = UUID(client.post("/v1/sos", json=_payload()).json()["id"])
    service = api.state.sos_notification_service
    with session_factory() as session:
        rows = {
            row.channel: row
            for row in session.exec(
                select(SOSNotification).where(SOSNotification.sos_alert_id == alert_id)
            ).all()
        }
        for row in rows.values():
            service.dispatch(session, row.id)
        session.commit()

    with session_factory() as session:
        rows = {
            row.channel: row
            for row in session.exec(
                select(SOSNotification).where(SOSNotification.sos_alert_id == alert_id)
            ).all()
        }
        assert rows[SOSNotificationChannel.PUSH].status == SOSNotificationStatus.SENT
        assert rows[SOSNotificationChannel.EMAIL].status == SOSNotificationStatus.SENT
        assert (
            rows[SOSNotificationChannel.WHATSAPP_OPERATOR].status
            == SOSNotificationStatus.SENT
        )
        assert (
            rows[SOSNotificationChannel.WHATSAPP_FAMILY].status
            == SOSNotificationStatus.FAILED
        )
        assert rows[SOSNotificationChannel.WHATSAPP_FAMILY].retry_count == 1
        assert rows[SOSNotificationChannel.WHATSAPP_FAMILY].admin_queued_at is None
        assert session.get(SOSAlert, alert_id).status == SOSStatus.ACTIVE


def _whatsapp_family_row(session_factory, alert_id):
    with session_factory() as session:
        return session.exec(
            select(SOSNotification).where(
                SOSNotification.sos_alert_id == UUID(alert_id),
                SOSNotification.channel == SOSNotificationChannel.WHATSAPP_FAMILY,
            )
        ).one()


def test_sos_sms_fallback_fires_at_sixty_seconds_not_before(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-22.3: same 59s/60s controlled-clock evidence bar as US-15's
    check-in fallback -- not immediate, not indefinitely late."""
    api, client, _, organization, sos_scheduler = _setup(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    alert_id = client.post("/v1/sos", json=_payload()).json()["id"]
    service = api.state.sos_notification_service
    family_row = _whatsapp_family_row(session_factory, alert_id)
    with session_factory() as session:
        assert service.dispatch(session, family_row.id) is True
    assert (family_row.id, 60) in [
        (fid, secs) for fid, secs in sos_scheduler.fallbacks
    ]

    clock.advance(seconds=59)
    with session_factory() as session:
        assert service.send_sms_fallback(session, family_row.id) is False
    with session_factory() as session:
        assert (
            session.exec(
                select(SOSNotification).where(
                    SOSNotification.sos_alert_id == UUID(alert_id),
                    SOSNotification.channel == SOSNotificationChannel.SMS_FAMILY,
                )
            ).first()
            is None
        )

    clock.advance(seconds=1)
    with session_factory() as session:
        assert service.send_sms_fallback(session, family_row.id) is True
    with session_factory() as session:
        sms_row = session.exec(
            select(SOSNotification).where(
                SOSNotification.sos_alert_id == UUID(alert_id),
                SOSNotification.channel == SOSNotificationChannel.SMS_FAMILY,
            )
        ).one()
        assert sms_row.status == SOSNotificationStatus.SENT
        assert sms_row.event == SOSNotificationEvent.TRIGGERED


def test_confirmed_whatsapp_delivery_cancels_sos_sms_fallback(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-22.3: a delivery confirmation before 60s prevents a duplicate SMS,
    mirroring US-15's exact confirm-suppresses-fallback behavior."""
    api, client, _, organization, _ = _setup(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    alert_id = client.post("/v1/sos", json=_payload()).json()["id"]
    service = api.state.sos_notification_service
    family_row = _whatsapp_family_row(session_factory, alert_id)
    with session_factory() as session:
        service.dispatch(session, family_row.id)
        assert service.confirm_whatsapp_delivery(session, "wamid.sos.1") is True
    clock.advance(seconds=60)

    with session_factory() as session:
        assert service.send_sms_fallback(session, family_row.id) is False
    with session_factory() as session:
        assert (
            session.exec(
                select(SOSNotification).where(
                    SOSNotification.sos_alert_id == UUID(alert_id),
                    SOSNotification.channel == SOSNotificationChannel.SMS_FAMILY,
                )
            ).first()
            is None
        )


def test_failed_whatsapp_family_send_makes_fallback_immediately_eligible(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-22.3 says "fails or does not confirm" -- an outright send failure
    must not still wait out the full 60s window."""
    api, client, _, organization, sos_scheduler = _setup(
        settings, redis_client, providers, scheduler, session_factory, clock,
        sender=ChannelSelectiveSOSSender(SOSNotificationChannel.WHATSAPP_FAMILY),
    )
    alert_id = client.post("/v1/sos", json=_payload()).json()["id"]
    service = api.state.sos_notification_service
    family_row = _whatsapp_family_row(session_factory, alert_id)
    with session_factory() as session:
        assert service.dispatch(session, family_row.id) is False

    assert (family_row.id, 0) in [(fid, secs) for fid, secs in sos_scheduler.fallbacks]
    with session_factory() as session:
        # Due immediately (clock hasn't even advanced), not 60s from now.
        assert service.send_sms_fallback(session, family_row.id) is True


def test_signed_meta_webhook_confirms_sos_whatsapp_delivery(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """The shared Meta webhook (already proven for check-in) also resolves
    SOS family WhatsApp delivery -- one signed endpoint, two tables."""
    import hashlib
    import hmac
    import json

    signed_settings = settings.model_copy(
        update={"whatsapp_app_secret": "meta-app-secret"}
    )
    api, client, _, organization, _ = _setup(
        signed_settings, redis_client, providers, scheduler, session_factory, clock
    )
    alert_id = client.post("/v1/sos", json=_payload()).json()["id"]
    service = api.state.sos_notification_service
    family_row = _whatsapp_family_row(session_factory, alert_id)
    with session_factory() as session:
        service.dispatch(session, family_row.id)

    body = json.dumps(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {"id": "wamid.sos.1", "status": "delivered"}
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

    response = client.post(
        "/v1/webhooks/meta/whatsapp",
        content=body,
        headers={
            "x-hub-signature-256": signature,
            "content-type": "application/json",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"processed": 1}
    with session_factory() as session:
        row = session.get(SOSNotification, family_row.id)
        assert row.whatsapp_delivered_at is not None


def test_due_sos_fallback_query_excludes_delivered_and_already_fallen_back(
    session_factory,
) -> None:
    """The Celery Beat sweep's query must skip rows that were delivered in
    time and rows that already have an SMS_FAMILY sibling -- otherwise it
    would re-trigger send_sms_fallback forever."""
    from app.sos.notifications import due_sos_fallback_notifications_query

    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    with session_factory() as session:
        alert = SOSAlert(
            user_id=uuid4(), client_generated_id=uuid4(), timestamp=now
        )
        delivered_alert = SOSAlert(
            user_id=uuid4(), client_generated_id=uuid4(), timestamp=now
        )
        already_fell_back_alert = SOSAlert(
            user_id=uuid4(), client_generated_id=uuid4(), timestamp=now
        )
        session.add_all([alert, delivered_alert, already_fell_back_alert])
        session.flush()

        due_row = SOSNotification(
            sos_alert_id=alert.id,
            channel=SOSNotificationChannel.WHATSAPP_FAMILY,
            status=SOSNotificationStatus.SENT,
            fallback_due_at=now - timedelta(seconds=1),
        )
        not_yet_due_row = SOSNotification(
            sos_alert_id=alert.id,
            channel=SOSNotificationChannel.WHATSAPP_OPERATOR,
            status=SOSNotificationStatus.SENT,
        )
        delivered_row = SOSNotification(
            sos_alert_id=delivered_alert.id,
            channel=SOSNotificationChannel.WHATSAPP_FAMILY,
            status=SOSNotificationStatus.SENT,
            fallback_due_at=now - timedelta(seconds=1),
            whatsapp_delivered_at=now,
        )
        already_fell_back_row = SOSNotification(
            sos_alert_id=already_fell_back_alert.id,
            channel=SOSNotificationChannel.WHATSAPP_FAMILY,
            status=SOSNotificationStatus.SENT,
            fallback_due_at=now - timedelta(seconds=1),
        )
        sibling_sms_row = SOSNotification(
            sos_alert_id=already_fell_back_alert.id,
            channel=SOSNotificationChannel.SMS_FAMILY,
            status=SOSNotificationStatus.SENT,
        )
        session.add_all(
            [
                due_row,
                not_yet_due_row,
                delivered_row,
                already_fell_back_row,
                sibling_sms_row,
            ]
        )
        session.commit()

        eligible_ids = {
            row.id
            for row in session.exec(due_sos_fallback_notifications_query(now)).all()
        }
        due_row_id = due_row.id
        not_yet_due_row_id = not_yet_due_row.id
        delivered_row_id = delivered_row.id
        already_fell_back_row_id = already_fell_back_row.id

    assert due_row_id in eligible_ids
    assert not_yet_due_row_id not in eligible_ids
    assert delivered_row_id not in eligible_ids
    assert already_fell_back_row_id not in eligible_ids


def test_resolving_mid_retry_stops_the_failed_channel_from_notifying_again(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-19.6: a channel that failed and is still eligible for retry must
    not fire once the operator has resolved the alert — the exact gap
    review found in SOSNotificationService.dispatch(), which previously had
    no idea the parent alert had moved on."""
    api, client, _, organization, _ = _setup(
        settings, redis_client, providers, scheduler, session_factory, clock,
        sender=ChannelSelectiveSOSSender(SOSNotificationChannel.WHATSAPP_FAMILY),
    )
    alert_id = UUID(client.post("/v1/sos", json=_payload()).json()["id"])
    service = api.state.sos_notification_service
    with session_factory() as session:
        failing_row = session.exec(
            select(SOSNotification).where(
                SOSNotification.sos_alert_id == alert_id,
                SOSNotification.channel == SOSNotificationChannel.WHATSAPP_FAMILY,
            )
        ).one()
        # First attempt fails (retry_count -> 1), well under the 3-attempt
        # admin-queue threshold, so the recovery sweep would normally still
        # consider this row eligible for another try.
        assert service.dispatch(session, failing_row.id) is False
        session.commit()
        failing_id = failing_row.id

    with session_factory() as session:
        sos_service = api.state.sos_service
        sos_service.resolve(session, organization, alert_id)

    sender = service.sender
    sent_before_retry = len(sender.sent)
    with session_factory() as session:
        # This is exactly what the 10s Celery Beat sweep would have done:
        # re-attempt the still-PENDING/FAILED, under-the-cap row.
        retried = service.dispatch(session, failing_id)

    assert retried is False
    assert len(sender.sent) == sent_before_retry  # no send attempt was made
    with session_factory() as session:
        row = session.get(SOSNotification, failing_id)
        assert row.status == SOSNotificationStatus.FAILED
        assert row.retry_count == 1  # unchanged: this was a skip, not an attempt
        assert row.admin_queued_at is None
        assert session.get(SOSAlert, alert_id).status == SOSStatus.RESOLVED


def test_pending_dispatchable_notifications_query_excludes_resolved_alerts(
    session_factory,
) -> None:
    """The Celery Beat recovery sweep (app.sos.enqueue_pending) must not
    re-surface a TRIGGERED-event row belonging to a resolved or cancelled
    alert, even though the row itself is still PENDING/FAILED and under
    the retry cap. Tests the extracted query directly since the Celery
    task itself uses a fresh create_session_factory(settings) disconnected
    from this fixture's engine, matching this codebase's existing
    convention of not unit-testing worker.py's Celery task wrappers."""
    from app.sos.notifications import pending_dispatchable_notifications_query

    with session_factory() as session:
        active_alert = SOSAlert(
            user_id=uuid4(),
            client_generated_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
        )
        resolved_alert = SOSAlert(
            user_id=uuid4(),
            client_generated_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            status=SOSStatus.RESOLVED,
        )
        cancelled_alert = SOSAlert(
            user_id=uuid4(),
            client_generated_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            status=SOSStatus.CANCELLED,
        )
        session.add_all([active_alert, resolved_alert, cancelled_alert])
        session.flush()

        active_triggered = SOSNotification(
            sos_alert_id=active_alert.id, channel=SOSNotificationChannel.EMAIL
        )
        resolved_triggered = SOSNotification(
            sos_alert_id=resolved_alert.id, channel=SOSNotificationChannel.EMAIL
        )
        cancelled_triggered = SOSNotification(
            sos_alert_id=cancelled_alert.id, channel=SOSNotificationChannel.EMAIL
        )
        # A legitimate cancellation-event row: its alert is CANCELLED, which
        # is expected and must not be excluded.
        cancelled_event = SOSNotification(
            sos_alert_id=cancelled_alert.id,
            channel=SOSNotificationChannel.WHATSAPP_FAMILY,
            event=SOSNotificationEvent.CANCELLED,
        )
        session.add_all(
            [active_triggered, resolved_triggered, cancelled_triggered, cancelled_event]
        )
        session.commit()

        eligible_ids = {
            row.id
            for row in session.exec(pending_dispatchable_notifications_query()).all()
        }
        active_triggered_id = active_triggered.id
        cancelled_event_id = cancelled_event.id
        resolved_triggered_id = resolved_triggered.id
        cancelled_triggered_id = cancelled_triggered.id

    assert active_triggered_id in eligible_ids
    assert cancelled_event_id in eligible_ids
    assert resolved_triggered_id not in eligible_ids
    assert cancelled_triggered_id not in eligible_ids


def test_admin_retry_only_requeues_failed_admin_queued_notifications(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """Review hardening: stale SENT IDs must never duplicate an SOS delivery."""
    api, client, _, _, recorder = _setup(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client.post("/v1/sos", json=_payload())
    with session_factory() as session:
        rows = session.exec(select(SOSNotification)).all()
        failed, sent = rows[:2]
        failed.status = SOSNotificationStatus.FAILED
        failed.admin_queued_at = datetime.now(timezone.utc)
        failed.retry_count = 3
        sent.status = SOSNotificationStatus.SENT
        session.add(failed)
        session.add(sent)
        session.commit()
        failed_id, sent_id = failed.id, sent.id

    recorder.dispatches.clear()
    queued = _retry_sos_rows(
        SimpleNamespace(app=api),  # type: ignore[arg-type]
        [failed_id, sent_id],
    )

    assert queued == 1
    assert [item[0] for item in recorder.dispatches] == [failed_id]
    with session_factory() as session:
        failed_row = session.get(SOSNotification, failed_id)
        sent_row = session.get(SOSNotification, sent_id)
        assert failed_row.status == SOSNotificationStatus.PENDING
        assert sent_row.status == SOSNotificationStatus.SENT
