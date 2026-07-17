from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import jwt
from fastapi.testclient import TestClient
from sqlmodel import select

from app.audit.models import AuditLog, AuditOutcome
from app.auth.models import AdminUser, PricingTier, User
from app.packages.models import Package, PackageSource, PackageStatus


def _admin_headers(settings, clock, admin_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": str(admin_id),
            "aud": "admin",
            "type": "access",
            "iat": clock(),
            "exp": clock() + timedelta(minutes=15),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _seed(session_factory) -> tuple[UUID, UUID, UUID]:
    """Creates an admin, a user, and one ACTIVE package. Returns
    (admin_id, user_id, package_id)."""
    with session_factory() as session:
        admin = AdminUser(
            email=f"admin-{uuid4().hex[:8]}@example.com", password_hash="x"
        )
        user = User(phone_number=f"+2348{uuid4().hex[:9]}", platform="android")
        tier = PricingTier(
            name="Standard",
            usd_reference_price=Decimal("100"),
            data_gb=10,
            pstn_minutes=90,
            wholesale_usd_price=Decimal("80"),
            ngn_price=Decimal("100000"),
        )
        session.add_all([admin, user, tier])
        session.commit()
        session.refresh(admin)
        session.refresh(user)
        session.refresh(tier)
        package = Package(
            user_id=user.id,
            pricing_tier_id=tier.id,
            source=PackageSource.RETAIL,
            status=PackageStatus.ACTIVE,
            data_gb_total=10,
            data_gb_remaining=Decimal("10.00"),
            pstn_minutes_total=90,
            pstn_minutes_remaining=Decimal("90.00"),
            purchased_at=datetime.now(timezone.utc),
        )
        session.add(package)
        session.commit()
        session.refresh(package)
        return admin.id, user.id, package.id


def test_admin_cancels_a_package_and_writes_an_audit_entry(
    api, settings, clock, session_factory
) -> None:
    """AC-25.3: an admin can undo a mistaken duplicate purchase by
    cancelling one of the two packages -- cancel-only, no balance
    reversal or refund (data-model.md §6.30)."""
    admin_id, user_id, package_id = _seed(session_factory)
    client = TestClient(api)

    response = client.post(
        f"/v1/admin/packages/{package_id}/cancel",
        headers=_admin_headers(settings, clock, admin_id),
    )

    assert response.status_code == 200
    assert response.json() == {"id": str(package_id), "status": "cancelled"}

    with session_factory() as session:
        package = session.get(Package, package_id)
        assert package is not None
        assert package.status == PackageStatus.CANCELLED
        # Cancel-only: balance untouched, no reversal/refund side effects.
        assert package.data_gb_remaining == Decimal("10.00")
        assert package.pstn_minutes_remaining == Decimal("90.00")

        audit_entry = session.exec(
            select(AuditLog).where(
                AuditLog.outcome == AuditOutcome.PACKAGE_CANCELLED_BY_ADMIN
            )
        ).one()
        assert audit_entry.reference == str(package_id)
        assert audit_entry.user_id == user_id
        assert str(admin_id) in (audit_entry.details or "")


def test_cancelling_an_already_cancelled_package_is_idempotent(
    api, settings, clock, session_factory
) -> None:
    admin_id, _, package_id = _seed(session_factory)
    client = TestClient(api)
    headers = _admin_headers(settings, clock, admin_id)

    first = client.post(f"/v1/admin/packages/{package_id}/cancel", headers=headers)
    second = client.post(f"/v1/admin/packages/{package_id}/cancel", headers=headers)

    assert first.status_code == second.status_code == 200
    with session_factory() as session:
        entries = session.exec(
            select(AuditLog).where(
                AuditLog.outcome == AuditOutcome.PACKAGE_CANCELLED_BY_ADMIN
            )
        ).all()
        # Idempotent: the second call is a no-op, not a second audit entry.
        assert len(entries) == 1


def test_cancel_requires_admin_auth_and_rejects_unknown_package(
    api, settings, clock, session_factory
) -> None:
    admin_id, _, _ = _seed(session_factory)
    client = TestClient(api)

    unauthenticated = client.post(f"/v1/admin/packages/{uuid4()}/cancel")
    assert unauthenticated.status_code == 401

    missing = client.post(
        f"/v1/admin/packages/{uuid4()}/cancel",
        headers=_admin_headers(settings, clock, admin_id),
    )
    assert missing.status_code == 404
    assert missing.json()["error"] == "package_not_found"
