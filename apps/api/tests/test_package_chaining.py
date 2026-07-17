"""AC-25.3: real evidence that PackageChainingService blocks nothing and
instead chains a renewal onto the current package's window, rolling its
unused balance forward -- and that a genuinely separate future trip
(current package already expired) gets a fresh window, not a chained one.
"""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from app.auth.models import PricingTier, User
from app.packages.models import Package, PackageSource, PackageStatus
from app.packages.service import PackageChainingService


def _tier(
    session_factory, validity_days: int, data_gb: int = 10, pstn_minutes: int = 90
):
    with session_factory() as session:
        tier = PricingTier(
            name=f"Tier-{uuid4().hex[:6]}",
            usd_reference_price=Decimal("100"),
            data_gb=data_gb,
            pstn_minutes=pstn_minutes,
            wholesale_usd_price=Decimal("80"),
            ngn_price=Decimal("100000"),
            validity_days=validity_days,
        )
        session.add(tier)
        session.commit()
        session.refresh(tier)
        return tier


def _user(session_factory):
    with session_factory() as session:
        user = User(phone_number=f"+2348{uuid4().hex[:9]}", platform="android")
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def test_no_existing_active_package_gets_a_fresh_window(session_factory, clock) -> None:
    tier = _tier(session_factory, validity_days=15)
    user = _user(session_factory)
    service = PackageChainingService(clock)

    with session_factory() as session:
        window = service.chain(session, user.id, tier)
        session.commit()

    assert window.superseded_package_id is None
    assert window.extra_data_gb == Decimal("0.00")
    assert window.extra_pstn_minutes == Decimal("0.00")
    assert window.expires_at == clock() + timedelta(days=15)


def test_rebuy_while_still_valid_chains_and_rolls_balance_forward(
    session_factory, clock
) -> None:
    """The core AC-25.3 scenario: buying a new package while the current
    one still has time left must not create a second concurrently-active
    package, must roll the unused balance forward so nothing paid-for is
    stranded, and must start the new window from the current package's
    expiry, not from the purchase moment."""
    tier = _tier(session_factory, validity_days=15)
    new_tier = _tier(session_factory, validity_days=30, data_gb=20, pstn_minutes=180)
    user = _user(session_factory)
    # Captured before the SQLite round-trip, which strips tzinfo on
    # read-back -- the service itself re-normalizes to UTC internally
    # (verified by this test's own assertion below matching), this is
    # purely about keeping the *test's* expected-value arithmetic in the
    # same aware/naive representation throughout.
    current_expires_at = clock() + timedelta(days=10)
    with session_factory() as session:
        current = Package(
            user_id=user.id,
            pricing_tier_id=tier.id,
            source=PackageSource.RETAIL,
            status=PackageStatus.ACTIVE,
            data_gb_total=10,
            data_gb_remaining=Decimal("6.50"),
            pstn_minutes_total=90,
            pstn_minutes_remaining=Decimal("40.00"),
            purchased_at=clock(),
            expires_at=current_expires_at,  # still 10 days left
        )
        session.add(current)
        session.commit()
        session.refresh(current)
        current_id = current.id

    service = PackageChainingService(clock)
    with session_factory() as session:
        window = service.chain(session, user.id, new_tier)
        session.commit()

    assert window.superseded_package_id == current_id
    assert window.extra_data_gb == Decimal("6.50")
    assert window.extra_pstn_minutes == Decimal("40.00")
    # Chained onto the CURRENT package's expiry, not "now" -- this is what
    # makes it a renewal rather than two overlapping purchases.
    assert window.expires_at == current_expires_at + timedelta(days=30)

    with session_factory() as session:
        superseded = session.get(Package, current_id)
        assert superseded.status == PackageStatus.SUPERSEDED


def test_stale_active_package_past_its_window_does_not_roll_balance_forward(
    session_factory, clock
) -> None:
    """A package that's still status=ACTIVE (nothing ever sweeps it) but
    whose expires_at has already passed represents a genuinely separate,
    concluded past trip -- not a rebuy. Its stale balance must not leak
    into an unrelated future purchase, and the new window must start from
    now, not from the long-past expiry."""
    tier = _tier(session_factory, validity_days=7)
    new_tier = _tier(session_factory, validity_days=30)
    user = _user(session_factory)
    with session_factory() as session:
        stale = Package(
            user_id=user.id,
            pricing_tier_id=tier.id,
            source=PackageSource.RETAIL,
            status=PackageStatus.ACTIVE,
            data_gb_total=5,
            data_gb_remaining=Decimal("3.00"),  # unused, but the trip is over
            pstn_minutes_total=30,
            pstn_minutes_remaining=Decimal("10.00"),
            purchased_at=clock() - timedelta(days=400),
            expires_at=clock() - timedelta(days=393),  # long expired
        )
        session.add(stale)
        session.commit()
        session.refresh(stale)
        stale_id = stale.id

    service = PackageChainingService(clock)
    with session_factory() as session:
        window = service.chain(session, user.id, new_tier)
        session.commit()

    assert window.superseded_package_id is None  # not a chain -- a fresh trip
    # Stale balance not rolled forward.
    assert window.extra_data_gb == Decimal("0.00")
    assert window.extra_pstn_minutes == Decimal("0.00")
    # Fresh window, not chained.
    assert window.expires_at == clock() + timedelta(days=30)

    with session_factory() as session:
        # Lazily corrected to EXPIRED now that we've discovered the truth,
        # not left dangling as ACTIVE.
        assert session.get(Package, stale_id).status == PackageStatus.EXPIRED


def test_rebuy_exactly_at_expiry_boundary_is_treated_as_a_fresh_trip(
    session_factory, clock
) -> None:
    """expires_at == now is not "still valid" -- confirms the boundary
    condition explicitly rather than leaving it to chance."""
    tier = _tier(session_factory, validity_days=7)
    new_tier = _tier(session_factory, validity_days=30)
    user = _user(session_factory)
    with session_factory() as session:
        boundary = Package(
            user_id=user.id,
            pricing_tier_id=tier.id,
            source=PackageSource.RETAIL,
            status=PackageStatus.ACTIVE,
            data_gb_total=5,
            data_gb_remaining=Decimal("2.00"),
            pstn_minutes_total=30,
            pstn_minutes_remaining=Decimal("5.00"),
            purchased_at=clock() - timedelta(days=7),
            expires_at=clock(),  # expires exactly now
        )
        session.add(boundary)
        session.commit()

    service = PackageChainingService(clock)
    with session_factory() as session:
        window = service.chain(session, user.id, new_tier)
        session.commit()

    assert window.superseded_package_id is None
    assert window.extra_data_gb == Decimal("0.00")
