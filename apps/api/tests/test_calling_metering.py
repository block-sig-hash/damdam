"""Metering: what the customer is charged for, derived from provider legs only.

Every case here is one of the things the amendment forbids or the go/no-go
worksheet leaves unproven. Nothing in this file touches a database: if a rule
needs a session to decide what a call cost, the rule is in the wrong place.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.calling.contract import LegRole, LegState
from app.calling.metering import (
    MeteringError,
    MeteringOutcome,
    charge_for,
    talk_interval,
)
from app.calling.models import CallLeg

START = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)


def leg(
    role: LegRole,
    *,
    answered: int | None = None,
    ended: int | None = None,
    state: LegState = LegState.ENDED,
) -> CallLeg:
    return CallLeg(
        attempt_id=None,
        role=role,
        provider="telnyx",
        provider_call_control_id=f"cc-{role.value}-{answered}-{ended}",
        state=state,
        started_at=START,
        answered_at=(
            START + timedelta(seconds=answered) if answered is not None else None
        ),
        ended_at=(
            START + timedelta(seconds=ended) if ended is not None else None
        ),
        created_at=START,
    )


class TestTalkInterval:
    def test_the_destination_leg_is_the_only_billable_clock(self) -> None:
        """The client leg is evidence. Billing it is billing the same call twice."""
        legs = [
            leg(LegRole.CLIENT, answered=0, ended=200),
            leg(LegRole.DESTINATION, answered=10, ended=130),
        ]
        interval = talk_interval(legs)
        assert interval.seconds == 120
        assert interval.outcome is MeteringOutcome.ANSWERED

    def test_leg_durations_are_never_summed(self) -> None:
        """`VOICE-EXPANSION.md`: do not sum leg durations as customer talk time."""
        legs = [
            leg(LegRole.CLIENT, answered=0, ended=200),
            leg(LegRole.DESTINATION, answered=10, ended=130),
        ]
        assert talk_interval(legs).seconds != 200 + 120

    def test_a_call_nobody_answered_is_not_talk_time(self) -> None:
        legs = [
            leg(LegRole.CLIENT, answered=0, ended=45),
            leg(LegRole.DESTINATION, ended=45),
        ]
        interval = talk_interval(legs)
        assert interval.seconds == 0
        assert interval.outcome is MeteringOutcome.NOT_ANSWERED

    def test_a_destination_leg_still_running_cannot_be_metered(self) -> None:
        """A missing terminal event is unknown liability, not a zero-second call."""
        legs = [leg(LegRole.DESTINATION, answered=10, state=LegState.ANSWERED)]
        interval = talk_interval(legs)
        assert interval.outcome is MeteringOutcome.INCOMPLETE
        assert interval.seconds is None

    def test_no_destination_leg_at_all_is_incomplete_not_free(self) -> None:
        """An attempt that reached the provider and produced nothing we can see."""
        legs = [leg(LegRole.CLIENT, answered=0, ended=12)]
        assert talk_interval(legs).outcome is MeteringOutcome.NOT_ANSWERED

    def test_a_second_answered_destination_leg_is_refused_not_summed(self) -> None:
        """Two answered destination legs on one attempt is a duplicate PSTN leg.

        Summing them would bill a customer for a second call they did not
        authorize; picking one silently would hide it. The caller raises it.
        """
        legs = [
            leg(LegRole.DESTINATION, answered=10, ended=70),
            leg(LegRole.DESTINATION, answered=100, ended=160),
        ]
        interval = talk_interval(legs)
        assert interval.outcome is MeteringOutcome.AMBIGUOUS
        assert interval.seconds is None

    def test_an_unanswered_second_leg_does_not_make_it_ambiguous(self) -> None:
        legs = [
            leg(LegRole.DESTINATION, ended=20),
            leg(LegRole.DESTINATION, answered=30, ended=90),
        ]
        interval = talk_interval(legs)
        assert interval.outcome is MeteringOutcome.ANSWERED
        assert interval.seconds == 60

    def test_a_leg_that_ended_before_it_answered_is_refused(self) -> None:
        """The database constraint prevents this; metering does not assume it."""
        bad = leg(LegRole.DESTINATION, answered=100, ended=40)
        with pytest.raises(MeteringError) as excinfo:
            talk_interval([bad])
        assert excinfo.value.code == "negative_duration"

    def test_sub_second_talk_time_rounds_up_to_a_second(self) -> None:
        one = leg(LegRole.DESTINATION, answered=10, ended=10)
        one.ended_at = START + timedelta(seconds=10, milliseconds=400)
        assert talk_interval([one]).seconds == 1


class TestChargeFor:
    RATE = {
        "per_minute_amount": Decimal("0.0450000000"),
        "setup_amount": Decimal("0.010000"),
        "minimum_seconds": 30,
        "increment_seconds": 60,
        "currency": "NGN",
    }

    def test_an_answered_call_pays_setup_plus_rounded_minutes(self) -> None:
        charge = charge_for(seconds=61, **self.RATE)
        # 61s -> 120 billable seconds -> 2 minutes at 0.045 = 0.09, plus setup.
        assert charge.billable_seconds == 120
        assert charge.usage_amount == Decimal("0.09")
        assert charge.setup_amount == Decimal("0.01")
        assert charge.total == Decimal("0.10")

    def test_the_minimum_applies_before_the_increment(self) -> None:
        charge = charge_for(seconds=5, **self.RATE)
        assert charge.billable_seconds == 60

    def test_an_unanswered_call_pays_nothing_at_all(self) -> None:
        """No talk time, no setup fee. A call that did not connect is not a sale."""
        charge = charge_for(seconds=0, **self.RATE)
        assert charge.billable_seconds == 0
        assert charge.usage_amount == Decimal("0")
        assert charge.setup_amount == Decimal("0")
        assert charge.total == Decimal("0")

    def test_settlement_rounds_half_even_not_up(self) -> None:
        """A hold rounds up because it must cover; a settlement rounds fairly.

        Half a minute at 0.01/min is exactly 0.005 -- the case where the two
        rounding rules disagree. `estimate_max_charge` takes it to 0.01 because
        a hold that does not cover its settlement is not a hold; this takes it
        to 0.00, because rounding every half-unit up is a systematic charge for
        nothing.
        """
        charge = charge_for(
            seconds=30,
            per_minute_amount=Decimal("0.0100000000"),
            setup_amount=Decimal("0.000000"),
            minimum_seconds=30,
            increment_seconds=30,
            currency="NGN",
        )
        assert charge.usage_amount == Decimal("0.00")

    def test_the_snapshot_rate_is_the_only_rate(self) -> None:
        """Two calls at two versions of a tariff charge their own version.

        A rate change mid-call cannot reach this function: it takes the numbers
        the attempt froze at authorization and has no way to look up another.
        """
        cheap = {**self.RATE, "per_minute_amount": Decimal("0.04")}
        dear = {**self.RATE, "per_minute_amount": Decimal("0.08")}
        old = charge_for(seconds=60, **cheap)
        new = charge_for(seconds=60, **dear)
        assert old.usage_amount == Decimal("0.04")
        assert new.usage_amount == Decimal("0.08")

    def test_negative_duration_is_refused(self) -> None:
        with pytest.raises(MeteringError):
            charge_for(seconds=-1, **self.RATE)
