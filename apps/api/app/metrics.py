"""The five numbers somebody is woken up for (US-42, chunk 26C).

An observability chunk can produce a dashboard nobody reads. The assignment asks
for something narrower and more useful: *actionable* metrics. Each of these
answers a question an operator would otherwise answer by running SQL at three in
the morning, and each has an obvious action attached.

- `oldest_unprovisioned_order_seconds` — is anyone paid-for and waiting?
  Fulfilment has stalled; check the outbox and the supplier.
- `unknown_supplier_outcomes` — purchases that lost their answer. Reconcile
  them (chunk 11); **never** retry.
- `unknown_call_outcomes` — the same, for calls.
- `webhook_lag_seconds` — when a provider last reached us. Signing, networking
  or the provider itself.
- `quarantined_events` — events that contradicted our records. A security
  signal, not a backlog.
- `usage_staleness_seconds` — how old our newest reading is. A stalled poller
  means balances have stopped moving.
- `open_exceptions` — what is waiting for a human, by kind.

## Carrier and calling are counted separately, deliberately

The calling amendment requires call-control and reconciliation failures to be
observed *separately from carrier events*, and it is right to insist. They share
a supplier and nothing else: a stalled eSIM issuance and a lost call outcome need
different people, different runbooks and different urgency. One combined
"unknown outcomes" number would be green while either half was on fire.

## Nothing here is cached

Every value is a query against the live database, because a cached metric is a
metric that can be wrong in exactly the situation it exists for. The queries are
indexed lookups over small result sets — counts and one `MIN` — and the endpoint
is admin-only and not on any customer path.

## Absence is reported as absence

Every "oldest" and "lag" figure is `None` when there is nothing to measure, and
`None` is **not** zero. A system with no usage readings at all and a system whose
readings are perfectly fresh are the same number otherwise, and they could not be
more different.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.auth.models import utc_now
from app.calling.models import AttemptState, CallAttempt, CallEvent, EventDisposition
from app.fulfilment.models import AttemptOutcome, SupplierAttempt
from app.orders.models import Order, OrderItem, PaymentState, ProvisioningState
from app.refunds.models import ExceptionItem
from app.usage.models import CounterReading


@dataclass(frozen=True)
class OperationalMetrics:
    """One observation of the system, at one moment."""

    observed_at: datetime
    #: Age of the oldest paid order with an unprovisioned item. `None` when
    #: every paid order has been fulfilled — not zero, which would mean one was
    #: placed this instant.
    oldest_unprovisioned_order_seconds: float | None
    #: Supplier purchases whose outcome was lost. These are reconciled against
    #: the original operation reference, never retried.
    unknown_supplier_outcomes: int
    #: The same for calls, counted apart from carrier work on purpose.
    unknown_call_outcomes: int
    #: Seconds since the most recent provider event arrived. `None` when none
    #: ever has.
    webhook_lag_seconds: float | None
    #: Events that contradicted our records. A security signal, not a backlog.
    quarantined_events: int
    #: Events stored with no attempt matched. Ordinary in a race; a problem in
    #: bulk.
    unmatched_events: int
    #: Seconds since the newest counter reading. `None` when nothing has ever
    #: been observed, which is not the same as fresh.
    usage_staleness_seconds: float | None
    #: Unresolved exception items, by kind.
    open_exceptions: dict[str, int] = field(default_factory=dict)

    @property
    def open_exception_total(self) -> int:
        return sum(self.open_exceptions.values())


def collect_metrics(
    session: Session, clock: Callable[[], datetime] = utc_now
) -> OperationalMetrics:
    """Read every metric in one pass. Cheap, uncached and honest."""
    now = clock()
    return OperationalMetrics(
        observed_at=now,
        oldest_unprovisioned_order_seconds=_age(
            now, _oldest_unprovisioned_order(session)
        ),
        unknown_supplier_outcomes=_count(
            session,
            select(func.count())
            .select_from(SupplierAttempt)
            .where(col(SupplierAttempt.outcome) == AttemptOutcome.OUTCOME_UNKNOWN),
        ),
        unknown_call_outcomes=_count(
            session,
            select(func.count())
            .select_from(CallAttempt)
            .where(col(CallAttempt.state) == AttemptState.UNKNOWN),
        ),
        webhook_lag_seconds=_age(now, _latest(session, col(CallEvent.received_at))),
        quarantined_events=_count(
            session,
            select(func.count())
            .select_from(CallEvent)
            .where(col(CallEvent.disposition) == EventDisposition.QUARANTINED),
        ),
        unmatched_events=_count(
            session,
            select(func.count())
            .select_from(CallEvent)
            .where(col(CallEvent.disposition) == EventDisposition.UNMATCHED),
        ),
        usage_staleness_seconds=_age(
            now, _latest(session, col(CounterReading.observed_at))
        ),
        open_exceptions=_open_exceptions(session),
    )


def render_prometheus(metrics: OperationalMetrics) -> str:
    """The same numbers in Prometheus text format.

    A missing value is **omitted**, not exported as zero or as `-1`. Prometheus
    treats an absent series and a zero series differently, and that difference is
    exactly the "nothing has been observed" versus "observed, and fresh"
    distinction this module refuses to collapse everywhere else.
    """
    lines: list[str] = []

    def gauge(name: str, value: float | int | None, help_text: str) -> None:
        lines.append(f"# HELP damdam_{name} {help_text}")
        lines.append(f"# TYPE damdam_{name} gauge")
        if value is not None:
            lines.append(f"damdam_{name} {value}")

    gauge(
        "oldest_unprovisioned_order_seconds",
        metrics.oldest_unprovisioned_order_seconds,
        "Age of the oldest paid order still awaiting provisioning.",
    )
    gauge(
        "unknown_supplier_outcomes",
        metrics.unknown_supplier_outcomes,
        "Supplier attempts whose outcome was lost. Reconcile; never retry.",
    )
    gauge(
        "unknown_call_outcomes",
        metrics.unknown_call_outcomes,
        "Call attempts whose outcome was lost. Counted apart from carrier work.",
    )
    gauge(
        "webhook_lag_seconds",
        metrics.webhook_lag_seconds,
        "Seconds since the most recent provider event arrived.",
    )
    gauge(
        "quarantined_events",
        metrics.quarantined_events,
        "Provider events that contradicted our records. A security signal.",
    )
    gauge(
        "unmatched_events",
        metrics.unmatched_events,
        "Provider events stored with no matching attempt.",
    )
    gauge(
        "usage_staleness_seconds",
        metrics.usage_staleness_seconds,
        "Seconds since the newest counter reading. Absent means never observed.",
    )
    lines.append("# HELP damdam_open_exceptions Unresolved exception items by kind.")
    lines.append("# TYPE damdam_open_exceptions gauge")
    for kind, count in sorted(metrics.open_exceptions.items()):
        lines.append(f'damdam_open_exceptions{{kind="{kind}"}} {count}')
    return "\n".join(lines) + "\n"


# --- internals -------------------------------------------------------------


def _count(session: Session, statement: Any) -> int:
    return int(session.exec(statement).one() or 0)


def _latest(session: Session, column: Any) -> datetime | None:
    value = session.exec(select(func.max(column))).one()
    return value if isinstance(value, datetime) else None


def _oldest_unprovisioned_order(session: Session) -> datetime | None:
    """The oldest paid order that still owes somebody a service.

    Joined through `order_items` rather than read off the order, because an
    order is a basket: one provisioned line does not discharge it, and a
    per-order status column would have to be maintained in lockstep with the
    items to stay true.
    """
    statement = (
        select(func.min(col(Order.placed_at)))
        .select_from(Order)
        .join(OrderItem, col(OrderItem.order_id) == col(Order.id))
        .where(col(Order.payment_state) == PaymentState.PAID)
        .where(
            col(OrderItem.provisioning_state).in_(
                [
                    # Everything that still owes the customer something.
                    # `FAILED` and `CANCELLED` are excluded: they are closed,
                    # and counting them would make this number un-actionable —
                    # it would never return to zero after a single bad order.
                    ProvisioningState.NOT_STARTED,
                    ProvisioningState.REQUESTED,
                    ProvisioningState.OUTCOME_UNKNOWN,
                ]
            )
        )
    )
    value = session.exec(statement).one()
    return value if isinstance(value, datetime) else None


def _open_exceptions(session: Session) -> dict[str, int]:
    rows = session.exec(
        select(col(ExceptionItem.kind), func.count())
        .where(col(ExceptionItem.resolved_at).is_(None))
        .group_by(col(ExceptionItem.kind))
    ).all()
    return {getattr(kind, "value", str(kind)): int(count) for kind, count in rows}


def _age(now: datetime, moment: datetime | None) -> float | None:
    """Seconds since `moment`, or `None`. Never negative.

    A clock that disagrees with the database's produces a negative age, and a
    negative age rendered on a dashboard looks like a bug in the dashboard
    rather than the clock skew it is. Clamped to zero, which is the honest floor.
    """
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=now.tzinfo)
    return max(0.0, round((now - moment).total_seconds(), 3))
