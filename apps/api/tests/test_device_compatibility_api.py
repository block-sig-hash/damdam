from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import jwt
from fastapi.testclient import TestClient
from sqlmodel import select

from app.auth.models import (
    HTOApprovalStatus,
    Manifest,
    ManifestOrder,
    ManifestOrderStatus,
    ManifestPilgrim,
    ManifestStatus,
    ManifestValidationStatus,
    Organization,
    OrganizationType,
    PricingTier,
)
from app.auth.routes import request_otp, verify_otp
from app.auth.schemas import OTPRequest, OTPVerifyRequest
from app.esim.models import (
    DeviceCompatibilityLog,
    EsimAggregator,
    EsimProfile,
    EsimProfileStatus,
)
from app.main import create_app
from app.packages.models import Package, PackageSource, PackageStatus


def _payload(
    settings,
    redis_client,
    providers,
    scheduler,
    session_factory,
    clock,
):
    return create_app(
        settings=settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
    )


def _authenticated_client(api: object, phone_number: str) -> tuple[TestClient, UUID]:
    request = SimpleNamespace(app=api)
    request_otp(OTPRequest(phone_number=phone_number), request)
    auth = verify_otp(
        OTPVerifyRequest(phone_number=phone_number, otp="123456", platform="android"),
        request,
    )
    client = TestClient(
        api,
        headers={"Authorization": f"Bearer {auth.access_token}"},
        raise_server_exceptions=False,
    )
    return client, auth.user.id


def operator_headers(settings, clock, organization_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": str(organization_id),
            "aud": "hto_dashboard",
            "type": "access",
            "iat": clock(),
            "exp": clock() + timedelta(minutes=15),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def create_operator(session_factory, email: str) -> Organization:
    organization = Organization(
        org_type=OrganizationType.HTO_OPERATOR,
        name=f"{email} HTO",
        primary_contact_name="Amina Yusuf",
        email=email,
        password_hash="unused",
        phone_number="+2348012345678",
        nahcon_licence_number=f"NAHCON-{uuid4()}",
        email_verified=True,
        approval_status=HTOApprovalStatus.APPROVED,
    )
    with session_factory() as session:
        session.add(organization)
        session.commit()
        session.refresh(organization)
        session.expunge(organization)
    return organization


def test_compatible_device_is_logged_without_flagging(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-10.1/10.2: a compatible check is logged, no follow-up flag set."""
    api = _payload(settings, redis_client, providers, scheduler, session_factory, clock)
    client, user_id = _authenticated_client(api, "08011112222")

    response = client.post(
        "/v1/me/device-compatibility",
        json={
            "platform": "ios",
            "device_model": "iPhone 15",
            "os_version": "18.1",
            "esim_supported": True,
        },
    )

    assert response.status_code == 201
    assert response.json() == {"logged": True}
    with session_factory() as session:
        entry = session.exec(select(DeviceCompatibilityLog)).one()
        assert entry.user_id == user_id
        assert entry.esim_supported is True
        assert entry.platform.value == "ios"


def test_incompatible_device_flags_the_linked_manifest_pilgrim(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-10.7: an incompatible check flags the pilgrim for HTO follow-up."""
    api = _payload(settings, redis_client, providers, scheduler, session_factory, clock)
    client, user_id = _authenticated_client(api, "08022223333")

    organization = create_operator(session_factory, "hto-flag@example.com")
    with session_factory() as session:
        manifest = Manifest(
            organization_id=organization.id,
            name="Flight NAF203",
            status=ManifestStatus.VALIDATED,
        )
        session.add(manifest)
        session.flush()
        pilgrim = ManifestPilgrim(
            manifest_id=manifest.id,
            first_name="Amina",
            last_name="Yusuf",
            phone_number="08022223333",
            row_number=2,
            validation_status=ManifestValidationStatus.VALID,
            user_id=user_id,
        )
        session.add(pilgrim)
        session.commit()
        pilgrim_id = pilgrim.id

    response = client.post(
        "/v1/me/device-compatibility",
        json={
            "platform": "ios",
            "device_model": "iPhone X",
            "os_version": "16.0",
            "esim_supported": False,
        },
    )

    assert response.status_code == 201
    with session_factory() as session:
        pilgrim = session.get(ManifestPilgrim, pilgrim_id)
        assert pilgrim is not None
        assert pilgrim.esim_incompatible_flag is True


def test_incompatible_device_flags_lowest_id_pilgrim_deterministically(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """Regression test for the log_check ordering fix (PR #62 review):
    a user linked to more than one ManifestPilgrim row (e.g. re-added
    on a different manifest) must deterministically flag the
    lowest-id row, not whichever `.first()` happened to return.
    The higher-id row is inserted first here specifically so an
    unordered `.first()` would pick the wrong one — this test fails
    without the `.order_by(ManifestPilgrim.id)` fix.
    """
    api = _payload(settings, redis_client, providers, scheduler, session_factory, clock)
    client, user_id = _authenticated_client(api, "08099998888")

    organization = create_operator(session_factory, "hto-ordering@example.com")
    high_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    low_id = UUID("00000000-0000-0000-0000-000000000001")
    with session_factory() as session:
        manifest = Manifest(
            organization_id=organization.id,
            name="Flight NAF203",
            status=ManifestStatus.VALIDATED,
        )
        session.add(manifest)
        session.flush()
        # Inserted in this order (high id first) so an unordered
        # `.first()` would return the wrong row.
        pilgrim_high = ManifestPilgrim(
            id=high_id,
            manifest_id=manifest.id,
            first_name="Amina",
            last_name="Yusuf-Later",
            phone_number="08099998888",
            row_number=5,
            validation_status=ManifestValidationStatus.VALID,
            user_id=user_id,
        )
        pilgrim_low = ManifestPilgrim(
            id=low_id,
            manifest_id=manifest.id,
            first_name="Amina",
            last_name="Yusuf-Original",
            phone_number="08099998888",
            row_number=2,
            validation_status=ManifestValidationStatus.VALID,
            user_id=user_id,
        )
        session.add(pilgrim_high)
        session.commit()
        session.add(pilgrim_low)
        session.commit()

    response = client.post(
        "/v1/me/device-compatibility",
        json={
            "platform": "android",
            "device_model": "Tecno Spark 10",
            "esim_supported": False,
        },
    )

    assert response.status_code == 201
    with session_factory() as session:
        flagged_low = session.get(ManifestPilgrim, low_id)
        flagged_high = session.get(ManifestPilgrim, high_id)
        assert flagged_low is not None and flagged_low.esim_incompatible_flag is True
        assert flagged_high is not None and flagged_high.esim_incompatible_flag is False


def test_incompatible_device_for_retail_pilgrim_does_not_error(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """A retail (non-manifest) pilgrim has nothing to flag — must not crash."""
    api = _payload(settings, redis_client, providers, scheduler, session_factory, clock)
    client, _ = _authenticated_client(api, "08033334444")

    response = client.post(
        "/v1/me/device-compatibility",
        json={
            "platform": "android",
            "device_model": "Tecno Spark 10",
            "esim_supported": False,
        },
    )

    assert response.status_code == 201


def test_hto_pilgrims_list_shows_follow_up_flag_and_is_tenant_scoped(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-10.7: dashboard listing surfaces the flag, scoped to the owning org."""
    api = _payload(settings, redis_client, providers, scheduler, session_factory, clock)
    _, flagged_user_id = _authenticated_client(api, "08044445555")
    _, clean_user_id = _authenticated_client(api, "08055556666")

    owner = create_operator(session_factory, "hto-owner@example.com")
    other = create_operator(session_factory, "hto-other@example.com")

    with session_factory() as session:
        tier = PricingTier(
            name="Standard",
            usd_reference_price=100,
            data_gb=10,
            pstn_minutes=90,
            wholesale_usd_price=80,
            ngn_price=145000,
        )
        session.add(tier)
        session.flush()

        owner_manifest = Manifest(
            organization_id=owner.id,
            name="Flight NAF203",
            status=ManifestStatus.VALIDATED,
        )
        other_manifest = Manifest(
            organization_id=other.id,
            name="Flight NAF900",
            status=ManifestStatus.VALIDATED,
        )
        session.add_all([owner_manifest, other_manifest])
        session.flush()

        order = ManifestOrder(
            manifest_id=owner_manifest.id,
            pricing_tier_id=tier.id,
            pilgrim_count=1,
            wholesale_price_ngn=80000,
            total_ngn=145000,
            status=ManifestOrderStatus.PAID,
        )
        session.add(order)
        session.flush()

        flagged = ManifestPilgrim(
            manifest_id=owner_manifest.id,
            manifest_order_id=order.id,
            first_name="Amina",
            last_name="Yusuf",
            phone_number="08044445555",
            row_number=2,
            validation_status=ManifestValidationStatus.VALID,
            user_id=flagged_user_id,
            esim_incompatible_flag=True,
        )
        clean = ManifestPilgrim(
            manifest_id=owner_manifest.id,
            first_name="Bello",
            last_name="Aliyu",
            phone_number="08066667777",
            row_number=3,
            validation_status=ManifestValidationStatus.VALID,
            user_id=clean_user_id,
        )
        other_org_pilgrim = ManifestPilgrim(
            manifest_id=other_manifest.id,
            first_name="Chidi",
            last_name="Okoro",
            phone_number="08055556666",
            row_number=2,
            validation_status=ManifestValidationStatus.VALID,
        )
        session.add_all([flagged, clean, other_org_pilgrim])
        package = Package(
            user_id=clean_user_id,
            pricing_tier_id=tier.id,
            source=PackageSource.HTO_MANIFEST,
            status=PackageStatus.ACTIVE,
            data_gb_total=10,
            data_gb_remaining=10,
            pstn_minutes_total=90,
            pstn_minutes_remaining=90,
        )
        session.add(package)
        session.flush()
        session.add(
            EsimProfile(
                package_id=package.id,
                aggregator=EsimAggregator.MONTY_MOBILE,
                iccid="8944501234567890123456",
                activation_code_lpa="LPA:1$monty.example$match",
                qr_code_url="https://cdn.example/qr.png",
                status=EsimProfileStatus.DOWNLOADED,
                downloaded_at=clock(),
            )
        )
        session.commit()

    client = TestClient(api, headers=operator_headers(settings, clock, owner.id))
    response = client.get("/v1/hto/pilgrims")

    assert response.status_code == 200
    pilgrims = {p["name"]: p for p in response.json()["pilgrims"]}
    assert set(pilgrims) == {"Amina Yusuf", "Bello Aliyu"}
    assert pilgrims["Amina Yusuf"]["esim_status"] == "incompatible"
    assert pilgrims["Amina Yusuf"]["tier"] == "Standard"
    assert pilgrims["Amina Yusuf"]["activation_status"] == "activated"
    # AC-11.6: the existing HTO roster reports the profile lifecycle;
    # there is no second reporting endpoint.
    assert pilgrims["Bello Aliyu"]["esim_status"] == "downloaded"
    assert pilgrims["Bello Aliyu"]["activation_status"] == "activated"
    assert pilgrims["Bello Aliyu"]["tier"] is None


def test_hto_pilgrims_list_reflects_real_active_sos_alerts(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """US-18: sos_status was previously dead code (schema default "none",
    never computed) despite sos_alerts existing since US-16. A pilgrim with
    an active alert must show "active"; a resolved one and a pilgrim with
    no alert at all must both show "none", not leak stale alert history."""
    from app.sos.models import SOSAlert, SOSStatus

    api = _payload(settings, redis_client, providers, scheduler, session_factory, clock)
    _, alerting_user_id = _authenticated_client(api, "08044445555")
    _, resolved_user_id = _authenticated_client(api, "08066667777")
    _, quiet_user_id = _authenticated_client(api, "08077778888")
    owner = create_operator(session_factory, "hto-owner@example.com")

    with session_factory() as session:
        manifest = Manifest(
            organization_id=owner.id,
            name="Flight NAF203",
            status=ManifestStatus.VALIDATED,
        )
        session.add(manifest)
        session.flush()
        session.add_all(
            [
                ManifestPilgrim(
                    manifest_id=manifest.id,
                    first_name="Amina",
                    last_name="Yusuf",
                    phone_number="08044445555",
                    row_number=1,
                    validation_status=ManifestValidationStatus.VALID,
                    user_id=alerting_user_id,
                ),
                ManifestPilgrim(
                    manifest_id=manifest.id,
                    first_name="Bello",
                    last_name="Aliyu",
                    phone_number="08066667777",
                    row_number=2,
                    validation_status=ManifestValidationStatus.VALID,
                    user_id=resolved_user_id,
                ),
                ManifestPilgrim(
                    manifest_id=manifest.id,
                    first_name="Chidi",
                    last_name="Okoro",
                    phone_number="08077778888",
                    row_number=3,
                    validation_status=ManifestValidationStatus.VALID,
                    user_id=quiet_user_id,
                ),
            ]
        )
        session.add_all(
            [
                SOSAlert(
                    user_id=alerting_user_id,
                    client_generated_id=uuid4(),
                    timestamp=clock(),
                    status=SOSStatus.ACTIVE,
                ),
                SOSAlert(
                    user_id=resolved_user_id,
                    client_generated_id=uuid4(),
                    timestamp=clock(),
                    status=SOSStatus.RESOLVED,
                ),
            ]
        )
        session.commit()

    client = TestClient(api, headers=operator_headers(settings, clock, owner.id))
    response = client.get("/v1/hto/pilgrims")

    assert response.status_code == 200
    pilgrims = {p["name"]: p for p in response.json()["pilgrims"]}
    assert pilgrims["Amina Yusuf"]["sos_status"] == "active"
    assert pilgrims["Bello Aliyu"]["sos_status"] == "none"
    assert pilgrims["Chidi Okoro"]["sos_status"] == "none"


def test_hto_pilgrims_list_filters_by_manifest_id(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """The one documented query param (api-spec.md §7.8) actually filters —
    two manifests under the *same* organization, so this isolates the
    manifest_id filter from tenant scoping (already covered above)."""
    api = _payload(settings, redis_client, providers, scheduler, session_factory, clock)
    owner = create_operator(session_factory, "hto-filter@example.com")

    with session_factory() as session:
        manifest_a = Manifest(
            organization_id=owner.id,
            name="Flight NAF203",
            status=ManifestStatus.VALIDATED,
        )
        manifest_b = Manifest(
            organization_id=owner.id,
            name="Flight NAF900",
            status=ManifestStatus.VALIDATED,
        )
        session.add_all([manifest_a, manifest_b])
        session.flush()

        pilgrim_a = ManifestPilgrim(
            manifest_id=manifest_a.id,
            first_name="Amina",
            last_name="Yusuf",
            phone_number="08077778888",
            row_number=1,
            validation_status=ManifestValidationStatus.VALID,
        )
        pilgrim_b = ManifestPilgrim(
            manifest_id=manifest_b.id,
            first_name="Bello",
            last_name="Aliyu",
            phone_number="08088889999",
            row_number=1,
            validation_status=ManifestValidationStatus.VALID,
        )
        session.add_all([pilgrim_a, pilgrim_b])
        session.commit()
        manifest_a_id = manifest_a.id

    client = TestClient(api, headers=operator_headers(settings, clock, owner.id))
    response = client.get(f"/v1/hto/pilgrims?manifest_id={manifest_a_id}")

    assert response.status_code == 200
    pilgrims = {p["name"] for p in response.json()["pilgrims"]}
    assert pilgrims == {"Amina Yusuf"}
