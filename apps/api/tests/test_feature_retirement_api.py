"""US-30 / AC-30.1-30.3 -- retired features answer explicitly, never silently.

Chunk 04B disables enrollment and dispatch for the features the product reset
retires. The dangerous failure is not a missing endpoint; it is an endpoint that
keeps accepting a check-in or an SOS alert and reports success to a client whose
alert nobody will ever act on. Every test here asserts the explicit refusal and
that nothing was persisted or dispatched behind it.
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
from sqlmodel import select

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.auth.routes import request_otp, verify_otp
from app.auth.schemas import OTPRequest, OTPVerifyRequest
from app.checkins.models import CheckIn
from app.main import create_app
from app.profile.models import FamilyContact
from app.sos.models import SOSAlert

RETIRED = "feature_retired"


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

    def patch(self, path: str, **kwargs) -> httpx.Response:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs) -> httpx.Response:
        return self.request("DELETE", path, **kwargs)


def _build_api(settings, redis_client, providers, scheduler, session_factory, clock):
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
    )


def _authenticated(api) -> tuple[ApiClient, UUID]:
    request = SimpleNamespace(app=api)
    request_otp(OTPRequest(phone_number="08012345678"), request)
    auth = verify_otp(
        OTPVerifyRequest(phone_number="08012345678", otp="123456", platform="android"),
        request,
    )

    async def current_user_override():
        return auth.user

    api.dependency_overrides[get_current_user] = current_user_override
    return (
        ApiClient(api, headers={"Authorization": f"Bearer {auth.access_token}"}),
        auth.user.id,
    )


def _assert_retired(response: httpx.Response, feature: str) -> None:
    assert response.status_code == 410, response.text
    body = response.json()
    assert body["error"] == RETIRED
    assert body["details"]["feature"] == feature
    assert body["details"]["upgrade_required"] is True
    assert body["message"]


# --- check-ins -------------------------------------------------------------


def test_checkin_creation_is_refused_and_records_nothing(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-30.1: an old client must not be told its check-in was received."""
    api = _build_api(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, _ = _authenticated(api)

    response = client.post(
        "/v1/checkins",
        json={
            "client_generated_id": str(uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "latitude": 21.42,
            "longitude": 39.82,
        },
    )

    _assert_retired(response, "checkins")
    with session_factory() as session:
        assert session.exec(select(CheckIn)).all() == []


def test_checkin_history_is_refused(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    api = _build_api(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, _ = _authenticated(api)
    _assert_retired(client.get("/v1/me/checkins"), "checkins")


def test_meta_whatsapp_webhook_is_refused(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """The webhook existed only to confirm retired family notifications."""
    api = _build_api(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client = ApiClient(api, headers={})

    _assert_retired(
        client.get(
            "/v1/webhooks/meta/whatsapp"
            "?hub.mode=subscribe&hub.verify_token=meta-verify-token&hub.challenge=x"
        ),
        "checkins",
    )
    _assert_retired(client.post("/v1/webhooks/meta/whatsapp", json={}), "checkins")


# --- SOS -------------------------------------------------------------------


def test_sos_creation_is_refused_and_raises_no_alert(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-30.1: the worst silent success in the product. Never accept an alert."""
    api = _build_api(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, _ = _authenticated(api)

    response = client.post(
        "/v1/sos",
        json={
            "client_generated_id": str(uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "latitude": 21.42,
            "longitude": 39.82,
        },
    )

    _assert_retired(response, "sos")
    with session_factory() as session:
        assert session.exec(select(SOSAlert)).all() == []


def test_sos_cancel_is_refused(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    api = _build_api(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, _ = _authenticated(api)
    _assert_retired(client.post(f"/v1/sos/{uuid4()}/cancel"), "sos")


def test_operator_sos_surfaces_are_refused(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """Retiring SOS must also close the operator side, not just the app side."""
    api = _build_api(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client = ApiClient(api, headers={})

    _assert_retired(client.get("/v1/hto/sos-alerts"), "sos")
    _assert_retired(client.post(f"/v1/hto/sos-alerts/{uuid4()}/resolve"), "sos")
    _assert_retired(
        client.post("/v1/hto/push-subscriptions", json={"fcm_token": "t"}), "sos"
    )


def test_admin_sos_retry_queue_is_refused(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-30.3: no operator path may put a retired notification back on a queue."""
    api = _build_api(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client = ApiClient(api, headers={})

    _assert_retired(client.get("/v1/admin/sos-notifications/failed"), "sos")
    _assert_retired(
        client.post(
            "/v1/admin/sos-notifications/retry-bulk",
            json={"notification_ids": [str(uuid4())]},
        ),
        "sos",
    )
    _assert_retired(
        client.post(f"/v1/admin/sos-notifications/{uuid4()}/retry"), "sos"
    )


# --- family and emergency contacts ----------------------------------------


def test_family_contact_enrollment_is_refused(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    api = _build_api(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, _ = _authenticated(api)
    payload = {"name": "Amina", "phone_number": "08087654321", "relationship": "sister"}

    _assert_retired(
        client.post("/v1/me/family-contact", json=payload), "family_contacts"
    )
    _assert_retired(
        client.patch("/v1/me/family-contact", json=payload), "family_contacts"
    )

    with session_factory() as session:
        assert session.exec(select(FamilyContact)).all() == []


def test_emergency_contact_read_is_refused(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    api = _build_api(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, _ = _authenticated(api)
    _assert_retired(client.get("/v1/me/emergency-contact"), "emergency_contact")


def test_arrival_geofence_lookup_is_refused(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """Arrival geofencing retires with the Hajj framing; the table is kept."""
    api = _build_api(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, _ = _authenticated(api)
    _assert_retired(
        client.get(f"/v1/packages/{uuid4()}/geofence"), "arrival_geofence"
    )


def test_operator_roster_reports_no_welfare_state(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """SCOPE-DISPOSITION: welfare tracking must not survive in the dashboard.

    The roster used to tell an operator when each traveler last checked in and
    whether they had an active SOS alert. Removing the screens is not enough --
    the projection itself is the tracking, so it must not be served at all.
    """
    from app.esim.schemas import HtoPilgrimSummary

    assert "last_checkin_at" not in HtoPilgrimSummary.model_fields
    assert "sos_status" not in HtoPilgrimSummary.model_fields


# --- shape of the refusal --------------------------------------------------


def test_retired_refusal_is_localized(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """The app ships English and French; a retirement notice is user-facing."""
    api = _build_api(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, _ = _authenticated(api)

    english = client.get("/v1/me/checkins").json()["message"]
    french = client.get("/v1/me/checkins", headers={"Accept-Language": "fr"}).json()[
        "message"
    ]

    assert english != french
    assert french


# --- what must survive the retirement -------------------------------------


def test_retained_surfaces_still_work(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-30.6: login, health and account deletion are not collateral damage."""
    api = _build_api(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)

    assert client.get("/health").status_code == 200
    assert client.delete("/v1/me/account").status_code == 202

    with session_factory() as session:
        assert session.get(User, user_id) is not None
