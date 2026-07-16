"""US-16 executable acceptance tests, committed before implementation."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
from sqlmodel import select

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
from app.sos.models import SOSAlert, SOSNotification, SOSNotificationChannel, SOSStatus


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

    def schedule_dispatch(self, notification_id, channel) -> None:
        self.dispatches.append((notification_id, channel))


def _setup(
    settings, redis_client, providers, scheduler, session_factory, clock
):
    sos_scheduler = RecordingSOSScheduler()
    api = create_app(
        settings=settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
        sos_scheduler=sos_scheduler,
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
                relationship="daughter",
                opted_in=True,
                confirmed_at=clock(),
            )
        )
        session.commit()
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
    """AC-16.3: durable alert + four channel queue rows precede dispatch."""
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
        assert {row.channel for row in notifications} == set(SOSNotificationChannel)
        assert len(sos_scheduler.dispatches) == 4


def test_same_client_id_is_idempotent_and_has_no_rate_limit_for_distinct_ids(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-16.7: retries collapse, while distinct deliberate SOS events remain allowed."""
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
        assert session.get(SOSAlert, alert_id).status == SOSStatus.CANCELLED
        assert session.get(SOSAlert, second_id).status == SOSStatus.RESOLVED


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

