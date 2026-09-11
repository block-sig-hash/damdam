"""What a carrier can tell us about consumption, and in which of two shapes.

US-36, chunk 16. There are exactly two ways suppliers report usage, and they are
not interchangeable:

**Counter** — "this line has used 2,049 MB this cycle". It is cumulative and it
**resets**. Treating a reading as a delta charges the whole cycle again, every
single poll.

**Events** — "session from 10:02 to 10:14 used 41 MB". They arrive **late, out
of order and twice**. Summing them naively double-charges.

Telnyx offers both — `current_billing_period_consumed_data` on the SIM card, and
Wireless Detail Records via an asynchronous report — and neither is documented
well enough to use blindly. The counter's cycle boundary is not exposed; the WDR
**record** schema is not published at all, so there is no documented unique
record id to deduplicate on. Both facts are recorded in
`docs/implementation/telnyx/API-CONTRACTS.md` §4.

So this module's job is to make the two shapes explicit and to refuse to blur
them. A supplier that reports both is not two sources of truth: it is one source
of truth and one source of evidence, and which is which is a decision recorded
per line rather than a coincidence of whichever poll ran first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol


class UsageKind(str, Enum):
    DATA = "data"
    VOICE = "voice"


class ReportState(str, Enum):
    """Telnyx's documented WDR report statuses, verbatim.

    `DELETED` is here because a report can be removed while we are polling it,
    and a poller that treats an unrecognised status as "keep waiting" waits
    forever on a report that is never coming.
    """

    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"
    DELETED = "deleted"


@dataclass(frozen=True)
class CounterSnapshot:
    """One cumulative reading, as the supplier reports it.

    `cycle_reference` is what separates "the counter went down because a new
    billing cycle started" from "the counter went down because something is
    wrong". When a supplier does not expose it — and Telnyx does not — it is
    `None`, and the reset handling has to be conservative rather than clever.
    """

    provider_reference: str
    consumed_bytes: int
    observed_at: datetime
    #: The supplier's own name for the billing period this counter covers.
    #: `None` when undocumented, which is the Telnyx case today.
    cycle_reference: str | None = None
    #: The supplier's configured cap, when it reports one.
    limit_bytes: int | None = None


@dataclass(frozen=True)
class UsageEvent:
    """One session or call, as the supplier describes it.

    `provider_event_id` is optional because not every supplier issues one, and
    pretending otherwise is how a deduplication key gets invented from fields
    that were never unique. `natural_key` is the fallback: a deterministic
    composite the ingester builds from the fields the supplier *does* document.
    """

    provider_reference: str
    kind: UsageKind
    #: Bytes for data, seconds for voice. One unit per kind, exact integers.
    quantity: int
    started_at: datetime
    ended_at: datetime
    #: When the supplier's record reached us, not when the session happened.
    #: The gap between them is the latency a customer's balance is stale by.
    received_at: datetime
    provider_event_id: str | None = None
    #: Where the call went, for voice. Needed to select a tariff rate.
    destination_country: str | None = None
    destination_kind: str | None = None
    #: The visited network, for a roaming-origin rate.
    origin_country: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class UsageReport:
    """An asynchronous batch of events, and whether it is finished.

    `cursor` carries the supplier's own pagination handle. It is opaque on
    purpose: a poller that reconstructs pagination from offsets loses records
    the moment the supplier's ordering changes underneath it.
    """

    state: ReportState
    events: tuple[UsageEvent, ...] = ()
    cursor: str | None = None
    #: The window the report actually covers, which may be narrower than what
    #: was asked for. Advancing a watermark past unreported time loses usage.
    covers_from: datetime | None = None
    covers_to: datetime | None = None


class UsageAdapter(Protocol):
    """The usage half of a carrier, kept separate from the lifecycle half.

    A separate Protocol rather than more methods on `ConnectivityAdapter`
    because the two capabilities are genuinely independent: a supplier can
    provision lines it cannot report usage for, and chunk 15's
    `Capability.USAGE_COUNTER` / `USAGE_EVENTS` already say so. Code that needs
    usage asks for this type and gets a compile-time answer instead of an
    `AttributeError` at three in the morning.
    """

    name: str

    def fetch_usage_counter(self, provider_reference: str) -> CounterSnapshot | None:
        """The line's cumulative consumption, or `None` if unavailable."""
        ...

    def request_usage_report(
        self, start: datetime, end: datetime
    ) -> str:
        """Ask for a batch covering a window. Returns the supplier's handle."""
        ...

    def fetch_usage_report(
        self, handle: str, cursor: str | None = None
    ) -> UsageReport:
        """Poll a requested batch. May be `PENDING` for a long time."""
        ...
