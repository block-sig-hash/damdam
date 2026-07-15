from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient
from sqlmodel import select

from app.auth.models import PricingTier
from app.auth.routes import request_otp, verify_otp
from app.auth.schemas import OTPRequest, OTPVerifyRequest
from app.esim.models import EsimAggregator, EsimProfile, EsimProfileStatus
from app.main import create_app
from app.packages.models import Package, PackageSource, PackageStatus
from app.profile.models import DeviceToken


def _client_with_profile(
    settings,
    redis_client,
    providers,
    scheduler,
    session_factory,
    clock,
) -> tuple[TestClient, UUID, UUID]:
    api = create_app(
        settings=settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
    )
    request = SimpleNamespace(app=api)
    request_otp(OTPRequest(phone_number="08055550130"), request)
    auth = verify_otp(
        OTPVerifyRequest(
            phone_number="08055550130", otp="123456", platform="android"
        ),
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
        session.flush()
        session.add(
            EsimProfile(
                package_id=package.id,
                aggregator=EsimAggregator.MONTY_MOBILE,
                iccid="8944501234567890123456",
                activation_code_lpa="LPA:1$activation.example$MATCH",
                qr_code_url="https://cdn.example/activation.png",
                status=EsimProfileStatus.DOWNLOADED,
                downloaded_at=clock(),
            )
        )
        session.commit()
        package_id = package.id
    return (
        TestClient(api, headers={"Authorization": f"Bearer {auth.access_token}"}),
        auth.user.id,
        package_id,
    )


def test_mark_activated_is_idempotent_after_connectivity_check(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-13.6: the successful connectivity check persists activated once."""
    client, _, package_id = _client_with_profile(
        settings, redis_client, providers, scheduler, session_factory, clock
    )

    first = client.post(f"/v1/packages/{package_id}/esim/mark-activated")
    assert first.status_code == 200
    assert first.json() == {"status": "activated"}
    with session_factory() as session:
        profile = session.exec(
            select(EsimProfile).where(EsimProfile.package_id == package_id)
        ).one()
        activated_at = profile.activated_at
        assert profile.status == EsimProfileStatus.ACTIVATED
        assert activated_at is not None

    clock.advance(minutes=5)
    second = client.post(f"/v1/packages/{package_id}/esim/mark-activated")
    assert second.status_code == 200
    with session_factory() as session:
        profile = session.exec(
            select(EsimProfile).where(EsimProfile.package_id == package_id)
        ).one()
        assert profile.activated_at == activated_at


def test_device_token_registration_upserts_one_app_installation(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-13.1: FCM registration is user-linked and refreshable."""
    client, user_id, _ = _client_with_profile(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    token = "fcm-registration-token-for-one-installation"

    first = client.put(
        "/v1/me/device-token",
        json={"fcm_token": token, "platform": "android"},
    )
    assert first.status_code == 200
    assert first.json() == {"registered": True}

    clock.advance(minutes=5)
    second = client.put(
        "/v1/me/device-token",
        json={"fcm_token": token, "platform": "ios"},
    )
    assert second.status_code == 200
    with session_factory() as session:
        rows = session.exec(select(DeviceToken)).all()
        assert len(rows) == 1
        assert rows[0].user_id == user_id
        assert rows[0].platform.value == "ios"
        assert rows[0].updated_at.replace(tzinfo=clock().tzinfo) == clock()
