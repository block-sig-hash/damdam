from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import select

from app.auth.models import (
    HTOApprovalStatus,
    Manifest,
    ManifestOrder,
    ManifestOrderStatus,
    ManifestPilgrim,
    ManifestValidationStatus,
    Organization,
    OrganizationType,
    PricingTier,
    User,
)
from app.auth.routes import request_otp, verify_otp
from app.auth.schemas import OTPRequest, OTPVerifyRequest
from app.packages.models import Package

PILGRIM_LOCAL_PHONE = "08012345678"
PILGRIM_E164_PHONE = "+2348012345678"
OTHER_LOCAL_PHONE = "08100000000"


def seed_activation_code(
    session_factory, clock, phone_number: str = PILGRIM_E164_PHONE
):
    """Creates an organization + manifest + a provisioned manifest_order
    + a manifest_pilgrim with an activation code tied to `phone_number`
    (E.164) — mirroring the real state US-06's provisioning worker
    produces after payment confirmation (data-model.md §6.14), not a
    shortcut that bypasses the order. Returns
    (manifest_pilgrim_id, code, tier)."""
    with session_factory() as session:
        organization = Organization(
            org_type=OrganizationType.HTO_OPERATOR,
            name="Barakah Hajj Services",
            primary_contact_name="Amina Yusuf",
            email=f"operator-{phone_number}@example.com",
            password_hash="not-used",
            phone_number="+2348011111111",
            nahcon_licence_number="NAHCON-1",
            email_verified=True,
            approval_status=HTOApprovalStatus.APPROVED,
        )
        session.add(organization)
        session.commit()
        session.refresh(organization)

        manifest = Manifest(organization_id=organization.id, name="Flight NAF203")
        session.add(manifest)
        session.commit()
        session.refresh(manifest)

        tier = PricingTier(
            name="Standard",
            usd_reference_price=15,
            data_gb=10,
            pstn_minutes=60,
            wholesale_usd_price=10,
            ngn_price=24000,
        )
        session.add(tier)
        session.commit()
        session.refresh(tier)

        order = ManifestOrder(
            manifest_id=manifest.id,
            pricing_tier_id=tier.id,
            pilgrim_count=1,
            wholesale_price_ngn=10,
            total_ngn=10,
            status=ManifestOrderStatus.PROVISIONED,
        )
        session.add(order)
        session.commit()
        session.refresh(order)

        pilgrim = ManifestPilgrim(
            manifest_id=manifest.id,
            manifest_order_id=order.id,
            first_name="Aisha",
            last_name="Bello",
            phone_number=phone_number,
            row_number=2,
            validation_status=ManifestValidationStatus.VALID,
            activation_code=uuid4().hex[:8].upper(),
            activation_code_expires_at=clock() + timedelta(days=30),
        )
        session.add(pilgrim)
        session.commit()
        session.refresh(pilgrim)
        # Each commit above expires already-attached objects (default
        # SQLAlchemy behavior); refresh before expunging so tier's
        # attributes survive past this session.
        session.refresh(tier)
        session.expunge(tier)
        return pilgrim.id, pilgrim.activation_code, tier


def authenticated_client(api, phone_number: str) -> TestClient:
    request = SimpleNamespace(app=api)
    request_otp(OTPRequest(phone_number=phone_number), request)
    auth = verify_otp(
        OTPVerifyRequest(phone_number=phone_number, otp="123456", platform="android"),
        request,
    )
    return TestClient(api, headers={"Authorization": f"Bearer {auth.access_token}"})


def test_preview_shows_operator_and_tier_for_a_valid_code(
    api, session_factory, clock
) -> None:
    """AC-07.2: preview surfaces operator name and tier before login."""
    _, code, tier = seed_activation_code(session_factory, clock)
    client = TestClient(api)

    response = client.get(f"/v1/activation/{code}")

    assert response.status_code == 200
    assert response.json() == {
        "valid": True,
        "reason": None,
        "organization_name": "Barakah Hajj Services",
        "pricing_tier_name": tier.name,
    }


def test_preview_returns_not_found_for_an_unknown_code(api) -> None:
    client = TestClient(api)

    response = client.get("/v1/activation/NOTAREAL")

    assert response.status_code == 404
    assert response.json()["error"] == "activation_code_invalid"


def test_new_pilgrim_redeems_code_after_otp_verify(
    api, session_factory, clock
) -> None:
    """AC-07.4: New pilgrim OTP-verifies, then the code auto-attaches
    a package sized from the tier it was generated against."""
    pilgrim_id, code, tier = seed_activation_code(session_factory, clock)
    client = authenticated_client(api, PILGRIM_LOCAL_PHONE)

    response = client.post(
        "/v1/me/activation/redeem", json={"activation_code": code}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pricing_tier_name"] == tier.name
    assert body["data_gb_total"] == tier.data_gb
    assert body["pstn_minutes_total"] == tier.pstn_minutes
    assert body["status"] == "active"

    with session_factory() as session:
        pilgrim = session.get(ManifestPilgrim, pilgrim_id)
        assert pilgrim is not None
        assert pilgrim.activation_code_used is True
        assert pilgrim.user_id is not None

        package = session.exec(
            select(Package).where(Package.user_id == pilgrim.user_id)
        ).one()
        assert package.source.value == "hto_manifest"
        assert package.data_gb_remaining == tier.data_gb
        assert package.pstn_minutes_remaining == tier.pstn_minutes


def test_existing_pilgrim_redeems_code_after_logging_in(
    api, session_factory, clock
) -> None:
    """AC-07.5: an already-registered pilgrim (existing session/refresh
    token, per US-23's persistent-session model — not a fresh OTP
    signup, which /auth/otp/request correctly refuses for an existing
    account) redeems the same way a new pilgrim does."""
    _, code, _tier = seed_activation_code(session_factory, clock)
    with session_factory() as session:
        user = User(phone_number=PILGRIM_E164_PHONE, platform="android")
        session.add(user)
        session.commit()
        session.refresh(user)
        pair = api.state.otp_service.tokens.issue(session, user, clock())
    client = TestClient(api, headers={"Authorization": f"Bearer {pair.access_token}"})

    response = client.post(
        "/v1/me/activation/redeem", json={"activation_code": code}
    )

    assert response.status_code == 200


def test_redeem_rejects_an_already_used_code(api, session_factory, clock) -> None:
    """AC-07.3: single-use."""
    _, code, _tier = seed_activation_code(session_factory, clock)
    client = authenticated_client(api, PILGRIM_LOCAL_PHONE)
    first = client.post("/v1/me/activation/redeem", json={"activation_code": code})
    assert first.status_code == 200

    second = client.post("/v1/me/activation/redeem", json={"activation_code": code})

    assert second.status_code == 409
    assert second.json()["error"] == "activation_code_already_used"


def test_redeem_rejects_an_expired_code(api, session_factory, clock) -> None:
    """AC-07.3: expires after 30 days. Authenticates first, then
    advances the clock 31 days, since a token minted post-advance
    would need its own longer-lived exp — this isolates the code's
    own expiry from the access token's."""
    _, code, _tier = seed_activation_code(session_factory, clock)
    clock.advance(days=31)
    with session_factory() as session:
        user = User(phone_number=PILGRIM_E164_PHONE, platform="android")
        session.add(user)
        session.commit()
        session.refresh(user)
        pair = api.state.otp_service.tokens.issue(session, user, clock())
    client = TestClient(api, headers={"Authorization": f"Bearer {pair.access_token}"})

    response = client.post(
        "/v1/me/activation/redeem", json={"activation_code": code}
    )

    assert response.status_code == 410
    assert response.json()["error"] == "activation_code_expired"


def test_redeem_rejects_a_phone_number_that_does_not_match_the_manifest_row(
    api, session_factory, clock
) -> None:
    """A code issued for one pilgrim's phone number cannot be redeemed
    by a different authenticated phone number."""
    _, code, _tier = seed_activation_code(session_factory, clock, PILGRIM_E164_PHONE)
    client = authenticated_client(api, OTHER_LOCAL_PHONE)

    response = client.post(
        "/v1/me/activation/redeem", json={"activation_code": code}
    )

    assert response.status_code == 403
    assert response.json()["error"] == "activation_code_phone_mismatch"


def test_redeem_requires_pilgrim_authentication(api, session_factory, clock) -> None:
    _, code, _tier = seed_activation_code(session_factory, clock)
    client = TestClient(api)

    response = client.post(
        "/v1/me/activation/redeem", json={"activation_code": code}
    )

    assert response.status_code == 401


def test_redeem_rejects_an_unknown_code(api) -> None:
    client = authenticated_client(api, PILGRIM_LOCAL_PHONE)

    response = client.post(
        "/v1/me/activation/redeem", json={"activation_code": "NOTAREAL"}
    )

    assert response.status_code == 404
    assert response.json()["error"] == "activation_code_invalid"


def test_redeem_normalizes_lowercase_and_whitespace_in_the_submitted_code(
    api, session_factory, clock
) -> None:
    _, code, _tier = seed_activation_code(session_factory, clock)
    client = authenticated_client(api, PILGRIM_LOCAL_PHONE)

    response = client.post(
        "/v1/me/activation/redeem",
        json={"activation_code": f"  {code.lower()}  "},
    )

    assert response.status_code == 200
