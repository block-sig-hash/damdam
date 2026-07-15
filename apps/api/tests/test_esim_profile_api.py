from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient
from sqlmodel import select

from app.auth.models import PricingTier, User
from app.auth.routes import request_otp, verify_otp
from app.auth.schemas import OTPRequest, OTPVerifyRequest
from app.esim.models import (
    DeviceCompatibilityLog,
    EsimAggregator,
    EsimIssuanceJob,
    EsimProfile,
    EsimProfileStatus,
)
from app.esim.providers import (
    EsimIssuedProfile,
    EsimIssueRequest,
    EsimProviderError,
    EsimProviderPending,
)
from app.main import create_app
from app.notifications.service import NotificationError
from app.packages.models import Package, PackageSource, PackageStatus


class FakeEsimProvider:
    def __init__(self, name: str, *, failing: bool = False) -> None:
        self.name = name
        self.failing = failing
        self.calls: list[EsimIssueRequest] = []

    def issue(self, request: EsimIssueRequest) -> EsimIssuedProfile:
        self.calls.append(request)
        if self.failing:
            raise EsimProviderError(f"{self.name} unavailable")
        return EsimIssuedProfile(
            iccid=f"894450{len(self.calls):016d}",
            activation_code_lpa=f"LPA:1${self.name}.example$MATCH-{request.package_id}",
            qr_code_url=f"https://cdn.example/{request.package_id}.png",
        )


class PendingEsimProvider(FakeEsimProvider):
    def issue(self, request: EsimIssueRequest) -> EsimIssuedProfile:
        self.calls.append(request)
        raise EsimProviderPending(f"{self.name} allocation pending")


class FakeEsimScheduler:
    def __init__(self, *, failing: bool = False) -> None:
        self.calls: list[tuple[UUID, int]] = []
        self.failing = failing

    def schedule(self, package_id: UUID, countdown: int) -> None:
        self.calls.append((package_id, countdown))
        if self.failing:
            raise RuntimeError("broker unavailable")


@dataclass
class FakeNotificationSender:
    success_calls: list[tuple[str, str]]
    failing: bool = False

    def send_esim_ready(self, phone_number: str, qr_code_url: str) -> None:
        self.success_calls.append((phone_number, qr_code_url))
        if self.failing:
            raise NotificationError("WhatsApp unavailable")

    def __getattr__(self, name: str):
        del name
        return lambda *args, **kwargs: None


def _client_and_package(
    settings,
    redis_client,
    providers,
    scheduler,
    session_factory,
    clock,
    esim_providers: dict[str, FakeEsimProvider],
    esim_scheduler: FakeEsimScheduler,
    phone: str = "08055550000",
    notifications: FakeNotificationSender | None = None,
) -> tuple[TestClient, UUID, UUID, FakeNotificationSender]:
    notifications = notifications or FakeNotificationSender([])
    api = create_app(
        settings=settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
        whatsapp_sender=notifications,
        esim_providers=esim_providers,
        esim_scheduler=esim_scheduler,
    )
    request = SimpleNamespace(app=api)
    request_otp(OTPRequest(phone_number=phone), request)
    auth = verify_otp(
        OTPVerifyRequest(phone_number=phone, otp="123456", platform="android"),
        request,
    )
    with session_factory() as session:
        tier = PricingTier(
            name="Basic",
            usd_reference_price=30,
            wholesale_usd_price=25,
            ngn_price=45000,
            data_gb=5,
            pstn_minutes=30,
        )
        session.add(tier)
        session.flush()
        package = Package(
            user_id=auth.user.id,
            pricing_tier_id=tier.id,
            source=PackageSource.RETAIL,
            status=PackageStatus.ACTIVE,
            data_gb_total=5,
            data_gb_remaining=5,
            pstn_minutes_total=30,
            pstn_minutes_remaining=30,
        )
        session.add(package)
        session.commit()
        package_id = package.id
    client = TestClient(
        api,
        headers={"Authorization": f"Bearer {auth.access_token}"},
        raise_server_exceptions=False,
    )
    return client, auth.user.id, package_id, notifications


def test_issue_cascades_vendors_and_logs_every_attempt(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-11.2: issuance cascades through configured vendors and logs each one."""
    settings.esim_vendor_primary = "monty_mobile"
    settings.esim_vendor_secondary = "esim_access"
    settings.esim_vendor_tertiary = "1global"
    vendors = {
        "monty_mobile": FakeEsimProvider("monty_mobile", failing=True),
        "esim_access": FakeEsimProvider("esim_access", failing=True),
        "1global": FakeEsimProvider("1global"),
    }
    client, user_id, package_id, notifications = _client_and_package(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        vendors,
        FakeEsimScheduler(),
    )

    response = client.post(f"/v1/packages/{package_id}/esim/issue")

    assert response.status_code == 200
    assert response.json()["status"] == "issued"
    assert response.json()["activation_code_lpa"].startswith("LPA:1$1global")
    with session_factory() as session:
        profile = session.exec(select(EsimProfile)).one()
        assert profile.aggregator == EsimAggregator.ONEGLOBAL
        attempts = session.exec(
            select(DeviceCompatibilityLog).where(
                DeviceCompatibilityLog.event_type == "issuance_attempt"
            )
        ).all()
        results = {
            attempt.aggregator.value: attempt.attempt_succeeded
            for attempt in attempts
            if attempt.aggregator is not None
        }
        assert results == {
            "monty_mobile": False,
            "esim_access": False,
            "1global": True,
        }
        assert all(attempt.user_id == user_id for attempt in attempts)
    assert all(len(vendor.calls) == 1 for vendor in vendors.values())
    assert notifications.success_calls == [
        ("+2348055550000", f"https://cdn.example/{package_id}.png")
    ]


def test_issue_is_idempotent_and_returns_existing_profile(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-11.4: repeated issue calls produce one vendor issue and one profile row."""
    vendor = FakeEsimProvider("monty_mobile")
    vendors = {
        "monty_mobile": vendor,
        "esim_access": FakeEsimProvider("esim_access"),
        "1global": FakeEsimProvider("1global"),
    }
    client, _, package_id, notifications = _client_and_package(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        vendors,
        FakeEsimScheduler(),
    )

    first = client.post(f"/v1/packages/{package_id}/esim/issue")
    second = client.post(f"/v1/packages/{package_id}/esim/issue")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(vendor.calls) == 1
    assert len(notifications.success_calls) == 1
    with session_factory() as session:
        assert len(session.exec(select(EsimProfile)).all()) == 1


def test_esim_endpoints_reject_another_users_package(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """Pilgrim eSIM operations must not expose or mutate another user's package."""
    vendors = {
        name: FakeEsimProvider(name)
        for name in ("monty_mobile", "esim_access", "1global")
    }
    owner_client, owner_id, package_id, _ = _client_and_package(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        vendors,
        FakeEsimScheduler(),
    )
    with session_factory() as session:
        other_user = User(phone_number="+2348055550001", platform="android")
        session.add(other_user)
        package = session.get(Package, package_id)
        assert package is not None
        package.user_id = other_user.id
        session.commit()
        other_user_id = other_user.id

    issue = owner_client.post(f"/v1/packages/{package_id}/esim/issue")
    assert issue.status_code == 404
    assert issue.json()["error"] == "package_not_found"
    assert all(vendor.calls == [] for vendor in vendors.values())

    with session_factory() as session:
        package = session.get(Package, package_id)
        assert package is not None
        package.user_id = owner_id
        session.add(package)
        session.commit()
    assert owner_client.post(f"/v1/packages/{package_id}/esim/issue").status_code == 200
    with session_factory() as session:
        package = session.get(Package, package_id)
        assert package is not None
        package.user_id = other_user_id
        session.add(package)
        session.commit()
    fetched = owner_client.get(f"/v1/packages/{package_id}/esim")
    marked = owner_client.post(f"/v1/packages/{package_id}/esim/mark-downloaded")

    assert fetched.status_code == marked.status_code == 404
    assert fetched.json()["error"] == "package_not_found"
    assert marked.json()["error"] == "package_not_found"
    with session_factory() as session:
        stored = session.exec(select(EsimProfile)).one()
        assert stored.status == EsimProfileStatus.ISSUED


def test_issue_follows_configured_vendor_order_not_hardcoded_order(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """§5.4: primary/secondary/tertiary routing is deployment configuration."""
    settings.esim_vendor_primary = "esim_access"
    settings.esim_vendor_secondary = "1global"
    settings.esim_vendor_tertiary = "monty_mobile"
    vendors = {
        "esim_access": FakeEsimProvider("esim_access", failing=True),
        "1global": FakeEsimProvider("1global"),
        "monty_mobile": FakeEsimProvider("monty_mobile"),
    }
    client, _, package_id, _ = _client_and_package(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        vendors,
        FakeEsimScheduler(),
    )

    response = client.post(f"/v1/packages/{package_id}/esim/issue")

    assert response.status_code == 200
    assert response.json()["activation_code_lpa"].startswith("LPA:1$1global")
    assert len(vendors["esim_access"].calls) == 1
    assert len(vendors["1global"].calls) == 1
    assert vendors["monty_mobile"].calls == []


def test_accepted_pending_order_does_not_cascade_and_buy_duplicate(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """§5.4: a slow accepted allocation is retried, not treated as failure."""
    primary = PendingEsimProvider("monty_mobile")
    secondary = FakeEsimProvider("esim_access")
    retry_scheduler = FakeEsimScheduler()
    client, _, package_id, _ = _client_and_package(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        {
            "monty_mobile": primary,
            "esim_access": secondary,
            "1global": FakeEsimProvider("1global"),
        },
        retry_scheduler,
    )

    response = client.post(f"/v1/packages/{package_id}/esim/issue")

    assert response.status_code == 502
    assert len(primary.calls) == 1
    assert secondary.calls == []
    assert retry_scheduler.calls == [(package_id, 60)]


def test_all_vendors_fail_persists_retry_then_admin_queues_after_three_attempts(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-11.5: all-vendor failures back off and enter admin queue after attempt 3."""
    vendors = {
        name: FakeEsimProvider(name, failing=True)
        for name in ("monty_mobile", "esim_access", "1global")
    }
    retry_scheduler = FakeEsimScheduler()
    client, _, package_id, _ = _client_and_package(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        vendors,
        retry_scheduler,
    )

    for expected_attempt in (1, 2, 3):
        response = client.post(f"/v1/packages/{package_id}/esim/issue")
        assert response.status_code == 502
        with session_factory() as session:
            job = session.exec(select(EsimIssuanceJob)).one()
            assert job.attempt_count == expected_attempt
            assert (job.admin_queued_at is not None) is (expected_attempt == 3)

    assert retry_scheduler.calls == [(package_id, 60), (package_id, 300)]


def test_get_and_mark_downloaded_are_owned_and_idempotent(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-11.3/11.4: QR fallback is returned and marking downloaded is repeat-safe."""
    vendors = {
        name: FakeEsimProvider(name)
        for name in ("monty_mobile", "esim_access", "1global")
    }
    client, _, package_id, _ = _client_and_package(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        vendors,
        FakeEsimScheduler(),
    )
    client.post(f"/v1/packages/{package_id}/esim/issue")

    fetched = client.get(f"/v1/packages/{package_id}/esim")
    first = client.post(f"/v1/packages/{package_id}/esim/mark-downloaded")
    with session_factory() as session:
        first_downloaded_at = session.exec(select(EsimProfile)).one().downloaded_at
    second = client.post(f"/v1/packages/{package_id}/esim/mark-downloaded")

    assert fetched.status_code == 200
    assert fetched.json()["qr_code_url"].endswith(".png")
    assert "activation_code_lpa" not in fetched.json()
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {"status": "downloaded"}
    with session_factory() as session:
        stored = session.exec(select(EsimProfile)).one()
        assert stored.status == EsimProfileStatus.DOWNLOADED
        assert stored.downloaded_at == first_downloaded_at


def test_get_and_mark_downloaded_require_an_issued_profile(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """GET/mark failure contract: an active package without a profile is 404."""
    vendors = {
        name: FakeEsimProvider(name)
        for name in ("monty_mobile", "esim_access", "1global")
    }
    client, _, package_id, _ = _client_and_package(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        vendors,
        FakeEsimScheduler(),
    )

    fetched = client.get(f"/v1/packages/{package_id}/esim")
    marked = client.post(f"/v1/packages/{package_id}/esim/mark-downloaded")

    assert fetched.status_code == marked.status_code == 404
    assert fetched.json()["error"] == "esim_profile_not_found"
    assert marked.json()["error"] == "esim_profile_not_found"


def test_broker_failure_keeps_due_job_without_masking_aggregator_error(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-11.5: broker downtime leaves durable retry work and still returns 502."""
    vendors = {
        name: FakeEsimProvider(name, failing=True)
        for name in ("monty_mobile", "esim_access", "1global")
    }
    client, _, package_id, _ = _client_and_package(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        vendors,
        FakeEsimScheduler(failing=True),
    )

    response = client.post(f"/v1/packages/{package_id}/esim/issue")

    assert response.status_code == 502
    with session_factory() as session:
        job = session.exec(select(EsimIssuanceJob)).one()
        assert job.attempt_count == 1
        assert job.next_attempt_at is not None


def test_notification_failure_retries_without_reissuing_profile(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-11.5: success notification retries without another vendor issue."""
    vendor = FakeEsimProvider("monty_mobile")
    notifications = FakeNotificationSender([], failing=True)
    client, _, package_id, _ = _client_and_package(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        {
            "monty_mobile": vendor,
            "esim_access": FakeEsimProvider("esim_access"),
            "1global": FakeEsimProvider("1global"),
        },
        FakeEsimScheduler(),
        notifications=notifications,
    )

    first = client.post(f"/v1/packages/{package_id}/esim/issue")
    notifications.failing = False
    second = client.post(f"/v1/packages/{package_id}/esim/issue")

    assert first.status_code == second.status_code == 200
    assert len(vendor.calls) == 1
    assert notifications.success_calls == [
        ("+2348055550000", f"https://cdn.example/{package_id}.png"),
        ("+2348055550000", f"https://cdn.example/{package_id}.png"),
    ]
    with session_factory() as session:
        job = session.exec(select(EsimIssuanceJob)).one()
        assert job.success_notified_at is not None
        assert job.next_attempt_at is None
