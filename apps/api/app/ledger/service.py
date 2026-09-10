"""Posting, balances and atomic reservations (US-32, chunk 10).

Two operations carry the weight here.

**`post`** writes a balanced entry or nothing. It is idempotent on
`business_event_id`: replaying the same event returns the entry already posted
rather than posting a second one, so a duplicated webhook, a retried worker and
a reordered message all converge on one accounting effect.

**`reserve`** answers "is there enough" and takes the amount in the same
transaction, with the account row locked. Reading availability and then writing
a reservation would let two concurrent purchases both see enough and both
succeed — the classic overspend, and the reason this chunk's tests run against
real PostgreSQL.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.auth.models import utc_now
from app.ledger.models import (
    NATURAL_SIDE,
    AccountKind,
    Direction,
    JournalEntry,
    JournalLine,
    LedgerAccount,
    OwnerKind,
    Reservation,
    ReservationState,
)
from app.money import round_money


class LedgerError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


@dataclass(frozen=True)
class Posting:
    """One side of an entry. Amount is always positive; direction carries sign."""

    account: LedgerAccount
    direction: Direction
    amount: Decimal


class LedgerService:
    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self.clock = clock

    # --- accounts ---------------------------------------------------------

    def account(
        self,
        session: Session,
        currency: str,
        kind: AccountKind,
        owner_kind: OwnerKind = OwnerKind.SYSTEM,
        owner_user_id: UUID | None = None,
        owner_organization_id: UUID | None = None,
    ) -> LedgerAccount:
        """Get or create. Accounts are identity, not state, so this is safe."""
        existing = session.exec(
            select(LedgerAccount).where(
                LedgerAccount.owner_kind == owner_kind,
                LedgerAccount.owner_user_id == owner_user_id,
                LedgerAccount.owner_organization_id == owner_organization_id,
                LedgerAccount.currency == currency,
                LedgerAccount.kind == kind,
            )
        ).first()
        if existing is not None:
            return existing
        account = LedgerAccount(
            owner_kind=owner_kind,
            owner_user_id=owner_user_id,
            owner_organization_id=owner_organization_id,
            currency=currency,
            kind=kind,
            created_at=self.clock(),
        )
        session.add(account)
        session.flush()
        return account

    # --- posting ----------------------------------------------------------

    def post(
        self,
        session: Session,
        business_event_id: str,
        postings: Sequence[Posting],
        occurred_at: datetime | None = None,
        reference: str | None = None,
    ) -> JournalEntry:
        """Post one balanced entry, or return the one this event already posted.

        Idempotent by design rather than by luck. The caller names the event
        (`order:<id>:capture`), and the same name always means the same entry —
        which is why a random id per attempt would be a bug, not a detail.
        """
        if not postings:
            raise LedgerError("empty_entry")

        currencies = {posting.account.currency for posting in postings}
        if len(currencies) != 1:
            # Two currencies in one entry cannot balance in either of them.
            # The composite foreign keys make this impossible at the database
            # level too; refusing here gives a comprehensible error first.
            raise LedgerError(
                "cross_currency_entry",
                f"one entry, one currency; got {sorted(currencies)}",
            )
        currency = currencies.pop()

        debits = sum_amounts(
            posting.amount
            for posting in postings
            if posting.direction is Direction.DEBIT
        )
        credits = sum_amounts(
            posting.amount
            for posting in postings
            if posting.direction is Direction.CREDIT
        )
        if round_money(debits, currency) != round_money(credits, currency):
            raise LedgerError(
                "unbalanced_entry",
                f"debits {debits} != credits {credits} in {currency}",
            )
        for posting in postings:
            if posting.amount <= 0:
                raise LedgerError("non_positive_amount")

        existing = session.exec(
            select(JournalEntry).where(
                JournalEntry.business_event_id == business_event_id
            )
        ).first()
        if existing is not None:
            # A replay. Returning the original is what makes retries safe; the
            # unique constraint is the backstop for two concurrent replays.
            return existing

        now = self.clock()
        entry = JournalEntry(
            business_event_id=business_event_id,
            currency=currency,
            occurred_at=occurred_at or now,
            recorded_at=now,
            reference=reference,
        )
        session.add(entry)
        session.flush()
        for posting in postings:
            session.add(
                JournalLine(
                    entry_id=entry.id,
                    account_id=posting.account.id,
                    currency=currency,
                    direction=posting.direction,
                    amount=round_money(posting.amount, currency),
                )
            )
        session.flush()
        return entry

    # --- balances ---------------------------------------------------------

    def balance(self, session: Session, account: LedgerAccount) -> Decimal:
        """Signed in the account's natural direction.

        So a customer holding 1,000 of credit reads as `1000`, not as `-1000`
        because a liability happens to be credit-natured. Anyone reading a
        balance wants the amount, not a lesson in bookkeeping sign conventions.
        """
        totals = dict(
            session.exec(
                select(JournalLine.direction, func.sum(JournalLine.amount))
                .where(JournalLine.account_id == account.id)
                .group_by(col(JournalLine.direction))
            ).all()
        )
        debit = Decimal(totals.get(Direction.DEBIT) or 0)
        credit = Decimal(totals.get(Direction.CREDIT) or 0)
        signed = (
            debit - credit
            if NATURAL_SIDE[account.kind] is Direction.DEBIT
            else credit - debit
        )
        return round_money(signed, account.currency)

    def held(self, session: Session, account: LedgerAccount) -> Decimal:
        """The part of the balance that is spoken for but not yet spent."""
        outstanding = session.exec(
            select(
                func.sum(
                    Reservation.amount
                    - Reservation.settled_amount
                    - Reservation.released_amount
                )
            ).where(
                Reservation.account_id == account.id,
                Reservation.state == ReservationState.HELD,
            )
        ).first()
        return round_money(Decimal(outstanding or 0), account.currency)

    def available(self, session: Session, account: LedgerAccount) -> Decimal:
        return round_money(
            self.balance(session, account) - self.held(session, account),
            account.currency,
        )

    # --- reservations -----------------------------------------------------

    def reserve(
        self,
        session: Session,
        account: LedgerAccount,
        amount: Decimal,
        business_event_id: str,
        expires_at: datetime | None = None,
    ) -> Reservation:
        """Check availability and take the hold in one locked step.

        The `FOR UPDATE` is the whole thing. Without it two concurrent callers
        both read the same availability, both find it sufficient, and both
        reserve — and the account is overspent by exactly the amount nobody
        checked for.
        """
        if amount <= 0:
            raise LedgerError("non_positive_amount")

        existing = session.exec(
            select(Reservation).where(
                Reservation.business_event_id == business_event_id
            )
        ).first()
        if existing is not None:
            return existing

        # Lock the account row first, then compute. Everything that changes
        # this account's availability has to pass through the same lock.
        session.exec(
            select(LedgerAccount)
            .where(LedgerAccount.id == account.id)
            .with_for_update()
        ).first()

        rounded = round_money(amount, account.currency)
        if self.available(session, account) < rounded:
            raise LedgerError(
                "insufficient_available_balance",
                f"{rounded} {account.currency} requested",
            )

        reservation = Reservation(
            business_event_id=business_event_id,
            account_id=account.id,
            currency=account.currency,
            amount=rounded,
            settled_amount=Decimal(0),
            released_amount=Decimal(0),
            state=ReservationState.HELD,
            expires_at=expires_at,
            created_at=self.clock(),
        )
        session.add(reservation)
        session.flush()
        return reservation

    def _open(self, session: Session, reservation: Reservation) -> Reservation:
        current = session.get(Reservation, reservation.id)
        if current is None:
            raise LedgerError("reservation_not_found")
        if current.state is not ReservationState.HELD:
            raise LedgerError("reservation_closed")
        return current

    def release(
        self,
        session: Session,
        reservation: Reservation,
        amount: Decimal | None = None,
    ) -> Reservation:
        """Give back an unspent hold, wholly or partly.

        No posting. Nothing ever left the customer's account, so there is
        nothing to reverse — releasing a hold that never moved money by writing
        a journal entry would invent a transaction that did not happen.
        """
        current = self._open(session, reservation)
        outstanding = current.amount - current.settled_amount - current.released_amount
        release_amount = round_money(
            amount if amount is not None else outstanding, current.currency
        )
        if release_amount <= 0:
            raise LedgerError("non_positive_amount")
        if release_amount > outstanding:
            raise LedgerError(
                "release_exceeds_hold",
                f"{release_amount} released against {outstanding} outstanding",
            )

        current.released_amount = current.released_amount + release_amount
        if current.settled_amount + current.released_amount == current.amount:
            current.state = ReservationState.RELEASED
            current.closed_at = self.clock()
        session.add(current)
        session.flush()
        return current

    def settle(
        self,
        session: Session,
        reservation: Reservation,
        amount: Decimal,
        business_event_id: str,
        credit_account: LedgerAccount,
        occurred_at: datetime | None = None,
    ) -> tuple[Reservation, JournalEntry]:
        """Spend part or all of a hold, and post the movement it represents.

        Settlement is where money actually moves, so this is the only
        reservation operation that posts. The remainder stays held: a call that
        reserved a maximum and used half keeps the rest reserved until the
        caller releases it, because deciding on the customer's behalf that they
        are finished is not this function's call to make.
        """
        current = self._open(session, reservation)
        outstanding = current.amount - current.settled_amount - current.released_amount
        settle_amount = round_money(amount, current.currency)
        if settle_amount <= 0:
            raise LedgerError("non_positive_amount")
        if settle_amount > outstanding:
            raise LedgerError(
                "settlement_exceeds_hold",
                f"{settle_amount} settled against {outstanding} outstanding",
            )
        if credit_account.currency != current.currency:
            raise LedgerError("cross_currency_settlement")

        account = session.get(LedgerAccount, current.account_id)
        if account is None:  # pragma: no cover - FK guarantees this
            raise LedgerError("account_not_found")

        entry = self.post(
            session,
            business_event_id,
            [
                Posting(account, Direction.DEBIT, settle_amount),
                Posting(credit_account, Direction.CREDIT, settle_amount),
            ],
            occurred_at=occurred_at,
            reference=f"settlement of reservation {current.id}",
        )
        current.settled_amount = current.settled_amount + settle_amount
        if current.settled_amount + current.released_amount == current.amount:
            current.state = ReservationState.SETTLED
            current.closed_at = self.clock()
        session.add(current)
        session.flush()
        return current, entry

    # --- reconciliation ---------------------------------------------------

    def trial_balance(
        self, session: Session, currency: str
    ) -> dict[str, Decimal]:
        """Total debits and credits for a currency. They must be equal.

        Not a formality. Every entry balances individually by trigger, so the
        whole ledger balances by construction — which means a non-zero result
        here is evidence that something reached the tables without going through
        `post`, and that is worth finding out about immediately.
        """
        totals = dict(
            session.exec(
                select(JournalLine.direction, func.sum(JournalLine.amount))
                .where(JournalLine.currency == currency)
                .group_by(col(JournalLine.direction))
            ).all()
        )
        debit = round_money(Decimal(totals.get(Direction.DEBIT) or 0), currency)
        credit = round_money(Decimal(totals.get(Direction.CREDIT) or 0), currency)
        return {
            "debits": debit,
            "credits": credit,
            "difference": round_money(debit - credit, currency),
        }


def sum_amounts(amounts: Iterable[Decimal]) -> Decimal:
    total = Decimal(0)
    for amount in amounts:
        total += amount
    return total


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
