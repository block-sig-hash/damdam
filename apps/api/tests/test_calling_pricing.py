"""Maximum authorized exposure — the number that gets reserved.

This is the only arithmetic between a tariff and a hold on somebody's money, so
it is tested for the ways it can be wrong in the customer's disfavour and in
ours. The rules come from chunk 09's `TariffRate`: a setup amount, a per-minute
rate, a minimum duration and a billing increment, all of which the supplier and
the retail tariff may define differently.
"""

from decimal import Decimal

import pytest

from app.calling.pricing import billable_seconds, estimate_max_charge


class TestBillableSeconds:
    def test_rounds_up_to_the_increment(self) -> None:
        assert billable_seconds(61, minimum_seconds=0, increment_seconds=60) == 120

    def test_an_exact_multiple_is_not_pushed_to_the_next_increment(self) -> None:
        # Charging 120 seconds for a 120-second call plus one increment is the
        # classic off-by-one that customers notice and disputes are made of.
        assert billable_seconds(120, minimum_seconds=0, increment_seconds=60) == 120

    def test_minimum_applies_below_it(self) -> None:
        assert billable_seconds(5, minimum_seconds=30, increment_seconds=1) == 30

    def test_minimum_is_itself_rounded_to_the_increment(self) -> None:
        assert billable_seconds(5, minimum_seconds=30, increment_seconds=60) == 60

    def test_per_second_billing_is_exact(self) -> None:
        assert billable_seconds(37, minimum_seconds=0, increment_seconds=1) == 37

    def test_zero_duration_still_costs_the_minimum(self) -> None:
        assert billable_seconds(0, minimum_seconds=60, increment_seconds=60) == 60


class TestMaxCharge:
    def test_setup_plus_metered_time(self) -> None:
        charge = estimate_max_charge(
            seconds=120,
            per_minute_amount=Decimal("30.00"),
            setup_amount=Decimal("5.00"),
            minimum_seconds=0,
            increment_seconds=60,
            currency="NGN",
        )
        assert charge == Decimal("65.00")

    def test_partial_increment_is_charged_as_a_whole_one(self) -> None:
        charge = estimate_max_charge(
            seconds=61,
            per_minute_amount=Decimal("30.00"),
            setup_amount=Decimal("0.00"),
            minimum_seconds=0,
            increment_seconds=60,
            currency="NGN",
        )
        assert charge == Decimal("60.00")

    def test_rounds_the_reserved_amount_up_rather_than_to_nearest(self) -> None:
        # A reservation that rounds *down* under-reserves, and the shortfall is
        # discovered at settlement when the money is already spent. Rounding a
        # hold up costs the customer nothing: the unused part is released.
        charge = estimate_max_charge(
            seconds=1,
            per_minute_amount=Decimal("0.011"),
            setup_amount=Decimal("0"),
            minimum_seconds=0,
            increment_seconds=1,
            currency="NGN",
        )
        assert charge == Decimal("0.01")

    def test_a_zero_rate_still_reserves_nothing_rather_than_failing(self) -> None:
        charge = estimate_max_charge(
            seconds=60,
            per_minute_amount=Decimal("0"),
            setup_amount=Decimal("0"),
            minimum_seconds=0,
            increment_seconds=60,
            currency="NGN",
        )
        assert charge == Decimal("0")

    @pytest.mark.parametrize("seconds", [-1, -60])
    def test_negative_duration_is_refused(self, seconds: int) -> None:
        with pytest.raises(ValueError):
            estimate_max_charge(
                seconds=seconds,
                per_minute_amount=Decimal("30"),
                setup_amount=Decimal("0"),
                minimum_seconds=0,
                increment_seconds=60,
                currency="NGN",
            )
