from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import select

from app.auth.models import PricingTier


def _tier(
    name: str,
    price: str,
    data_gb: int,
    minutes: int,
    *,
    group: bool = False,
    active: bool = True,
) -> PricingTier:
    return PricingTier(
        name=name,
        usd_reference_price=Decimal("100.00"),
        data_gb=data_gb,
        pstn_minutes=minutes,
        is_group_tier=group,
        min_group_size=2 if group else None,
        max_group_size=8 if group else None,
        wholesale_usd_price=Decimal("80.00"),
        active=active,
        ngn_price=Decimal(price),
    )


def test_public_pricing_returns_four_tiers_from_current_admin_prices(
    api, session_factory
) -> None:
    """AC-08.1/2/4/6: public tiers expose current stored Naira prices."""
    with session_factory() as session:
        session.add_all(
            [
                _tier("Family", "75000.00", 12, 100, group=True),
                _tier("Standard", "145000.00", 10, 90),
                _tier("Starter", "65000.00", 3, 20),
                _tier("Basic", "95000.00", 6, 45),
                _tier("Retired", "1.00", 1, 1, active=False),
            ]
        )
        session.commit()

    response = TestClient(api).get("/v1/pricing/tiers")

    assert response.status_code == 200
    tiers = response.json()["tiers"]
    assert [tier["name"] for tier in tiers] == [
        "Starter",
        "Basic",
        "Standard",
        "Family",
    ]
    assert [tier["ngn_price"] for tier in tiers] == [
        65000.0,
        95000.0,
        145000.0,
        75000.0,
    ]
    assert tiers[2]["data_gb"] == 10
    assert tiers[2]["pstn_minutes"] == 90
    assert "per_person_ngn_rate" not in tiers[2]
    assert tiers[3]["min_group_size"] == 2
    assert tiers[3]["max_group_size"] == 8
    assert tiers[3]["per_person_ngn_rate"] == 75000.0

    with session_factory() as session:
        standard = session.exec(
            select(PricingTier).where(PricingTier.name == "Standard")
        ).one()
        standard.ngn_price = Decimal("155000.00")
        session.add(standard)
        session.commit()

    refreshed = TestClient(api).get("/v1/pricing/tiers").json()["tiers"]
    assert next(tier for tier in refreshed if tier["name"] == "Standard")[
        "ngn_price"
    ] == 155000.0


def test_public_pricing_is_unauthenticated_and_handles_no_active_tiers(api) -> None:
    """The public catalogue has no pilgrim-session dependency or stale fallback."""
    response = TestClient(api).get("/v1/pricing/tiers")

    assert response.status_code == 200
    assert response.json() == {"tiers": []}
