"""Turning a tariff and a duration into the amount to reserve.

Two functions, both pure, both about the same question: how much could this call
cost us before we have any way to stop it? The answer is what gets held in the
ledger, and getting it wrong in either direction is a defect:

- **too low** and the call is under-reserved. The shortfall surfaces at
  settlement, when the money has already been spent and there is nothing left to
  hold. That is how a prepaid product goes negative.
- **too high** and the customer cannot start a call they can afford. Less
  damaging, and recoverable — the unused hold is released the moment the call
  ends — which is why the rounding below is deliberately asymmetric.

This estimates **retail exposure**, what the customer could be charged. Supplier
cost is a different number reconciled separately (V01 §8: the number of billable
supplier components per call is unproven for this topology), and V03 owns it.
Nothing here is a settlement.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

from app.money import round_money


def billable_seconds(
    seconds: int, *, minimum_seconds: int, increment_seconds: int
) -> int:
    """Apply the tariff's minimum and rounding increment, in that order.

    Order is not interchangeable. A 30-second minimum under 60-second increments
    bills a 5-second call as 60, not 30: the minimum raises the duration and the
    increment then rounds *that*. Applying them the other way round would let a
    tariff advertise 60-second increments and charge a 30-second unit.
    """
    if seconds < 0:
        raise ValueError("duration cannot be negative")
    if increment_seconds < 1:
        raise ValueError("increment must be at least one second")
    effective = max(seconds, minimum_seconds)
    whole, remainder = divmod(effective, increment_seconds)
    return (whole + 1) * increment_seconds if remainder else whole * increment_seconds


def estimate_max_charge(
    *,
    seconds: int,
    per_minute_amount: Decimal,
    setup_amount: Decimal,
    minimum_seconds: int,
    increment_seconds: int,
    currency: str,
) -> Decimal:
    """The most this call can cost at this rate, rounded **up** to the currency.

    `round_money` rounds half-even, which is right for settling an amount that
    has actually happened and wrong for a hold: half-even rounds down half the
    time, and a hold rounded down is a hold that does not cover the settlement it
    exists for. So the metered part is computed at full precision and taken to
    the currency's scale with `ROUND_CEILING`.

    The overshoot is at most one minor unit and it is released, not charged.
    """
    if seconds < 0:
        raise ValueError("duration cannot be negative")
    units = Decimal(
        billable_seconds(
            seconds,
            minimum_seconds=minimum_seconds,
            increment_seconds=increment_seconds,
        )
    ) / Decimal(60)
    exact = setup_amount + (units * per_minute_amount)
    # Quantize to the currency's own scale by rounding a stored amount up.
    # `round_money` establishes the scale; `ROUND_CEILING` chooses the direction.
    scale = round_money(Decimal("1"), currency)
    quantum = scale.as_tuple().exponent
    assert isinstance(quantum, int)  # `round_money` never returns a special value
    return exact.quantize(Decimal(1).scaleb(quantum), rounding=ROUND_CEILING)
