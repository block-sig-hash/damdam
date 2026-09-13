"""What the customer is charged for, derived from provider legs and nothing else.

Two pure functions, and the reason both are pure is the same reason
`policy.py` is: a billing rule that needs a database round trip is a rule
somebody eventually approximates on a fast path, and the approximation of a
billing rule is a wrong invoice.

The amendment's constraints show up here as code rather than as comments:

- **The destination leg is the only billable clock.** Summing leg durations is
  named as a defect (*"do not sum leg durations as customer talk time"*): the
  client leg and the destination leg describe **one** conversation from two
  ends, and adding them charges twice for it.
- **Client elapsed time is never billing truth.** No argument here comes from a
  handset. The browser can close, the app can be killed, and the numbers below
  do not move.
- **Unknown is not zero.** A leg we have not seen end is unmetered liability,
  and `MeteringOutcome.INCOMPLETE` exists so that a caller cannot accidentally
  treat "we do not know yet" as "it was free". The reservation stays held.

Supplier cost is a different number entirely, reconciled separately: V01's
worksheet establishes the published unit prices and explicitly *not* how many
billable components a call produces, so nothing here pretends to know what the
call cost us.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.calling.contract import LegRole, LegState
from app.calling.models import CallLeg
from app.calling.pricing import billable_seconds
from app.money import round_money


class MeteringError(Exception):
    """A call whose legs cannot be metered as they stand."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


class MeteringOutcome(str, Enum):
    """What the legs say happened, in the only four shapes that matter."""

    #: A destination leg answered and ended. This is the one that bills.
    ANSWERED = "answered"
    #: Nobody picked up, or the provider rejected it. Nothing is charged.
    NOT_ANSWERED = "not_answered"
    #: A destination leg is still open, or answered with no end recorded.
    #: Liability is not final, so neither is the charge.
    INCOMPLETE = "incomplete"
    #: More than one destination leg answered on one attempt. That is a
    #: duplicate billable leg, which is an incident rather than a long call.
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class TalkInterval:
    """Authoritative talk time, or the reason there is not one yet."""

    outcome: MeteringOutcome
    #: Whole seconds, rounded up from any positive fraction. `None` whenever the
    #: outcome is not one that can be billed — deliberately not `0`, so that a
    #: caller reading this field has to notice the difference.
    seconds: int | None

    @property
    def is_billable(self) -> bool:
        return self.outcome is MeteringOutcome.ANSWERED


@dataclass(frozen=True)
class MeteredCharge:
    """The retail amount for one attempt, split so a receipt can explain it."""

    billable_seconds: int
    setup_amount: Decimal
    usage_amount: Decimal
    total: Decimal


def talk_interval(legs: Iterable[CallLeg]) -> TalkInterval:
    """Read one conversation's billable duration out of its provider legs.

    The client leg is examined only to be excluded. It is evidence that someone
    was on the line, and evidence is not an invoice.
    """
    destination: Sequence[CallLeg] = [
        leg for leg in legs if leg.role is LegRole.DESTINATION
    ]
    for leg in destination:
        if (
            leg.answered_at is not None
            and leg.ended_at is not None
            and leg.ended_at < leg.answered_at
        ):
            raise MeteringError(
                "negative_duration",
                f"leg {leg.provider_call_control_id} ended before it answered",
            )

    answered = [leg for leg in destination if leg.answered_at is not None]
    if len(answered) > 1:
        # Not a judgement call: one authorized attempt funded one destination
        # leg, so a second answered leg is either a duplicate PSTN call or a
        # correlation error, and both need a person.
        return TalkInterval(MeteringOutcome.AMBIGUOUS, None)

    if answered:
        leg = answered[0]
        answered_at, ended_at = leg.answered_at, leg.ended_at
        if answered_at is None or ended_at is None:
            return TalkInterval(MeteringOutcome.INCOMPLETE, None)
        elapsed = (ended_at - answered_at).total_seconds()
        # Round the raw interval up: a 400ms conversation is not a zero-second
        # one, and the tariff's minimum is applied to whole seconds.
        return TalkInterval(MeteringOutcome.ANSWERED, math.ceil(elapsed))

    unfinished = [
        leg
        for leg in destination
        if leg.ended_at is None and leg.state is not LegState.ENDED
    ]
    if unfinished:
        return TalkInterval(MeteringOutcome.INCOMPLETE, None)
    return TalkInterval(MeteringOutcome.NOT_ANSWERED, 0)


def charge_for(
    *,
    seconds: int,
    per_minute_amount: Decimal,
    setup_amount: Decimal,
    minimum_seconds: int,
    increment_seconds: int,
    currency: str,
) -> MeteredCharge:
    """Price talk time at the rate the attempt froze when it was authorized.

    Every rate argument is passed in, never looked up. That is what makes a
    tariff change mid-call a non-event: this function cannot see the new rate,
    so it cannot apply it, and the immutable snapshot on the attempt is the only
    thing that can reach it.

    Rounding is **half-even**, unlike `estimate_max_charge`'s deliberate ceiling.
    A hold has to cover what follows, so it rounds up; a settlement is what
    actually happened, and rounding it up every time is charging a fraction of a
    minor unit for nothing, several million times.
    """
    if seconds < 0:
        raise MeteringError("negative_duration", "duration cannot be negative")

    if seconds == 0:
        # A call that never connected is not a sale, so it carries no setup fee
        # either. Charging one would bill a customer for a number that rang.
        zero = round_money(Decimal(0), currency)
        return MeteredCharge(0, zero, zero, zero)

    units = billable_seconds(
        seconds,
        minimum_seconds=minimum_seconds,
        increment_seconds=increment_seconds,
    )
    usage = round_money(
        (Decimal(units) / Decimal(60)) * per_minute_amount, currency
    )
    setup = round_money(setup_amount, currency)
    return MeteredCharge(units, setup, usage, round_money(setup + usage, currency))
