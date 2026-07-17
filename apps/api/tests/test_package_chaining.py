"""AC-25.3: real evidence that PackageChainingService blocks nothing and
instead chains a renewal onto the current package's window, rolling its
unused balance forward -- and that a genuinely separate future trip
(current package already expired) gets a fresh window, not a chained one.
"""

from datetime import timedelta, timezone
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
        window = service.chain(session, user.id, "SA", tier)
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
        window = service.chain(session, user.id, "SA", new_tier)
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
        window = service.chain(session, user.id, "SA", new_tier)
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
        window = service.chain(session, user.id, "SA", new_tier)
        session.commit()

    assert window.superseded_package_id is None
    assert window.extra_data_gb == Decimal("0.00")


def test_a_second_destinations_active_package_neither_blocks_nor_chains(
    session_factory, clock
) -> None:
    """The destination-abstraction fix: once a user can have an ACTIVE
    package for a different destination, buying a fresh package for a
    *new* destination must not touch the other destination's active
    package at all -- no chaining, no superseding, no balance roll-
    forward, and the existing destination's package must still be
    ACTIVE (and untouched) afterward. Two genuinely independent trips,
    not one being silently treated as a renewal of the other."""
    sa_tier = _tier(session_factory, validity_days=15)
    other_tier = _tier(session_factory, validity_days=20, data_gb=8, pstn_minutes=60)
    user = _user(session_factory)
    sa_expires_at = clock() + timedelta(days=10)
    with session_factory() as session:
        sa_package = Package(
            user_id=user.id,
            pricing_tier_id=sa_tier.id,
            source=PackageSource.RETAIL,
            status=PackageStatus.ACTIVE,
            data_gb_total=10,
            data_gb_remaining=Decimal("7.00"),
            pstn_minutes_total=90,
            pstn_minutes_remaining=Decimal("50.00"),
            purchased_at=clock(),
            expires_at=sa_expires_at,
            destination_country="SA",
        )
        session.add(sa_package)
        session.commit()
        session.refresh(sa_package)
        sa_package_id = sa_package.id

    service = PackageChainingService(clock)
    with session_factory() as session:
        window = service.chain(session, user.id, "KE", other_tier)
        session.commit()

    # A fresh window for the new destination -- not chained onto SA's
    # package, and no balance rolled forward from it.
    assert window.superseded_package_id is None
    assert window.extra_data_gb == Decimal("0.00")
    assert window.extra_pstn_minutes == Decimal("0.00")
    assert window.expires_at == clock() + timedelta(days=20)

    with session_factory() as session:
        # The SA package is completely untouched: still ACTIVE, still
        # holding its own original balance -- not superseded, not
        # expired, not raided for balance by an unrelated destination's
        # purchase.
        sa_package = session.get(Package, sa_package_id)
        assert sa_package.status == PackageStatus.ACTIVE
        assert sa_package.data_gb_remaining == Decimal("7.00")
        assert sa_package.pstn_minutes_remaining == Decimal("50.00")
        # SQLite strips tzinfo on read-back; normalize before comparing.
        assert sa_package.expires_at.replace(tzinfo=timezone.utc) == sa_expires_at


def test_same_destination_rebuy_still_chains_when_a_different_destination_also_exists(
    session_factory, clock
) -> None:
    """Regression guard the other direction: adding the destination
    dimension must not accidentally make same-destination chaining stop
    working when a second destination's package also exists for this
    user -- the existing US-25 behavior (chain onto the matching
    destination's package, ignore the other one) must hold."""
    sa_tier = _tier(session_factory, validity_days=15)
    sa_new_tier = _tier(session_factory, validity_days=30, data_gb=20, pstn_minutes=180)
    ke_tier = _tier(session_factory, validity_days=20)
    user = _user(session_factory)
    sa_expires_at = clock() + timedelta(days=10)
    with session_factory() as session:
        sa_package = Package(
            user_id=user.id,
            pricing_tier_id=sa_tier.id,
            source=PackageSource.RETAIL,
            status=PackageStatus.ACTIVE,
            data_gb_total=10,
            data_gb_remaining=Decimal("6.50"),
            pstn_minutes_total=90,
            pstn_minutes_remaining=Decimal("40.00"),
            purchased_at=clock(),
            expires_at=sa_expires_at,
            destination_country="SA",
        )
        ke_package = Package(
            user_id=user.id,
            pricing_tier_id=ke_tier.id,
            source=PackageSource.RETAIL,
            status=PackageStatus.ACTIVE,
            data_gb_total=10,
            data_gb_remaining=Decimal("9.00"),
            pstn_minutes_total=90,
            pstn_minutes_remaining=Decimal("85.00"),
            purchased_at=clock(),
            expires_at=clock() + timedelta(days=18),
            destination_country="KE",
        )
        session.add(sa_package)
        session.add(ke_package)
        session.commit()
        session.refresh(sa_package)
        session.refresh(ke_package)
        sa_package_id = sa_package.id
        ke_package_id = ke_package.id

    service = PackageChainingService(clock)
    with session_factory() as session:
        window = service.chain(session, user.id, "SA", sa_new_tier)
        session.commit()

    # Chains onto the SA package specifically, exactly as US-25 always
    # behaved -- unaffected by the KE package also existing.
    assert window.superseded_package_id == sa_package_id
    assert window.extra_data_gb == Decimal("6.50")
    assert window.extra_pstn_minutes == Decimal("40.00")
    assert window.expires_at == sa_expires_at + timedelta(days=30)

    with session_factory() as session:
        sa_package = session.get(Package, sa_package_id)
        ke_package = session.get(Package, ke_package_id)
        assert sa_package.status == PackageStatus.SUPERSEDED
        # The KE package is untouched by an SA-scoped chain() call.
        assert ke_package.status == PackageStatus.ACTIVE
        assert ke_package.data_gb_remaining == Decimal("9.00")
