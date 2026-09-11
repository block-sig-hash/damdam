"""Usage ingestion, reconciliation and carrier charging (US-36, chunk 16).

Five things go wrong with supplier usage, and each one has a named method here
rather than a comment somewhere hoping somebody remembers:

1. **A cumulative counter resets.** Reading it as a delta charges the whole
   cycle again on the next poll. `ingest_counter` compares against the previous
   reading and recognises a decrease as a reset — not as negative usage, which
   would credit the customer for bytes they used.
2. **Events arrive late, out of order and twice.** `ingest_event` deduplicates
   on a natural key before anything is counted, and orders by when usage
   *happened* rather than when we heard.
3. **The same bytes arrive from two sources.** A line has one authoritative
   data source; everything from the other is kept as evidence and never
   charged. `AGENTS.md`'s "avoid charging the same data via two sources" is a
   column, not a convention.
4. **Suppliers correct themselves.** `apply_correction` supersedes rather than
   edits, and posts a compensating ledger entry for the difference — the same
   discipline chunk 10 enforces with a trigger.
5. **The poller quietly stops.** A cursor with no visibility is a customer whose
   balance froze and nobody noticed. Cursors have durable watermarks, bounded
   retries, an explicit stalled state and an exception queue entry when they
   reach it.

## Carrier only, deliberately

The approved calling amendment keeps chunks 15–17 on carrier lifecycle, usage
and control, and assigns internet-call metering to V03. Everything ingested here
is `AdapterChannel.CARRIER` and names a carrier line. `usage_records` carries a
`channel` column and a nullable `carrier_line_id` so V03 has somewhere truthful
to put an internet record without migrating these tables — and so that a WebRTC
call record can never be summed into a carrier line's usage, which the amendment
says outright it must not be.

## Provisional is not final, and neither is an unread balance

`prd.md` AC-36.4 forbids presenting a delayed, app-side figure as a guaranteed
one. `allowance` therefore returns *when the number was last observed* and
whether it is fresh, stale or **unknown** — and unknown is the honest state for
a line nobody has ever polled. Returning the granted total for such a line, with
no qualification, is what the assignment means by "refreshing an initialized
database balance is not reconciliation": the number would look like a
measurement and be nothing of the kind.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, text
from sqlmodel import Session, col, select

from app.auth.models import utc_now
from app.catalog.tariffs import (
    DestinationKind,
    OriginKind,
    RateNotFoundError,
    Tariff,
    TariffRate,
    select_rate,
)
from app.connectivity.contract import AdapterChannel
from app.connectivity.models import CarrierLine, Entitlement
from app.ledger.models import AccountKind, Direction, LedgerAccount, OwnerKind
from app.ledger.service import LedgerService, Posting
from app.money import round_money
from app.orders.models import Order, OrderItem
from app.refunds.models import ExceptionItem, ExceptionKind
from app.usage.contract import CounterSnapshot, UsageEvent, UsageKind
from app.usage.models import (
    CounterReading,
    CursorState,
    UsageCursor,
    UsageRecord,
    UsageSource,
    UsageState,
)

#: How stale a reading may be before a customer is told so, when the supplier
#: documents no latency of its own. Telnyx documents none — see
#: `docs/implementation/telnyx/API-CONTRACTS.md` §4 — so this is a product
#: decision rather than a supplier fact, and it is deliberately short: telling
#: somebody a number is current when it is an hour old is the failure.
DEFAULT_STALENESS = timedelta(minutes=15)

#: A poll that has not run for longer than this has missed a window, and the
#: missed window is backfilled rather than skipped. Advancing a watermark past
#: unreported time loses usage no later poll will look for.
DEFAULT_MAX_GAP = timedelta(hours=6)

MAX_CURSOR_FAILURES = 5

#: Records that count against an allowance. `SUPERSEDED` does not (a correction
#: replaced it) and neither does `EVIDENCE` (it is the other source's view of
#: bytes already counted).
COUNTED_STATES = (UsageState.PROVISIONAL, UsageState.FINAL)


class UsageError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


class Freshness(str, Enum):
    """How much a displayed balance can be relied on.

    `UNKNOWN` is not a degraded `STALE`. Stale means we measured and the
    measurement is old; unknown means nobody has ever measured, and the only
    number available is the grant.
    """

    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AllowanceView:
    """What is left, when it was last observed, and how much to trust it."""

    entitlement_id: UUID
    data_bytes_total: int
    data_bytes_used: int
    voice_seconds_total: int
    voice_seconds_used: int
    #: The latest `occurred_to` we have a record for, not the latest poll. A
    #: poll that returned nothing tells you the poller is alive; it does not
    #: make an old measurement newer.
    observed_at: datetime | None
    freshness: Freshness
    expires_at: datetime | None = None
    #: True when some counted usage is still provisional, so the figure may be
    #: revised. The UI is required to say so rather than imply a settled bill.
    has_provisional: bool = False

    @property
    def data_bytes_remaining(self) -> int:
        return max(0, self.data_bytes_total - self.data_bytes_used)

    @property
    def voice_seconds_remaining(self) -> int:
        return max(0, self.voice_seconds_total - self.voice_seconds_used)

    @property
    def is_observed(self) -> bool:
        return self.observed_at is not None


def price_call(
    rate: TariffRate, seconds: int, currency: str
) -> Decimal:
    """Price one call from a pinned rate. Increments and minimum both apply.

    A supplier charging per 60 seconds while we quote per second is a margin
    leak; quoting per 60 while charging per second is a customer overcharge.
    Both directions are recorded on the rate, so both are applied here rather
    than assumed away.

    Rounding to the billed increment happens **before** the multiplication, not
    after: a 61-second call on a 60-second increment is two units, and
    computing `61/60 * rate` and rounding the money instead quietly charges for
    1.0167 units.
    """
    if seconds < 0:
        raise UsageError("negative_duration")
    if seconds == 0:
        return round_money(rate.setup_amount, currency)
    billed_seconds = max(seconds, rate.minimum_seconds)
    increment = rate.increment_seconds
    units = -(-billed_seconds // increment)  # ceiling division
    amount = rate.setup_amount + (
        rate.per_minute_amount * Decimal(units * increment) / Decimal(60)
    )
    return round_money(amount, currency)


class UsageService:
    def __init__(
        self,
        ledger: LedgerService | None = None,
        clock: Callable[[], datetime] = utc_now,
        staleness: timedelta = DEFAULT_STALENESS,
        max_gap: timedelta = DEFAULT_MAX_GAP,
        max_cursor_failures: int = MAX_CURSOR_FAILURES,
    ) -> None:
        self.ledger = ledger
        self.clock = clock
        self.staleness = staleness
        self.max_gap = max_gap
        self.max_cursor_failures = max_cursor_failures

    # --- cursors ----------------------------------------------------------

    def cursor(
        self,
        session: Session,
        provider: str,
        stream: str,
        position_at: datetime,
        scope_reference: str = "",
    ) -> UsageCursor:
        """Get or create the durable watermark for one stream."""
        self._lock(
            session,
            f"usage-cursor:{provider}:{stream}:{scope_reference}",
        )
        existing = session.exec(
            select(UsageCursor).where(
                UsageCursor.provider == provider,
                UsageCursor.stream == stream,
                UsageCursor.scope_reference == scope_reference,
            )
        ).first()
        if existing is not None:
            return existing
        cursor = UsageCursor(
            provider=provider,
            stream=stream,
            scope_reference=scope_reference,
            position_at=position_at,
            state=CursorState.ACTIVE,
            created_at=self.clock(),
        )
        session.add(cursor)
        session.flush()
        return cursor

    def advance(
        self,
        session: Session,
        cursor: UsageCursor,
        covered_to: datetime,
        provider_cursor: str | None = None,
    ) -> UsageCursor:
        """Move the watermark to the end of a window that was actually covered.

        Refuses to move backwards, and refuses to move at all while a backfill
        is open. Both refusals protect the same thing: the watermark's meaning
        is "we have everything before this", and a cursor that jumps forward
        over an uncovered gap makes that false permanently, because nothing ever
        looks behind a watermark again.
        """
        cursor = self._locked_cursor(session, cursor)
        now = self.clock()
        cursor.last_polled_at = now
        cursor.last_success_at = now
        cursor.consecutive_failures = 0
        cursor.last_error = None
        if provider_cursor is not None:
            cursor.provider_cursor = provider_cursor
        if cursor.state is CursorState.BACKFILLING:
            raise UsageError(
                "cursor_backfilling",
                "close the backfill before advancing the live watermark; "
                "advancing now would claim coverage of a window still being "
                "caught up",
            )
        if _aware(covered_to) < _aware(cursor.position_at):
            raise UsageError(
                "cursor_would_move_backwards",
                f"watermark is at {cursor.position_at}, refused {covered_to}",
            )
        cursor.position_at = covered_to
        if cursor.state is CursorState.STALLED:
            cursor.state = CursorState.ACTIVE
        session.add(cursor)
        session.flush()
        return cursor

    def record_failure(
        self, session: Session, cursor: UsageCursor, error: str
    ) -> UsageCursor:
        """Count a failed poll, and stop pretending after enough of them.

        Bounded rather than infinite: a poller retrying forever is a queue that
        never drains and an alert nobody can act on. Reaching the bound raises
        an exception item, because a stalled usage poller is invisible from the
        outside — the balance simply stops moving.
        """
        cursor = self._locked_cursor(session, cursor)
        now = self.clock()
        cursor.last_polled_at = now
        cursor.consecutive_failures += 1
        cursor.last_error = error[:1000]
        if cursor.consecutive_failures >= self.max_cursor_failures:
            cursor.state = CursorState.STALLED
            self.raise_exception(
                session,
                ExceptionKind.USAGE_POLLING_STALLED,
                f"{cursor.provider}:{cursor.stream}:{cursor.scope_reference}",
                f"{cursor.consecutive_failures} consecutive failures; watermark "
                f"stuck at {cursor.position_at}. Last error: {error[:300]}",
            )
        session.add(cursor)
        session.flush()
        return cursor

    def open_backfill(
        self,
        session: Session,
        cursor: UsageCursor,
        window_from: datetime,
        window_to: datetime,
    ) -> UsageCursor:
        cursor = self._locked_cursor(session, cursor)
        if _aware(window_to) <= _aware(window_from):
            raise UsageError("empty_backfill_window")
        cursor.state = CursorState.BACKFILLING
        cursor.backfill_from = window_from
        cursor.backfill_to = window_to
        session.add(cursor)
        session.flush()
        return cursor

    def close_backfill(self, session: Session, cursor: UsageCursor) -> UsageCursor:
        """Finish catching up, and only then move the live watermark.

        The watermark moves to the end of the backfilled window rather than to
        "now": time after the window still has not been covered by anything.
        """
        cursor = self._locked_cursor(session, cursor)
        if cursor.state is not CursorState.BACKFILLING:
            raise UsageError("cursor_not_backfilling")
        window_to = cursor.backfill_to
        cursor.state = CursorState.ACTIVE
        cursor.backfill_from = None
        cursor.backfill_to = None
        if window_to is not None and _aware(window_to) > _aware(cursor.position_at):
            cursor.position_at = window_to
        session.add(cursor)
        session.flush()
        return cursor

    def check_for_missed_window(
        self, session: Session, cursor: UsageCursor, now: datetime | None = None
    ) -> UsageCursor:
        """A poller that stopped for hours has a gap. Backfill it, do not skip it.

        The tempting alternative — start polling from now — makes the system
        look healthy immediately and silently loses every byte in the gap.
        """
        cursor = self._locked_cursor(session, cursor)
        moment = now or self.clock()
        if cursor.state is CursorState.BACKFILLING:
            return cursor
        gap = _aware(moment) - _aware(cursor.position_at)
        if gap <= self.max_gap:
            return cursor
        self.open_backfill(session, cursor, cursor.position_at, moment)
        return cursor

    # --- counter ingestion ------------------------------------------------

    def ingest_counter(
        self, session: Session, line: CarrierLine, snapshot: CounterSnapshot
    ) -> UsageRecord | None:
        """Turn a cumulative reading into a delta, or recognise a reset.

        Returns `None` when the reading is a duplicate of one already stored or
        adds nothing — a poll that finds the counter unchanged is a normal, very
        common event and must not write a zero-quantity record every minute.
        """
        if snapshot.provider_reference != line.carrier_line_reference:
            raise UsageError(
                "provider_line_mismatch",
                "the counter snapshot belongs to a different carrier line",
            )
        self._lock(session, f"usage-counter:{line.carrier}:{line.id}")
        entitlement = self._entitlement(session, line)
        existing_reading = session.exec(
            select(CounterReading).where(
                CounterReading.carrier_line_id == line.id,
                CounterReading.observed_at == snapshot.observed_at,
            )
        ).first()
        if existing_reading is not None:
            if (
                existing_reading.value_bytes != snapshot.consumed_bytes
                or existing_reading.cycle_reference != snapshot.cycle_reference
            ):
                raise UsageError(
                    "counter_reading_conflict",
                    "the provider restated an existing observation timestamp",
                )
            return None

        latest = session.exec(
            select(CounterReading)
            .where(CounterReading.carrier_line_id == line.id)
            .order_by(col(CounterReading.observed_at).desc())
        ).first()

        reading = CounterReading(
            carrier_line_id=line.id,
            value_bytes=snapshot.consumed_bytes,
            cycle_reference=snapshot.cycle_reference,
            observed_at=snapshot.observed_at,
            received_at=self.clock(),
        )
        session.add(reading)
        session.flush()

        # Retain late evidence, but never derive a new delta from a point that
        # predates the watermark already counted. Doing so would count part of
        # the same cumulative total twice.
        if latest is not None and _aware(snapshot.observed_at) < _aware(
            latest.observed_at
        ):
            return None

        previous = latest

        window_from = _aware(
            previous.observed_at if previous is not None else line.created_at
        )
        note: str | None = None
        source = UsageSource.COUNTER

        if previous is None:
            delta = snapshot.consumed_bytes
        elif (
            snapshot.cycle_reference is not None
            and previous.cycle_reference is not None
            and snapshot.cycle_reference != previous.cycle_reference
        ):
            delta = snapshot.consumed_bytes
            source = UsageSource.DERIVED
            note = (
                f"billing cycle changed: {previous.cycle_reference} -> "
                f"{snapshot.cycle_reference}; the new counter is counted in full"
            )
        elif snapshot.consumed_bytes >= previous.value_bytes:
            delta = snapshot.consumed_bytes - previous.value_bytes
        else:
            # The counter went down. Either a new billing cycle started or the
            # supplier is wrong, and Telnyx exposes no cycle boundary to tell
            # them apart. The conservative reading is a reset: everything up to
            # the old value is already counted, and the new value is fresh
            # consumption in a new cycle. Recording the difference as negative
            # usage would credit bytes the customer really used.
            delta = snapshot.consumed_bytes
            source = UsageSource.DERIVED
            note = (
                f"counter reset: {previous.value_bytes} -> "
                f"{snapshot.consumed_bytes} bytes. Prior consumption stands; "
                "the new value is treated as a fresh cycle"
            )
            self.raise_exception(
                session,
                ExceptionKind.USAGE_COUNTER_RESET,
                f"line:{line.id}:{snapshot.observed_at.isoformat()}",
                f"{line.carrier} counter fell from {previous.value_bytes} to "
                f"{snapshot.consumed_bytes}. No billing-cycle boundary is "
                "documented, so this needs checking against supplier billing.",
            )

        if delta == 0:
            return None

        return self._store(
            session,
            line=line,
            entitlement=entitlement,
            kind=UsageKind.DATA,
            source=source,
            # A counter reading is an estimate the next poll may revise. It is
            # never final: the supplier has not settled anything.
            state=UsageState.PROVISIONAL,
            quantity=delta,
            occurred_from=window_from,
            occurred_to=snapshot.observed_at,
            received_at=self.clock(),
            natural_key=f"counter:{line.id}:{snapshot.observed_at.isoformat()}",
            note=note,
        )

    # --- event ingestion --------------------------------------------------

    def ingest_event(
        self,
        session: Session,
        line: CarrierLine,
        event: UsageEvent,
        tariff: Tariff | None = None,
        origin_kind: OriginKind = OriginKind.CARRIER_VISITED_NETWORK,
    ) -> UsageRecord:
        """Record one session or call, once.

        Deduplication happens before anything is counted, and it is idempotent
        rather than an error: a supplier redelivering a record is not a fault,
        and raising on it would turn every replayed page into an incident.

        Late and out-of-order arrivals are ordinary. Nothing here compares the
        event against a watermark, because a watermark is about *coverage*, not
        about whether a record is welcome — rejecting a late CDR is how usage
        goes missing.
        """
        if event.provider_reference != line.carrier_line_reference:
            raise UsageError(
                "provider_line_mismatch",
                "the usage event belongs to a different carrier line",
            )
        entitlement = self._entitlement(session, line)
        natural_key = self.natural_key(event)
        self._lock(session, f"usage-event:{line.carrier}:{natural_key}")
        existing = session.exec(
            select(UsageRecord).where(
                UsageRecord.provider == line.carrier,
                UsageRecord.natural_key == natural_key,
            )
        ).first()
        if existing is not None:
            return existing

        charged_amount: Decimal | None = None
        charged_currency: str | None = None
        tariff_id: UUID | None = None
        if event.kind is UsageKind.VOICE and tariff is not None:
            charged_amount, charged_currency = self.price_event(
                session, event, tariff, origin_kind
            )
            tariff_id = tariff.id

        return self._store(
            session,
            line=line,
            entitlement=entitlement,
            kind=event.kind,
            source=UsageSource.EVENT,
            # A session record is what the supplier will invoice us for. That
            # is as settled as usage gets before an invoice arrives.
            state=UsageState.FINAL,
            quantity=event.quantity,
            occurred_from=event.started_at,
            occurred_to=event.ended_at,
            received_at=event.received_at,
            natural_key=natural_key,
            provider_event_id=event.provider_event_id,
            tariff_id=tariff_id,
            charged_amount=charged_amount,
            charged_currency=charged_currency,
        )

    @staticmethod
    def natural_key(event: UsageEvent) -> str:
        """The deduplication handle, and an honest one about its own limits.

        A supplier id is used when there is one. Telnyx publishes no WDR record
        id — the OpenAPI source documents the report envelope and not the record
        — so the fallback composes the fields that *are* documented: line, start,
        end, quantity.

        That composite is imperfect. Two genuinely distinct sessions with
        identical boundaries and identical volume collapse into one, which
        under-counts. Under-counting in the customer's favour is the right
        direction to be wrong when the supplier will not give us an id, and it
        is recorded here rather than discovered later.
        """
        if event.provider_event_id:
            scope = (
                f"{event.provider_reference}:{event.kind.value}:"
                f"{event.provider_event_id}"
            )
            return f"event:{sha256(scope.encode()).hexdigest()}"
        return (
            f"derived:{event.provider_reference}:{event.kind.value}:"
            f"{event.started_at.isoformat()}:{event.ended_at.isoformat()}:"
            f"{event.quantity}"
        )

    def price_event(
        self,
        session: Session,
        event: UsageEvent,
        tariff: Tariff,
        origin_kind: OriginKind,
    ) -> tuple[Decimal, str]:
        """Price a call from the pinned tariff version, or refuse.

        Refusing is the point of the `RateNotFoundError` re-raise below. A call
        that cannot be priced must not be priced at zero: a free call is a
        commercial decision, and a missing rate is a gap in the rate deck.
        """
        if not event.destination_country or not event.destination_kind:
            raise UsageError(
                "unpriceable_call",
                "a voice record with no destination cannot be priced; pricing "
                "it at zero would give away a call that costs us money",
            )
        rates = session.exec(
            select(TariffRate).where(TariffRate.tariff_id == tariff.id)
        ).all()
        try:
            rate = select_rate(
                list(rates),
                origin_kind,
                event.origin_country,
                event.destination_country,
                DestinationKind(event.destination_kind),
            )
        except RateNotFoundError as exc:
            raise UsageError("rate_not_found", exc.detail) from exc
        return price_call(rate, event.quantity, tariff.currency), tariff.currency

    # --- corrections ------------------------------------------------------

    def apply_correction(
        self,
        session: Session,
        original: UsageRecord,
        corrected_quantity: int,
        reason: str,
        corrected_amount: Decimal | None = None,
    ) -> UsageRecord:
        """Supersede, never edit. The old numbers stay readable.

        A supplier correcting itself is normal, and the wrong response is to
        update the row: "what were they told last week" becomes unanswerable,
        and any ledger entry already posted no longer matches anything.

        The correcting record carries the *corrected* quantity, and the original
        stops counting. Allowance sums exclude `SUPERSEDED`, so the balance
        converges on the corrected figure without ever having double-counted —
        which is what the assignment means by "converges without double debit".
        """
        self._lock(session, f"usage-correction:{original.id}")
        current = session.exec(
            select(UsageRecord)
            .where(UsageRecord.id == original.id)
            .with_for_update()
        ).first()
        if current is None:
            raise UsageError("usage_record_not_found")
        original = current
        if original.state is UsageState.SUPERSEDED:
            raise UsageError(
                "already_superseded",
                "correct the correction, not the record it replaced",
            )
        if corrected_quantity < 0:
            raise UsageError("negative_correction")
        reason = reason.strip()
        if not reason:
            raise UsageError("correction_reason_required")
        if original.charged_amount is not None and corrected_amount is None:
            raise UsageError(
                "correction_charge_required",
                "a charged record must be corrected with its revised charge",
            )
        if original.charged_amount is None and corrected_amount is not None:
            raise UsageError(
                "correction_charge_unexpected",
                "an uncharged record cannot acquire a charge through correction",
            )

        now = self.clock()
        original.state = UsageState.SUPERSEDED
        session.add(original)

        correction = UsageRecord(
            channel=original.channel,
            carrier_line_id=original.carrier_line_id,
            entitlement_id=original.entitlement_id,
            provider=original.provider,
            kind=original.kind,
            source=UsageSource.DERIVED,
            state=UsageState.FINAL,
            provider_event_id=original.provider_event_id,
            natural_key=f"correction:{original.id}",
            quantity=corrected_quantity,
            occurred_from=original.occurred_from,
            occurred_to=original.occurred_to,
            received_at=now,
            tariff_id=original.tariff_id,
            charged_currency=(
                original.charged_currency if corrected_amount is not None else None
            ),
            charged_amount=corrected_amount,
            corrects_id=original.id,
            note=reason[:500],
            created_at=now,
        )
        session.add(correction)
        session.flush()
        return correction

    def settle_charge(
        self,
        session: Session,
        record: UsageRecord,
        debit_account: LedgerAccount,
        credit_account: LedgerAccount,
    ) -> None:
        """Post what a usage record costs, once, under its own event id.

        Idempotent through chunk 10: the business event is derived from the
        record id, so a replayed worker posts nothing new. A correction posts
        under its *own* id and moves only the difference, which is why the
        original entry is never touched.
        """
        if self.ledger is None:
            raise UsageError("no_ledger", "charging needs a ledger service")
        if record.charged_amount is None or record.charged_currency is None:
            raise UsageError("record_has_no_charge")
        if record.state is UsageState.EVIDENCE:
            raise UsageError(
                "evidence_is_not_charged",
                "this record came from the line's non-authoritative source; "
                "charging it would bill the same usage twice",
            )
        if (
            debit_account.currency != record.charged_currency
            or credit_account.currency != record.charged_currency
        ):
            raise UsageError(
                "charge_currency_mismatch",
                "the usage charge and both ledger accounts must share a currency",
            )
        if (
            debit_account.kind is not AccountKind.SERVICE_CREDIT
            or credit_account.kind is not AccountKind.REVENUE
            or credit_account.owner_kind is not OwnerKind.SYSTEM
        ):
            raise UsageError(
                "charge_account_mismatch",
                "usage charges move from service credit to revenue",
            )
        entitlement = session.get(Entitlement, record.entitlement_id)
        item = (
            session.get(OrderItem, entitlement.order_item_id)
            if entitlement is not None
            else None
        )
        order = session.get(Order, item.order_id) if item is not None else None
        if order is None:
            raise UsageError("charge_payer_not_found")
        owns_debit = (
            order.payer_user_id is not None
            and debit_account.owner_kind is OwnerKind.USER
            and debit_account.owner_user_id == order.payer_user_id
        ) or (
            order.payer_organization_id is not None
            and debit_account.owner_kind is OwnerKind.ORGANIZATION
            and debit_account.owner_organization_id == order.payer_organization_id
        )
        if not owns_debit:
            raise UsageError(
                "charge_payer_mismatch",
                "the service-credit account must belong to the order payer",
            )

        amount = record.charged_amount
        if record.corrects_id is not None:
            original = session.get(UsageRecord, record.corrects_id)
            if original is not None and original.charged_amount is not None:
                # Only the difference moves. Reversing and re-posting would put
                # two transactions in the books where one adjustment happened.
                amount = record.charged_amount - original.charged_amount
        if amount == 0:
            return
        direction_pair = (
            (debit_account, credit_account)
            if amount > 0
            else (credit_account, debit_account)
        )
        magnitude = abs(amount)
        self.ledger.post(
            session,
            f"usage:{record.id}:charge",
            [
                Posting(direction_pair[0], Direction.DEBIT, magnitude),
                Posting(direction_pair[1], Direction.CREDIT, magnitude),
            ],
            occurred_at=record.occurred_to,
            reference=f"usage record {record.id}",
        )

    # --- allowance --------------------------------------------------------

    def allowance(
        self, session: Session, entitlement: Entitlement, now: datetime | None = None
    ) -> AllowanceView:
        """What is left, and how much the number can be relied on.

        `EVIDENCE` and `SUPERSEDED` records are excluded from the sums. That is
        the whole of the double-charging defence in one `where` clause: evidence
        is the other source's view of bytes already counted, and a superseded
        record has been replaced.
        """
        moment = _aware(now or self.clock())
        totals = dict(
            session.exec(
                select(UsageRecord.kind, func.sum(UsageRecord.quantity))
                .where(
                    UsageRecord.entitlement_id == entitlement.id,
                    col(UsageRecord.state).in_(COUNTED_STATES),
                )
                .group_by(col(UsageRecord.kind))
            ).all()
        )
        observed_at = session.exec(
            select(func.max(UsageRecord.occurred_to)).where(
                UsageRecord.entitlement_id == entitlement.id,
                col(UsageRecord.state).in_(COUNTED_STATES),
            )
        ).first()
        provisional = session.exec(
            select(func.count())
            .select_from(UsageRecord)
            .where(
                UsageRecord.entitlement_id == entitlement.id,
                UsageRecord.state == UsageState.PROVISIONAL,
            )
        ).first()

        if observed_at is None:
            # Nobody has ever measured this line. The grant is all we have, and
            # presenting it as a measurement is the thing AC-36.4 forbids.
            freshness = Freshness.UNKNOWN
        elif moment - _aware(observed_at) > self.staleness:
            freshness = Freshness.STALE
        else:
            freshness = Freshness.FRESH

        return AllowanceView(
            entitlement_id=entitlement.id,
            data_bytes_total=entitlement.data_bytes_total,
            data_bytes_used=int(totals.get(UsageKind.DATA) or 0),
            voice_seconds_total=entitlement.voice_seconds_total,
            voice_seconds_used=int(totals.get(UsageKind.VOICE) or 0),
            observed_at=_aware(observed_at) if observed_at is not None else None,
            freshness=freshness,
            expires_at=entitlement.expires_at,
            has_provisional=bool(provisional),
        )

    # --- reconciliation against the supplier ------------------------------

    def compare_sources(
        self,
        session: Session,
        line: CarrierLine,
        tolerance_bytes: int = 0,
    ) -> int:
        """Compare the authoritative data total against the evidence total.

        This is the check that catches a supplier billing us for something our
        authoritative source never reported, and it is why evidence records are
        kept rather than dropped. A disagreement raises an exception item; it
        does **not** adjust anything, because deciding which source is right is
        a conversation with the supplier, not an arithmetic default.
        """
        counted = int(
            session.exec(
                select(func.coalesce(func.sum(UsageRecord.quantity), 0)).where(
                    UsageRecord.carrier_line_id == line.id,
                    UsageRecord.kind == UsageKind.DATA,
                    col(UsageRecord.state).in_(COUNTED_STATES),
                )
            ).first()
            or 0
        )
        evidence = int(
            session.exec(
                select(func.coalesce(func.sum(UsageRecord.quantity), 0)).where(
                    UsageRecord.carrier_line_id == line.id,
                    UsageRecord.kind == UsageKind.DATA,
                    UsageRecord.state == UsageState.EVIDENCE,
                )
            ).first()
            or 0
        )
        difference = counted - evidence
        if evidence and abs(difference) > tolerance_bytes:
            self.raise_exception(
                session,
                ExceptionKind.USAGE_DISCREPANCY,
                f"line:{line.id}",
                f"authoritative source reports {counted} bytes; the other "
                f"source reports {evidence}. Difference {difference}. Neither "
                "figure has been adjusted -- which is right is a question for "
                "the supplier.",
            )
        return difference

    # --- tenancy ----------------------------------------------------------

    def records_for_payer(
        self,
        session: Session,
        user_id: UUID | None = None,
        organization_id: UUID | None = None,
    ) -> Sequence[UsageRecord]:
        """Usage scoped to whoever paid for it.

        Joined through the order rather than filtered on a denormalised owner
        column: `AGENTS.md` calls a cross-tenant read a breach rather than a
        bug, and a copied owner id is a thing that can be copied wrongly. The
        join cannot be wrong without the order being wrong.
        """
        if (user_id is None) == (organization_id is None):
            raise UsageError(
                "ambiguous_scope",
                "name exactly one payer; a query that means 'either' returns "
                "both tenants' usage",
            )
        statement = (
            select(UsageRecord)
            .join(Entitlement, col(UsageRecord.entitlement_id) == col(Entitlement.id))
            .join(OrderItem, col(Entitlement.order_item_id) == col(OrderItem.id))
            .join(Order, col(OrderItem.order_id) == col(Order.id))
        )
        if user_id is not None:
            statement = statement.where(Order.payer_user_id == user_id)
        else:
            statement = statement.where(
                Order.payer_organization_id == organization_id
            )
        return session.exec(statement).all()

    # --- shared -----------------------------------------------------------

    def raise_exception(
        self,
        session: Session,
        kind: ExceptionKind,
        subject_reference: str,
        detail: str,
    ) -> ExceptionItem:
        """Put it in front of a human, once.

        Reuses chunk 14's queue rather than building a second one. An operations
        team watching two lists watches neither, and chunk 25 builds its screens
        on this table.
        """
        subject_reference = subject_reference[:200]
        self._lock(session, f"exception:{kind.value}:{subject_reference}")
        existing = session.exec(
            select(ExceptionItem).where(
                ExceptionItem.kind == kind,
                ExceptionItem.subject_reference == subject_reference,
            )
        ).first()
        if existing is not None:
            return existing
        item = ExceptionItem(
            kind=kind,
            subject_reference=subject_reference,
            detail=detail[:1000],
            raised_at=self.clock(),
        )
        session.add(item)
        session.flush()
        return item

    def _entitlement(self, session: Session, line: CarrierLine) -> Entitlement:
        entitlement = session.get(Entitlement, line.entitlement_id)
        if entitlement is None:  # pragma: no cover - FK guarantees this
            raise UsageError("entitlement_not_found")
        return entitlement

    def _locked_cursor(
        self, session: Session, cursor: UsageCursor
    ) -> UsageCursor:
        self._lock(session, f"usage-cursor-id:{cursor.id}")
        current = session.exec(
            select(UsageCursor)
            .where(UsageCursor.id == cursor.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if current is None:
            raise UsageError("usage_cursor_not_found")
        return current

    @staticmethod
    def _lock(session: Session, key: str) -> None:
        """Serialize one logical ingest operation for the transaction.

        The unique constraints remain the final guard. The advisory lock makes
        concurrent redeliveries converge on the existing row instead of making
        one worker fail after both observed the key as absent.
        """
        if session.get_bind().dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
                .bindparams(key=key)
            )

    def _store(
        self,
        session: Session,
        line: CarrierLine,
        entitlement: Entitlement,
        kind: UsageKind,
        source: UsageSource,
        state: UsageState,
        quantity: int,
        occurred_from: datetime,
        occurred_to: datetime,
        received_at: datetime,
        natural_key: str,
        provider_event_id: str | None = None,
        tariff_id: UUID | None = None,
        charged_amount: Decimal | None = None,
        charged_currency: str | None = None,
        note: str | None = None,
    ) -> UsageRecord:
        record = UsageRecord(
            channel=AdapterChannel.CARRIER,
            carrier_line_id=line.id,
            entitlement_id=entitlement.id,
            provider=line.carrier,
            kind=kind,
            source=source,
            state=self._state_for_source(line, kind, source, state),
            provider_event_id=provider_event_id,
            natural_key=natural_key,
            quantity=quantity,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
            received_at=received_at,
            tariff_id=tariff_id,
            charged_amount=charged_amount,
            charged_currency=charged_currency,
            note=note,
            created_at=self.clock(),
        )
        session.add(record)
        session.flush()
        return record

    @staticmethod
    def _state_for_source(
        line: CarrierLine,
        kind: UsageKind,
        source: UsageSource,
        state: UsageState,
    ) -> UsageState:
        """One authoritative data source per line; the other is evidence.

        Voice is untouched by this: there is only ever one voice source, and
        forcing voice through the data source's choice would silence a whole
        stream because a data counter happened to arrive first.
        """
        if kind is not UsageKind.DATA:
            return state
        authoritative = line.authoritative_data_source
        if authoritative is None:
            return state
        # A derived record produced here is a counter reset/cycle boundary. It
        # still has counter provenance for authoritative-source purposes; only
        # corrections are source-independent, and they bypass `_store`.
        provenance = (
            UsageSource.COUNTER if source is UsageSource.DERIVED else source
        )
        if provenance.value != authoritative:
            return UsageState.EVIDENCE
        return state


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
