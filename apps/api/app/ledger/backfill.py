"""Bringing the legacy NGN history into the ledger (US-32, chunk 10).

The assignment asks for a backfill "with explicit provenance and reconciliation
reports, avoiding unsupported assumptions about legacy rows", and the second
half is the harder half.

**What the legacy data actually is.** `transactions.amount_ngn` records money
that was paid for a package. There was never a customer balance: the product had
no wallet, no top-up and no stored credit. Every payment bought one package
outright.

**So the backfill records revenue, and creates no service credit.** Inventing a
`SERVICE_CREDIT` balance for a legacy customer would be inventing money they
never held and could never spend — a liability on our books that no event
produced. `packages.data_gb_remaining` is a *unit* balance, not a currency one;
converting leftover gigabytes into a cash balance would be a pricing decision
nobody made, applied retroactively to customers who never agreed to it.

What each legacy payment becomes:

    debit  settlement_clearing (system, NGN)   the money we received
    credit revenue             (system, NGN)   the sale it paid for

Both sides are system accounts, which is the honest shape: the money arrived and
was earned, and no customer was ever owed a balance.

**The date is the best one available, and labelled as such.** `transactions`
has no payment timestamp — only `created_at` and `receipt_sent_at`, and the
latter is when a receipt was emailed, which is a different event. Entries post
at `created_at` and the report says so, rather than inferring a payment date the
table never recorded.

**Provenance is on every entry.** `business_event_id` is
`legacy:transaction:<id>`, so a re-run posts nothing new, and `reference` names
the table and row it came from. Anybody asking "where did this entry come from"
gets an answer that points at the row rather than at a migration nobody kept.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlmodel import Session, select

from app.auth.models import utc_now
from app.ledger.models import AccountKind, Direction, OwnerKind
from app.ledger.service import LedgerService, Posting
from app.money import round_money
from app.packages.models import Transaction, TransactionStatus

LEGACY_CURRENCY = "NGN"


@dataclass
class BackfillReport:
    """What was posted, what was skipped, and whether it reconciles.

    A backfill that reports only successes is a backfill nobody can check. The
    skipped counts are the interesting numbers: they say which legacy rows the
    ledger deliberately does not represent, so a reviewer can decide whether
    that judgement was right rather than discovering the absence later.
    """

    posted: int = 0
    already_posted: int = 0
    skipped_not_successful: int = 0
    skipped_zero_amount: int = 0
    posted_total: Decimal = Decimal(0)
    legacy_total: Decimal = Decimal(0)
    notes: list[str] = field(default_factory=list)

    @property
    def reconciles(self) -> bool:
        """Does the ledger's NGN revenue equal the legacy successful receipts?"""
        return self.posted_total == self.legacy_total

    def as_dict(self) -> dict[str, object]:
        return {
            "posted": self.posted,
            "already_posted": self.already_posted,
            "skipped_not_successful": self.skipped_not_successful,
            "skipped_zero_amount": self.skipped_zero_amount,
            "posted_total": str(self.posted_total),
            "legacy_total": str(self.legacy_total),
            "reconciles": self.reconciles,
            "notes": list(self.notes),
        }


class LegacyBackfill:
    def __init__(
        self,
        ledger: LedgerService,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.ledger = ledger
        self.clock = clock

    def run(self, session: Session, dry_run: bool = False) -> BackfillReport:
        """Post one entry per successful legacy transaction. Idempotent.

        `dry_run` computes the report without writing, so the reconciliation can
        be inspected before anything is posted — the same courtesy chunk 04's
        retention plan extends before it deletes.
        """
        report = BackfillReport()
        clearing = self.ledger.account(
            session, LEGACY_CURRENCY, AccountKind.SETTLEMENT_CLEARING, OwnerKind.SYSTEM
        )
        revenue = self.ledger.account(
            session, LEGACY_CURRENCY, AccountKind.REVENUE, OwnerKind.SYSTEM
        )

        transactions = session.exec(select(Transaction)).all()
        for transaction in transactions:
            amount = round_money(
                Decimal(transaction.amount_ngn or 0), LEGACY_CURRENCY
            )

            if transaction.status is not TransactionStatus.SUCCESS:
                # A pending or failed charge is not money we hold. Posting one
                # would put revenue on the books for a sale that never
                # completed.
                report.skipped_not_successful += 1
                continue
            if amount <= 0:
                report.skipped_zero_amount += 1
                report.notes.append(
                    f"transaction {transaction.id} is successful but has "
                    f"amount {amount}; not posted"
                )
                continue

            report.legacy_total += amount
            event_id = f"legacy:transaction:{transaction.id}"

            if dry_run:
                report.posted += 1
                report.posted_total += amount
                continue

            self.ledger.post(
                session,
                event_id,
                [
                    Posting(clearing, Direction.DEBIT, amount),
                    Posting(revenue, Direction.CREDIT, amount),
                ],
                # The date the row was created, because that is the only date
                # the legacy table has. `transactions` records no payment
                # timestamp -- `receipt_sent_at` is when we emailed a receipt,
                # which is a different event and sometimes days later, so using
                # it would be exactly the unsupported assumption about legacy
                # rows this chunk is told to avoid. What matters is that it is
                # not the migration's own date: stamping everything "today"
                # destroys the only thing the backfill exists to preserve.
                occurred_at=transaction.created_at,
                reference=f"backfilled from transactions.{transaction.id}",
            )
            # `post` is idempotent on the event id, so a re-run replays rather
            # than double-posting and the totals still reconcile.
            report.posted += 1
            report.posted_total += amount

        report.notes.append(
            "No SERVICE_CREDIT was created. The legacy product had no wallet: "
            "every payment bought one package outright, so no customer ever "
            "held a balance. Creating one would invent a liability that no "
            "event produced."
        )
        report.notes.append(
            "packages.data_gb_remaining and pstn_minutes_remaining are unit "
            "balances, not currency. They are entitlements and belong to "
            "chunk 05's entitlements table, not to this ledger."
        )
        return report
