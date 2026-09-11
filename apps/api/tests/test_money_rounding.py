"""Currency-aware rounding (US-31, chunk 09).

Written before the implementation. Money is in the repository's strict-TDD
category, and rounding is where money quietly goes missing: a half-cent dropped
the wrong way on every line of a forty-line order is a real amount, and it is
invisible in any test that checks one line at a time.

Three properties matter and none of them are "it rounds":

1. **The exponent is the currency's, not two.** JPY has no minor unit, KWD has
   three. Charging ¥1,234.57 is not a rounding error, it is an amount that
   cannot be paid.
2. **The direction is fixed and documented.** Banker's rounding, not
   half-up: over a large number of lines half-up drifts consistently in the
   seller's favour, which is the kind of bias a regulator asks about.
3. **It is deterministic.** The same inputs give the same answer on every
   machine, which is why this uses `Decimal` and never a float.
"""

from decimal import Decimal, InvalidOperation

import pytest

from app.money import (
    CurrencyError,
    currency_exponent,
    round_money,
    sum_money,
)


class TestExponents:
    @pytest.mark.parametrize(
        ("currency", "exponent"),
        [
            ("NGN", 2),
            ("USD", 2),
            ("EUR", 2),
            ("GBP", 2),
            # Zero-exponent currencies. ISO 4217 lists these with no minor unit.
            ("JPY", 0),
            ("KRW", 0),
            ("XOF", 0),
            ("XAF", 0),
            # Three-exponent currencies.
            ("KWD", 3),
            ("BHD", 3),
            ("TND", 3),
            ("JOD", 3),
        ],
    )
    def test_known_currencies_use_their_iso_4217_minor_unit(self, currency, exponent):
        assert currency_exponent(currency) == exponent

    def test_an_unknown_currency_is_refused_rather_than_assumed_to_be_two(self):
        """The dangerous default.

        Assuming two would silently charge a hundred times too much in a
        zero-exponent currency, and the failure would look like a pricing
        decision rather than a bug.
        """
        with pytest.raises(CurrencyError) as excinfo:
            currency_exponent("ZZZ")
        assert "ZZZ" in str(excinfo.value)

    def test_a_malformed_code_is_refused(self):
        for value in ("ngn", "NG", "NGNN", "", "N-N"):
            with pytest.raises(CurrencyError):
                currency_exponent(value)


class TestRounding:
    @pytest.mark.parametrize(
        ("amount", "currency", "expected"),
        [
            ("1234.567", "NGN", "1234.57"),
            ("1234.561", "NGN", "1234.56"),
            ("1234.567", "JPY", "1235"),
            ("1234.4", "JPY", "1234"),
            ("1.23456", "KWD", "1.235"),
            ("1.23444", "KWD", "1.234"),
        ],
    )
    def test_rounds_to_the_currency_exponent(self, amount, currency, expected):
        assert round_money(Decimal(amount), currency) == Decimal(expected)

    @pytest.mark.parametrize(
        ("amount", "expected"),
        [
            # Banker's rounding: exact halves go to the even digit, so the bias
            # cancels across many lines instead of accumulating.
            ("0.125", "0.12"),
            ("0.135", "0.14"),
            ("2.345", "2.34"),
            ("2.355", "2.36"),
        ],
    )
    def test_exact_halves_round_to_even_not_up(self, amount, expected):
        assert round_money(Decimal(amount), "USD") == Decimal(expected)

    def test_rounding_is_symmetric_for_negative_amounts(self):
        # Refunds are negative. A rounding rule that treats them differently
        # makes a full refund fail to cancel its charge.
        assert round_money(Decimal("-0.125"), "USD") == Decimal("-0.12")
        assert round_money(Decimal("-1234.567"), "JPY") == Decimal("-1235")

    def test_an_already_exact_amount_is_unchanged(self):
        assert round_money(Decimal("10.00"), "USD") == Decimal("10.00")
        assert round_money(Decimal("10"), "JPY") == Decimal("10")

    def test_the_result_carries_the_currency_exponent_as_its_scale(self):
        # Not merely equal to the right number -- shaped like it, so a stored
        # value and a formatted one agree.
        assert str(round_money(Decimal("10"), "USD")) == "10.00"
        assert str(round_money(Decimal("10"), "JPY")) == "10"
        assert str(round_money(Decimal("10"), "KWD")) == "10.000"

    def test_a_float_is_refused(self):
        """Floats are how money stops being exact.

        0.1 + 0.2 is not 0.3 in binary floating point, and a price built from
        floats is wrong before it reaches the rounding function.
        """
        with pytest.raises(CurrencyError):
            round_money(0.1, "USD")  # type: ignore[arg-type]

    def test_a_non_finite_amount_is_refused(self):
        for value in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
            with pytest.raises((CurrencyError, InvalidOperation)):
                round_money(value, "USD")


class TestSummation:
    def test_sums_within_one_currency(self):
        total = sum_money([Decimal("1.005"), Decimal("2.005")], "USD")
        # Rounded once at the end, not per addend: rounding each line first and
        # adding the results is how a total stops matching its own lines.
        assert total == Decimal("3.01")

    def test_refuses_to_add_across_currencies(self):
        # The rule the whole money module exists for.
        with pytest.raises(CurrencyError):
            sum_money([Decimal("1.00")], "ZZZ")

    def test_an_empty_sum_is_zero_at_the_currency_scale(self):
        assert str(sum_money([], "JPY")) == "0"
        assert str(sum_money([], "USD")) == "0.00"

    def test_line_totals_reconcile_with_the_order_total(self):
        """The forty-line case this module exists for.

        Each line is rounded for presentation, and the order total is the sum of
        the *rounded* lines -- because a customer who adds up the receipt must
        get the number at the bottom. Any other convention makes a correct total
        look wrong to the person paying it.
        """
        unit = Decimal("3.334")
        lines = [round_money(unit, "USD") for _ in range(40)]
        assert sum(lines) == Decimal("133.20")
        assert sum_money(lines, "USD") == Decimal("133.20")
