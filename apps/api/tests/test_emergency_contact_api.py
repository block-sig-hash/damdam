from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.auth.models import (
    HTOApprovalStatus,
    Manifest,
    ManifestPilgrim,
    ManifestStatus,
    ManifestValidationStatus,
    Organization,
    OrganizationType,
)
from app.auth.routes import request_otp, verify_otp
from app.auth.schemas import OTPRequest, OTPVerifyRequest
from app.main import create_app


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


def test_hto_manifest_pilgrim_gets_their_operators_contact(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-12.2: the HTO operator's number is read live from the pilgrim's
    assigned organization, not bundled/hardcoded."""
    api = create_app(
        settings=settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
    )
    client, user_id = _authenticated_client(api, "08011112222")

    organization = create_operator(session_factory, "hto-emergency@example.com")
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
            phone_number="08011112222",
            row_number=2,
            validation_status=ManifestValidationStatus.VALID,
            user_id=user_id,
        )
        session.add(pilgrim)
        session.commit()

    response = client.get("/v1/me/emergency-contact")

    assert response.status_code == 200
    assert response.json() == {
        "hto_operator_name": "hto-emergency@example.com HTO",
        "hto_operator_phone_number": "+2348012345678",
    }


def test_direct_retail_pilgrim_has_no_hto_operator(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """A retail (non-manifest) pilgrim has no assigned HTO — both fields
    are null, not a 404/error, so the client just hides that row."""
    api = create_app(
        settings=settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
    )
    client, _ = _authenticated_client(api, "08033334444")

    response = client.get("/v1/me/emergency-contact")

    assert response.status_code == 200
    assert response.json() == {
        "hto_operator_name": None,
        "hto_operator_phone_number": None,
    }


def test_emergency_contact_requires_authentication(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    api = create_app(
        settings=settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
    )
    client = TestClient(api, raise_server_exceptions=False)

    response = client.get("/v1/me/emergency-contact")

    assert response.status_code == 401


def test_emergency_contact_does_not_leak_another_organizations_contact(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """Two pilgrims on two different HTOs must each get only their own
    organization's contact, never the other's."""
    api = create_app(
        settings=settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
    )
    client_a, user_a = _authenticated_client(api, "08044445555")
    client_b, user_b = _authenticated_client(api, "08055556666")

    org_a = create_operator(session_factory, "hto-a@example.com")
    org_b = create_operator(session_factory, "hto-b@example.com")
    with session_factory() as session:
        manifest_a = Manifest(
            organization_id=org_a.id,
            name="Flight NAF203",
            status=ManifestStatus.VALIDATED,
        )
        manifest_b = Manifest(
            organization_id=org_b.id,
            name="Flight NAF900",
            status=ManifestStatus.VALIDATED,
        )
        session.add_all([manifest_a, manifest_b])
        session.flush()
        session.add_all(
            [
                ManifestPilgrim(
                    manifest_id=manifest_a.id,
                    first_name="Amina",
                    last_name="Yusuf",
                    phone_number="08044445555",
                    row_number=1,
                    validation_status=ManifestValidationStatus.VALID,
                    user_id=user_a,
                ),
                ManifestPilgrim(
                    manifest_id=manifest_b.id,
                    first_name="Bello",
                    last_name="Aliyu",
                    phone_number="08055556666",
                    row_number=1,
                    validation_status=ManifestValidationStatus.VALID,
                    user_id=user_b,
                ),
            ]
        )
        session.commit()

    response_a = client_a.get("/v1/me/emergency-contact")
    response_b = client_b.get("/v1/me/emergency-contact")

    assert response_a.json()["hto_operator_name"] == "hto-a@example.com HTO"
    assert response_b.json()["hto_operator_name"] == "hto-b@example.com HTO"
