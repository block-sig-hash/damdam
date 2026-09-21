"""What an organization has, may spend, and actually used (US-40, chunk 24).

Three questions that look like one and are not, which is why this module keeps
them apart:

**What do we have?** Service credit in the ledger — a balance, an amount held
against commitments, and what is left. That is one number per currency and it is
authoritative, because the ledger is where money lives.

**What may we spend?** A recorded policy cap, minus what has already gone. This
is *not* the same as having the money: an organization can hold ten million in
credit and have a departmental cap of fifty thousand, and it is also not the
same as a supplier pooling anything. Which brings us to the distinction the
assignment insists on.

**What did we use?** Usage and charges, aggregated by team and cost centre. This
is the number that arrives late, and therefore the one that must carry its own
freshness.

## Service credit, allowances and pooling are three different things

The assignment: *clearly distinguish organization service credit, per-line
allowances and any actual supplier pooling capability.* They are routinely
conflated, and the conflation sells something nobody can deliver:

- **Service credit** is money with us. Real, ours to account for, and spendable
  on anything we sell.
- **A per-line allowance** is what one line may consume — bytes and seconds
  granted by a product. It is not money and it does not move between lines.
- **Pooling** is a *carrier* capability: several lines drawing from one bucket
  of data at the network. We do not have it. Chunk 15's adapter does not
  advertise it, chunk 16 found no supplier evidence for it, and a dashboard that
  showed "shared 500GB" would be describing an arrangement that does not exist.

`FundingSummary.pooling` says so in a field rather than in a comment, so a client
cannot render a pooled balance by accident.

## Freshness is part of the number

Usage arrives late and sometimes stops arriving. A departmental total rendered
without saying when it was last updated is a number an administrator will treat
as now — and the day the poller stalls is the day they plan around a figure that
stopped moving last Tuesday. Every report carries `observed_through`, and it is
`None` when nothing has been observed at all, which is different from zero.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_
from sqlmodel import Session, col, select

from app.auth.models import utc_now
from app.bulk.models import BulkJobItem
from app.catalog.models import Product
from app.connectivity.models import Entitlement
from app.controls.models import OrganizationSpendingPolicy
from app.ledger.models import AccountKind, OwnerKind
from app.ledger.service import LedgerService
from app.money import round_money
from app.orders.models import Order, OrderItem
from app.people.models import (
    OrganizationCostCentre,
    OrganizationPerson,
    OrganizationTeam,
)
from app.usage.models import UsageRecord, UsageState


@dataclass(frozen=True)
class FundingSummary:
    """What an organization has and may spend, with the three kinds kept apart."""

    currency: str
    #: Money with us. The ledger's answer, not a cached one.
    balance: Decimal
    #: Committed to something — a bulk order's holds, a pending top-up.
    held: Decimal
    available: Decimal
    #: The recorded cap for this period, or `None` when nobody has set one.
    #: `None` is not "unlimited" and not zero; it is "undecided", and a screen
    #: must say so rather than rendering infinity.
    period_cap: Decimal | None = None
    spent_this_period: Decimal = Decimal(0)
    #: Whether a supplier can pool allowance across this organization's lines.
    #: **False, and not a placeholder.** No adapter advertises pooling and no
    #: evidence for it exists; a client must not render a shared bucket.
    pooling: bool = False
    pooling_note: str = (
        "Allowances belong to individual lines. No supplier pooling capability "
        "is available or claimed."
    )

    @property
    def headroom(self) -> Decimal | None:
        if self.period_cap is None:
            return None
        return self.period_cap - self.spent_this_period


@dataclass(frozen=True)
class DepartmentTotal:
    """One team or cost centre's spend, and what it is made of."""

    key: str
    label: str
    people: int
    lines: int
    #: What was purchased — order items, at the price recorded on them.
    purchased_amount: Decimal
    #: What was metered — usage charged to those lines. Arrives late.
    usage_amount: Decimal
    currency: str


@dataclass(frozen=True)
class DepartmentalReport:
    organization_id: UUID
    currency: str
    period_from: datetime
    period_to: datetime
    totals: Sequence[DepartmentTotal] = field(default_factory=tuple)
    #: The latest usage observation covering this organization's lines. `None`
    #: means nothing has been observed — which is different from zero used, and
    #: a screen that shows one as the other is lying about a stalled poller.
    observed_through: datetime | None = None

    @property
    def purchased_total(self) -> Decimal:
        return sum(
            (total.purchased_amount for total in self.totals), Decimal(0)
        )

    @property
    def usage_total(self) -> Decimal:
        return sum((total.usage_amount for total in self.totals), Decimal(0))


@dataclass
class _Bucket:
    """One department's running totals while a report is being built.

    A small mutable dataclass rather than a dict of `object`: the dict version
    needed a cast on every read, and a cast is where a `Decimal` quietly becomes
    a string in a money column.
    """

    people: int = 0
    lines: int = 0
    purchased: Decimal = Decimal(0)
    usage: Decimal = Decimal(0)


class EnterpriseReportingService:
    def __init__(
        self,
        ledger: LedgerService,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.ledger = ledger
        self.clock = clock

    def funding(
        self, session: Session, organization_id: UUID, currency: str, *, since: datetime
    ) -> FundingSummary:
        """What is in the account, and what policy says about spending it."""
        account = self.ledger.account(
            session,
            currency,
            AccountKind.SERVICE_CREDIT,
            OwnerKind.ORGANIZATION,
            owner_organization_id=organization_id,
        )
        balance = self.ledger.balance(session, account)
        available = self.ledger.available(session, account)
        policy = session.exec(
            select(OrganizationSpendingPolicy).where(
                OrganizationSpendingPolicy.organization_id == organization_id,
                OrganizationSpendingPolicy.currency == currency,
            )
        ).first()
        cap = (
            policy.period_cap_amount
            if policy is not None and policy.enforced
            else None
        )
        spent = self._purchased_since(session, organization_id, currency, since)
        return FundingSummary(
            currency=currency,
            balance=balance,
            held=round_money(balance - available, currency),
            available=available,
            period_cap=cap,
            spent_this_period=spent,
        )

    def departmental(
        self,
        session: Session,
        organization_id: UUID,
        currency: str,
        *,
        period_from: datetime,
        period_to: datetime,
        by: str = "team",
    ) -> DepartmentalReport:
        """Spend by team or cost centre, with the freshness of the usage half.

        Purchases and usage are reported side by side rather than summed. They
        are different facts arriving at different times — an order is known the
        moment it is placed, usage is known when a supplier says so — and adding
        them produces a number that is neither.
        """
        if by not in {"team", "cost_centre"}:
            raise ValueError("group by team or cost_centre")

        people = session.exec(
            select(OrganizationPerson).where(
                OrganizationPerson.organization_id == organization_id
            )
        ).all()
        labels = self._labels(session, organization_id, by)

        buckets: dict[str, _Bucket] = {}
        for person in people:
            key = str(
                (person.team_id if by == "team" else person.cost_centre_id) or ""
            )
            bucket = buckets.setdefault(key, _Bucket())
            bucket.people += 1

            for item, entitlement in self._lines_for(
                session, organization_id, person, period_from, period_to
            ):
                bucket.lines += 1
                if item.unit_currency == currency:
                    bucket.purchased += item.unit_amount * item.quantity
                if entitlement is not None:
                    bucket.usage += self._usage_for(
                        session, entitlement, currency, period_from, period_to
                    )

        totals = [
            DepartmentTotal(
                key=key,
                label=labels.get(key, "Unassigned"),
                people=values.people,
                lines=values.lines,
                purchased_amount=round_money(values.purchased, currency),
                usage_amount=round_money(values.usage, currency),
                currency=currency,
            )
            for key, values in sorted(buckets.items())
        ]
        return DepartmentalReport(
            organization_id=organization_id,
            currency=currency,
            period_from=period_from,
            period_to=period_to,
            totals=totals,
            observed_through=self._observed_through(session, organization_id),
        )

    # --- internals ---------------------------------------------------------

    def _labels(
        self, session: Session, organization_id: UUID, by: str
    ) -> dict[str, str]:
        if by == "team":
            rows = session.exec(
                select(OrganizationTeam).where(
                    OrganizationTeam.organization_id == organization_id
                )
            ).all()
            return {str(row.id): row.name for row in rows}
        centres = session.exec(
            select(OrganizationCostCentre).where(
                OrganizationCostCentre.organization_id == organization_id
            )
        ).all()
        return {str(row.id): f"{row.code} — {row.name}" for row in centres}

    def _lines_for(
        self,
        session: Session,
        organization_id: UUID,
        person: OrganizationPerson,
        period_from: datetime,
        period_to: datetime,
    ) -> Sequence[tuple[OrderItem, Entitlement | None]]:
        """This person's work lines, bought by this organization, in the period.

        Scoped through the order's payer, the same as offboarding: who paid is
        the only durable definition of a work line, and a personal purchase by
        the same person is on an order this query does not reach.
        """
        identity = [col(BulkJobItem.person_id) == person.id]
        if person.user_id is not None:
            identity.extend(
                [
                    col(OrderItem.recipient_user_id) == person.user_id,
                    col(Entitlement.holder_user_id) == person.user_id,
                ]
            )
        rows = session.exec(
            select(OrderItem, Entitlement)
            .join(Order, col(OrderItem.order_id) == col(Order.id))
            .outerjoin(
                Entitlement, col(Entitlement.order_item_id) == col(OrderItem.id)
            )
            .outerjoin(
                BulkJobItem,
                col(BulkJobItem.order_item_id) == col(OrderItem.id),
            )
            .where(
                Order.payer_organization_id == organization_id,
                or_(*identity),
                col(Order.placed_at) >= period_from,
                col(Order.placed_at) < period_to,
            )
            .distinct()
        ).all()
        return list(rows)

    def _usage_for(
        self,
        session: Session,
        entitlement: Entitlement,
        currency: str,
        period_from: datetime,
        period_to: datetime,
    ) -> Decimal:
        """Charged usage for one line, excluding evidence-only records.

        `UsageState.EVIDENCE` is what chunk 16 calls a reading from a line's
        *non-authoritative* source. Counting it would bill the same bytes twice
        in a report, which is how a reconciliation meeting goes wrong.
        """
        total = session.exec(
            select(func.coalesce(func.sum(UsageRecord.charged_amount), 0)).where(
                UsageRecord.entitlement_id == entitlement.id,
                UsageRecord.charged_currency == currency,
                UsageRecord.state != UsageState.EVIDENCE,
                col(UsageRecord.occurred_to) >= period_from,
                col(UsageRecord.occurred_to) < period_to,
            )
        ).first()
        return Decimal(total or 0)

    def _purchased_since(
        self, session: Session, organization_id: UUID, currency: str, since: datetime
    ) -> Decimal:
        total = session.exec(
            select(func.coalesce(func.sum(OrderItem.unit_amount), 0))
            .join(Order, col(OrderItem.order_id) == col(Order.id))
            .where(
                Order.payer_organization_id == organization_id,
                OrderItem.unit_currency == currency,
                col(Order.placed_at) >= since,
            )
        ).first()
        return round_money(Decimal(total or 0), currency)

    def _observed_through(
        self, session: Session, organization_id: UUID
    ) -> datetime | None:
        """The oldest per-line watermark, or unknown if any line has none.

        A maximum across the organization lets one healthy line hide fifty
        stalled ones. Freshness is therefore the minimum of each line's latest
        authoritative observation. A line with no observation makes the
        organization-wide watermark unknown rather than silently current.
        """
        entitlement_ids = list(
            session.exec(
                select(Entitlement.id)
                .join(OrderItem, col(Entitlement.order_item_id) == col(OrderItem.id))
                .join(Order, col(OrderItem.order_id) == col(Order.id))
                .where(Order.payer_organization_id == organization_id)
            ).all()
        )
        if not entitlement_ids:
            return None
        observations = session.exec(
            select(
                UsageRecord.entitlement_id,
                func.max(UsageRecord.occurred_to),
            )
            .join(
                Entitlement, col(UsageRecord.entitlement_id) == col(Entitlement.id)
            )
            .where(
                col(UsageRecord.entitlement_id).in_(entitlement_ids),
                UsageRecord.state != UsageState.EVIDENCE,
            )
            .group_by(col(UsageRecord.entitlement_id))
        ).all()
        if len(observations) != len(entitlement_ids):
            return None
        watermarks = [observed for _entitlement_id, observed in observations]
        return min(watermarks) if watermarks else None


__all__ = [
    "DepartmentTotal",
    "DepartmentalReport",
    "EnterpriseReportingService",
    "FundingSummary",
    "Product",
]
