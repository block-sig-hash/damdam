import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine

from app.auth.models import PricingTier, User
from app.esim.models import EsimAggregator, EsimProfile
from app.packages.models import Package, PackageSource, PackageStatus


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL eSIM idempotency constraint test runs in CI",
)
def test_one_esim_profile_per_package_is_database_enforced() -> None:
    """AC-11.4: the package unique key rejects a second profile row."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    suffix = uuid4().hex
    with Session(engine) as session:
        user = User(phone_number=f"+23481{suffix[:8]}", platform="android")
        tier = PricingTier(
            name=f"Esim-{suffix}",
            usd_reference_price=Decimal("30.00"),
            data_gb=5,
            pstn_minutes=30,
            wholesale_usd_price=Decimal("25.00"),
            ngn_price=Decimal("45000.00"),
        )
        session.add_all([user, tier])
        session.flush()
        package = Package(
            user_id=user.id,
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

        def profile(aggregator: EsimAggregator) -> EsimProfile:
            return EsimProfile(
                package_id=package.id,
                aggregator=aggregator,
                iccid=f"894450{uuid4().int % 10**16:016d}",
                activation_code_lpa=f"LPA:1$example${uuid4().hex}",
                qr_code_url=f"https://cdn.example/{uuid4()}.png",
            )

        session.add(profile(EsimAggregator.MONTY_MOBILE))
        session.commit()
        session.add(profile(EsimAggregator.ESIM_ACCESS))

        with pytest.raises(IntegrityError):
            session.commit()
