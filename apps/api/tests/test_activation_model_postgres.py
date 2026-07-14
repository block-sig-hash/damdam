import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete
from sqlmodel import Session, SQLModel, col, create_engine, select

from app.auth.models import PricingTier, User
from app.packages.models import Package, PackageSource, PackageStatus


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
