import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from sqlmodel import Session, SQLModel, col, create_engine, select

from app.activation.service import ActivationError, ActivationService
from app.audit.service import AuditLogService
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
from app.packages.models import Package, PackageSource, PackageStatus
from app.packages.service import PackageChainingService


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL cascade test runs in CI",
)
def test_package_is_owned_by_and_cascades_with_user() -> None:
    """A purchased/activated package cannot outlive its owning pilgrim."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(phone_number="+2348012345691", platform="android")
        session.add(user)
        session.commit()
        session.refresh(user)

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

        session.add(
            Package(
                user_id=user.id,
                pricing_tier_id=tier.id,
                source=PackageSource.HTO_MANIFEST,
                status=PackageStatus.ACTIVE,
                data_gb_total=tier.data_gb,
                data_gb_remaining=tier.data_gb,
                pstn_minutes_total=tier.pstn_minutes,
                pstn_minutes_remaining=tier.pstn_minutes,
                purchased_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

        session.execute(delete(User).where(col(User.id) == user.id))
        session.commit()

        assert session.exec(select(Package)).all() == []


class _RecordingEsimScheduler:
    def schedule(self, package_id: UUID, countdown: int) -> None:
        del package_id, countdown


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL activation-code redemption race runs in CI",
)
def test_concurrent_redemption_of_the_same_activation_code_only_activates_once() -> (
    None
):
    """AC-25.2's real-concurrency counterpart to AC-25.1's payment-webhook
    compare-and-swap test: two simultaneous redemption attempts on the same
    single-use activation code must not both succeed in creating a package
    -- exactly one must win, and the loser must see
    activation_code_already_used, not a duplicate Package row."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    suffix = uuid4().hex[:8]
    with Session(engine) as session:
        organization = Organization(
            org_type=OrganizationType.HTO_OPERATOR,
            name=f"Barakah Hajj Services {suffix}",
            primary_contact_name="Amina Yusuf",
            email=f"operator-{suffix}@example.com",
            password_hash="not-used",
            phone_number=f"+23480{suffix}",
            nahcon_licence_number=f"NAHCON-{suffix}",
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
            name=f"Standard-{suffix}",
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

        phone_number = f"+23481{suffix}"
        pilgrim = ManifestPilgrim(
            manifest_id=manifest.id,
            manifest_order_id=order.id,
            first_name="Aisha",
            last_name="Bello",
            phone_number=phone_number,
            row_number=2,
            validation_status=ManifestValidationStatus.VALID,
            activation_code=uuid4().hex[:8].upper(),
            activation_code_expires_at=now + timedelta(days=30),
        )
        session.add(pilgrim)
        session.commit()
        session.refresh(pilgrim)
        activation_code = pilgrim.activation_code

        user = User(phone_number=phone_number, platform="android")
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)

    service = ActivationService(
        lambda: now,
        _RecordingEsimScheduler(),
        PackageChainingService(lambda: now),
        AuditLogService(lambda: now),
    )
    barrier = Barrier(2)

    def redeem() -> str:
        with Session(engine) as session:
            barrier.wait()
            try:
                package = service.redeem(session, user, activation_code)
                return f"ok:{package.id}"
            except ActivationError as error:
                return f"error:{error.code}"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: redeem(), range(2)))

    successes = [outcome for outcome in outcomes if outcome.startswith("ok:")]
    failures = [outcome for outcome in outcomes if outcome.startswith("error:")]
    assert len(successes) == 1
    assert failures == ["error:activation_code_already_used"]

    with Session(engine) as session:
        packages = session.exec(
            select(Package).where(Package.user_id == user.id)
        ).all()
        assert len(packages) == 1
