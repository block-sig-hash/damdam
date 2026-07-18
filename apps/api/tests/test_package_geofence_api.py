from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlmodel import select

from app.auth.models import PricingTier, User
from app.auth.routes import request_otp, verify_otp
from app.auth.schemas import OTPRequest, OTPVerifyRequest
from app.packages.models import DestinationGeofence, Package, PackageSource


def _authenticated_client(api: object, phone_number: str = "08012345678") -> TestClient:
    request = SimpleNamespace(app=api)
    request_otp(OTPRequest(phone_number=phone_number), request)
    auth = verify_otp(
        OTPVerifyRequest(
            phone_number=phone_number, otp="123456", platform="android"
        ),
        request,
    )
    client = TestClient(
        api, headers={"Authorization": f"Bearer {auth.access_token}"}
    )
    return client


def test_package_geofence_is_destination_keyed_and_missing_config_is_404(
    api, session_factory
) -> None:
    client = _authenticated_client(api)
    with session_factory() as session:
        user = session.exec(
            select(User).where(User.phone_number == "+2348012345678")
        ).one()
        tier = PricingTier(
            name="Standard",
            usd_reference_price=Decimal("100.00"),
            data_gb=5,
            pstn_minutes=30,
            wholesale_usd_price=Decimal("80.00"),
            ngn_price=Decimal("100000.00"),
        )
        package = Package(
            user_id=user.id,
            pricing_tier_id=tier.id,
            source=PackageSource.RETAIL,
            data_gb_total=5,
            data_gb_remaining=Decimal("5.00"),
            pstn_minutes_total=30,
            pstn_minutes_remaining=Decimal("30.00"),
            destination_country="SA",
        )
        session.add_all(
            [
                tier,
                package,
                DestinationGeofence(
                    destination_country="SA",
                    latitude=21.4858,
                    longitude=39.1925,
                    radius_meters=150000.0,
                ),
            ]
        )
        session.commit()
        session.refresh(package)
        package_id = package.id

    response = client.get(f"/v1/packages/{package_id}/geofence")

    assert response.status_code == 200
    assert response.json() == {
        "latitude": 21.4858,
        "longitude": 39.1925,
        "radius_meters": 150000.0,
        "request_id": f"arrival-sa-{package_id}",
    }

    other_user = _authenticated_client(api, "08012345679")
    not_owned = other_user.get(f"/v1/packages/{package_id}/geofence")
    assert not_owned.status_code == 404
    assert not_owned.json()["error"] == "package_not_found"

    with session_factory() as session:
        package = session.exec(select(Package).where(Package.id == package_id)).one()
        package.destination_country = "KE"
        session.add(package)
        session.commit()

    missing = client.get(f"/v1/packages/{package_id}/geofence")

    assert missing.status_code == 404
    assert missing.json()["error"] == "destination_geofence_not_configured"
