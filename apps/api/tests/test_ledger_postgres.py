"""US-32 chunk 10 — the ledger and reservations, on real PostgreSQL.

Ledger correctness and concurrency is one of the repository's strict-TDD
categories, and every test here is a way money goes missing or appears from
nowhere: an entry that does not balance, a webhook delivered twice, two
purchases racing for the same balance, a settlement larger than its hold, a
correction applied by editing history.

None of it is testable on SQLite. The deferred constraint trigger, `SELECT …
FOR UPDATE` and the composite foreign keys are the things doing the work.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.models import Platform, User
from app.ledger.backfill import LegacyBackfill
from app.ledger.models import (
    AccountKind,
    Direction,
    JournalEntry,
    JournalLine,
    LedgerAccount,
    OwnerKind,
    ReservationState,
)
from app.ledger.service import LedgerError, LedgerService, Posting
from app.packages.models import (
    PaymentMethod,
    PaymentProcessor,
    Transaction,
    TransactionStatus,
)

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="the ledger's guarantees are database guarantees",
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
TABLES = (
    "journal_lines, journal_entries, ledger_reservations, ledger_accounts, "
    "transactions, users"
)


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def engine():
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        session.exec(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        session.commit()
        yield session
        session.rollback()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def service(clock):
    return LedgerService(clock=clock)


def _user(session: Session, label: str = "customer") -> User:
    user = User(
        # Unique per call: two customers in one test is the normal case, and a
        # label-derived number collides the moment there are two of them.
        phone_number=f"+23485{uuid4().int % 10**8:08d}",
        first_name=label,
        platform=Platform.ANDROID,
    )
    session.add(user)
    session.flush()
    return user


def _funded(session, service, amount="10000.00", currency="NGN"):
    """A customer with credit, funded the way a real payment would fund it."""
    user = _user(session)
    credit = service.account(
        session,
        currency,
        AccountKind.SERVICE_CREDIT,
        OwnerKind.USER,
        owner_user_id=user.id,
    )
    clearing = service.account(session, currency, AccountKind.SETTLEMENT_CLEARING)
    service.post(
        session,
        f"funding:{uuid4()}",
        [
            Posting(clearing, Direction.DEBIT, Decimal(amount)),
            Posting(credit, Direction.CREDIT, Decimal(amount)),
        ],
    )
    session.commit()
    return user, credit, clearing


# --- entries balance, per currency ------------------------------------------


class TestBalancedEntries:
    def test_a_balanced_entry_posts(self, session, service):
        _, credit, clearing = _funded(session, service)
        assert service.balance(session, credit) == Decimal("10000.00")
        assert service.balance(session, clearing) == Decimal("10000.00")

    def test_an_unbalanced_entry_is_refused_by_the_service(self, session, service):
        _, credit, clearing = _funded(session, service)
        with pytest.raises(LedgerError) as excinfo:
            service.post(
                session,
                "bad:1",
                [
                    Posting(clearing, Direction.DEBIT, Decimal("100")),
                    Posting(credit, Direction.CREDIT, Decimal("90")),
                ],
            )
        assert excinfo.value.code == "unbalanced_entry"

    def test_the_database_refuses_an_unbalanced_entry_too(self, session, service):
        """The deferred trigger, checked at COMMIT.

        The service check is a good error message. This is the guarantee: an
        unbalanced entry cannot exist even if some future caller bypasses the
        service entirely.
        """
        _, credit, clearing = _funded(session, service)
        entry = JournalEntry(
            business_event_id=f"raw:{uuid4()}",
            currency="NGN",
            occurred_at=NOW,
            recorded_at=NOW,
        )
        session.add(entry)
        session.flush()
        session.add(
            JournalLine(
                entry_id=entry.id,
                account_id=clearing.id,
                currency="NGN",
                direction=Direction.DEBIT,
                amount=Decimal("100"),
            )
        )
        with pytest.raises(Exception) as excinfo:
            session.commit()
        assert "does not balance" in str(excinfo.value)
        session.rollback()

    def test_the_database_refuses_an_entry_with_no_lines(self, session, service):
        session.add(
            JournalEntry(
                business_event_id=f"empty:{uuid4()}",
                currency="NGN",
                occurred_at=NOW,
                recorded_at=NOW,
            )
        )
        with pytest.raises(Exception) as excinfo:
            session.commit()
        assert "no lines" in str(excinfo.value)
        session.rollback()

    def test_two_currencies_cannot_share_an_entry(self, session, service):
        # An entry in two currencies cannot balance in either of them.
        user = _user(session)
        ngn = service.account(
            session, "NGN", AccountKind.SERVICE_CREDIT, OwnerKind.USER, user.id
        )
        usd = service.account(
            session, "USD", AccountKind.SERVICE_CREDIT, OwnerKind.USER, user.id
        )
        session.commit()
        with pytest.raises(LedgerError) as excinfo:
            service.post(
                session,
                "mixed:1",
                [
                    Posting(ngn, Direction.DEBIT, Decimal("100")),
                    Posting(usd, Direction.CREDIT, Decimal("100")),
                ],
            )
        assert excinfo.value.code == "cross_currency_entry"

    def test_a_line_cannot_disagree_with_its_account_about_currency(
        self, session, service
    ):
        # The composite foreign key, not the service.
        _, credit, clearing = _funded(session, service)
        entry = JournalEntry(
            business_event_id=f"raw:{uuid4()}",
            currency="NGN",
            occurred_at=NOW,
            recorded_at=NOW,
        )
        session.add(entry)
        session.flush()
        session.add(
            JournalLine(
                entry_id=entry.id,
                account_id=credit.id,
                currency="USD",
                direction=Direction.CREDIT,
                amount=Decimal("100"),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_a_zero_or_negative_line_is_refused(self, session, service):
        _, credit, clearing = _funded(session, service)
        for amount in (Decimal("0"), Decimal("-5")):
            with pytest.raises(LedgerError):
                service.post(
                    session,
                    f"bad:{amount}",
                    [
                        Posting(clearing, Direction.DEBIT, amount),
                        Posting(credit, Direction.CREDIT, amount),
                    ],
                )

    def test_the_whole_ledger_balances(self, session, service):
        _funded(session, service)
        _funded(session, service, amount="250.00")
        assert service.trial_balance(session, "NGN")["difference"] == Decimal("0.00")


# --- replay, duplication and reordering --------------------------------------


class TestIdempotency:
    def test_replaying_a_business_event_posts_once(self, session, service):
        """A webhook delivered twice, or a worker retried after a timeout."""
        _, credit, clearing = _funded(session, service)
        postings = [
            Posting(clearing, Direction.DEBIT, Decimal("500")),
            Posting(credit, Direction.CREDIT, Decimal("500")),
        ]
        first = service.post(session, "payment:abc:capture", postings)
        session.commit()
        second = service.post(session, "payment:abc:capture", postings)
        session.commit()

        assert first.id == second.id
        assert service.balance(session, credit) == Decimal("10500.00")

    def test_the_database_refuses_a_duplicate_event_id(self, session, service):
        # The backstop for two concurrent replays, where both read "not posted".
        _, credit, clearing = _funded(session, service)
        service.post(
            session,
            "payment:xyz",
            [
                Posting(clearing, Direction.DEBIT, Decimal("5")),
                Posting(credit, Direction.CREDIT, Decimal("5")),
            ],
        )
        session.commit()
        session.add(
            JournalEntry(
                business_event_id="payment:xyz",
                currency="NGN",
                occurred_at=NOW,
                recorded_at=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_concurrent_replays_credit_once(self, engine, service):
        with Session(engine) as setup:
            setup.exec(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
            setup.commit()
            _, credit, clearing = _funded(setup, service)
            credit_id, clearing_id = credit.id, clearing.id

        barrier = Barrier(2)

        def deliver(_: int) -> str:
            with Session(engine) as scoped:
                credit_account = scoped.get(LedgerAccount, credit_id)
                clearing_account = scoped.get(LedgerAccount, clearing_id)
                barrier.wait(timeout=10)
                try:
                    service.post(
                        scoped,
                        "payment:concurrent:capture",
                        [
                            Posting(clearing_account, Direction.DEBIT, Decimal("400")),
                            Posting(credit_account, Direction.CREDIT, Decimal("400")),
                        ],
                    )
                    scoped.commit()
                    return "ok"
                except Exception:
                    scoped.rollback()
                    return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(deliver, range(2)))

        with Session(engine) as check:
            account = check.get(LedgerAccount, credit_id)
            entries = check.exec(
                select(JournalEntry).where(
                    JournalEntry.business_event_id == "payment:concurrent:capture"
                )
            ).all()
            # Exactly one entry, and exactly one credit -- whichever thread won.
            assert len(entries) == 1
            assert service.balance(check, account) == Decimal("10400.00")

    def test_an_out_of_order_settlement_posts_at_the_date_it_describes(
        self, session, service
    ):
        # A settlement report arriving three days late is not a transaction
        # that happened today.
        _, credit, clearing = _funded(session, service)
        backdated = NOW - timedelta(days=3)
        entry = service.post(
            session,
            "settlement:late",
            [
                Posting(clearing, Direction.DEBIT, Decimal("10")),
                Posting(credit, Direction.CREDIT, Decimal("10")),
            ],
            occurred_at=backdated,
        )
        session.commit()
        assert entry.occurred_at.replace(tzinfo=timezone.utc) == backdated
        assert entry.recorded_at.replace(tzinfo=timezone.utc) == NOW


# --- posted history is never edited ------------------------------------------


class TestImmutability:
    def test_a_posted_entry_cannot_be_updated(self, session, service):
        _, credit, clearing = _funded(session, service)
        entry = session.exec(select(JournalEntry)).first()
        with pytest.raises(Exception) as excinfo:
            session.exec(
                text(
                    "UPDATE journal_entries SET reference = 'edited' "
                    "WHERE id = CAST(:id AS uuid)"
                ).bindparams(id=str(entry.id))
            )
            session.commit()
        assert "immutable" in str(excinfo.value).lower()
        session.rollback()

    def test_a_posted_entry_cannot_be_deleted(self, session, service):
        _, credit, clearing = _funded(session, service)
        entry = session.exec(select(JournalEntry)).first()
        with pytest.raises(Exception) as excinfo:
            session.exec(
                text(
                    "DELETE FROM journal_entries WHERE id = CAST(:id AS uuid)"
                ).bindparams(id=str(entry.id))
            )
            session.commit()
        assert "immutable" in str(excinfo.value).lower()
        session.rollback()

    def test_a_correction_is_a_new_opposite_entry(self, session, service):
        """The only way to fix a posting: post the opposite and say why."""
        _, credit, clearing = _funded(session, service)
        adjustment = service.account(session, "NGN", AccountKind.ADJUSTMENT)
        service.post(
            session,
            "correction:overcharge-4821",
            [
                Posting(credit, Direction.DEBIT, Decimal("250")),
                Posting(adjustment, Direction.CREDIT, Decimal("250")),
            ],
            reference="compensating entry for overcharge on order 4821",
        )
        session.commit()

        assert service.balance(session, credit) == Decimal("9750.00")
        # The original is still there, unchanged, which is the point.
        assert len(session.exec(select(JournalEntry)).all()) == 2


# --- reservations ------------------------------------------------------------


class TestReservations:
    def test_a_hold_reduces_available_but_not_balance(self, session, service):
        # Nothing has happened to the money. It is still theirs and still in
        # their account; it is simply spoken for.
        _, credit, _ = _funded(session, service)
        service.reserve(session, credit, Decimal("3000"), "order:1:hold")
        session.commit()

        assert service.balance(session, credit) == Decimal("10000.00")
        assert service.held(session, credit) == Decimal("3000.00")
        assert service.available(session, credit) == Decimal("7000.00")

    def test_a_reservation_beyond_available_is_refused(self, session, service):
        _, credit, _ = _funded(session, service)
        service.reserve(session, credit, Decimal("9000"), "order:1:hold")
        session.commit()
        with pytest.raises(LedgerError) as excinfo:
            service.reserve(session, credit, Decimal("2000"), "order:2:hold")
        assert excinfo.value.code == "insufficient_available_balance"

    def test_reserving_is_idempotent_on_its_event(self, session, service):
        _, credit, _ = _funded(session, service)
        first = service.reserve(session, credit, Decimal("1000"), "order:1:hold")
        session.commit()
        second = service.reserve(session, credit, Decimal("1000"), "order:1:hold")
        session.commit()
        assert first.id == second.id
        assert service.held(session, credit) == Decimal("1000.00")

    def test_releasing_returns_the_hold_without_posting_anything(
        self, session, service
    ):
        """A released hold never moved money, so there is nothing to reverse.

        Writing a journal entry for it would invent a transaction that did not
        happen, and the ledger would describe a refund nobody received.
        """
        _, credit, _ = _funded(session, service)
        reservation = service.reserve(session, credit, Decimal("3000"), "order:1:hold")
        session.commit()
        entries_before = len(session.exec(select(JournalEntry)).all())

        service.release(session, reservation)
        session.commit()

        assert service.available(session, credit) == Decimal("10000.00")
        assert len(session.exec(select(JournalEntry)).all()) == entries_before
        session.refresh(reservation)
        assert reservation.state is ReservationState.RELEASED

    def test_partial_settlement_keeps_the_remainder_held(self, session, service):
        # A call reserves a maximum and settles what it cost. Deciding on the
        # customer's behalf that they are finished is not settle()'s call.
        _, credit, _ = _funded(session, service)
        revenue = service.account(session, "NGN", AccountKind.REVENUE)
        reservation = service.reserve(session, credit, Decimal("1000"), "call:1:hold")
        session.commit()

        reservation, _ = service.settle(
            session, reservation, Decimal("250"), "call:1:settle", revenue
        )
        session.commit()

        assert reservation.state is ReservationState.HELD
        assert service.balance(session, credit) == Decimal("9750.00")
        assert service.held(session, credit) == Decimal("750.00")
        assert service.available(session, credit) == Decimal("9000.00")
        assert service.balance(session, revenue) == Decimal("250.00")

    def test_settling_then_releasing_the_rest_closes_the_hold(self, session, service):
        _, credit, _ = _funded(session, service)
        revenue = service.account(session, "NGN", AccountKind.REVENUE)
        reservation = service.reserve(session, credit, Decimal("1000"), "call:2:hold")
        session.commit()
        reservation, _ = service.settle(
            session, reservation, Decimal("400"), "call:2:settle", revenue
        )
        service.release(session, reservation)
        session.commit()

        session.refresh(reservation)
        assert reservation.state is ReservationState.RELEASED
        assert service.available(session, credit) == Decimal("9600.00")

    def test_settling_more_than_the_hold_is_refused(self, session, service):
        _, credit, _ = _funded(session, service)
        revenue = service.account(session, "NGN", AccountKind.REVENUE)
        reservation = service.reserve(session, credit, Decimal("100"), "call:3:hold")
        session.commit()
        with pytest.raises(LedgerError) as excinfo:
            service.settle(
                session, reservation, Decimal("101"), "call:3:settle", revenue
            )
        assert excinfo.value.code == "settlement_exceeds_hold"

    def test_releasing_more_than_the_hold_is_refused(self, session, service):
        _, credit, _ = _funded(session, service)
        reservation = service.reserve(session, credit, Decimal("100"), "call:4:hold")
        session.commit()
        with pytest.raises(LedgerError) as excinfo:
            service.release(session, reservation, Decimal("101"))
        assert excinfo.value.code == "release_exceeds_hold"

    def test_the_database_refuses_an_overspent_disposition(self, session, service):
        _, credit, _ = _funded(session, service)
        reservation = service.reserve(session, credit, Decimal("100"), "call:5:hold")
        session.commit()
        with pytest.raises(IntegrityError):
            session.exec(
                text(
                    "UPDATE ledger_reservations SET settled_amount = 200 "
                    "WHERE id = CAST(:id AS uuid)"
                ).bindparams(id=str(reservation.id))
            )
            session.commit()
        session.rollback()

    def test_a_closed_reservation_cannot_be_settled_again(self, session, service):
        _, credit, _ = _funded(session, service)
        revenue = service.account(session, "NGN", AccountKind.REVENUE)
        reservation = service.reserve(session, credit, Decimal("100"), "call:6:hold")
        session.commit()
        reservation, _ = service.settle(
            session, reservation, Decimal("100"), "call:6:settle", revenue
        )
        session.commit()
        with pytest.raises(LedgerError) as excinfo:
            service.settle(
                session, reservation, Decimal("1"), "call:6:settle:again", revenue
            )
        assert excinfo.value.code == "reservation_closed"

    def test_concurrent_reservations_cannot_overspend(self, engine, service):
        """The test this chunk exists for.

        Two purchases, one balance, enough for exactly one of them. Read
        availability and then write, and both succeed.
        """
        with Session(engine) as setup:
            setup.exec(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
            setup.commit()
            _, credit, _ = _funded(setup, service, amount="1000.00")
            credit_id = credit.id

        barrier = Barrier(2)

        def purchase(index: int) -> str:
            with Session(engine) as scoped:
                account = scoped.get(LedgerAccount, credit_id)
                barrier.wait(timeout=10)
                try:
                    service.reserve(
                        scoped, account, Decimal("700"), f"order:{index}:hold"
                    )
                    scoped.commit()
                    return "ok"
                except LedgerError as exc:
                    scoped.rollback()
                    return exc.code
                except Exception:
                    scoped.rollback()
                    return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(purchase, range(2)))

        assert outcomes.count("ok") == 1, outcomes
        with Session(engine) as check:
            account = check.get(LedgerAccount, credit_id)
            assert service.held(check, account) == Decimal("700.00")
            assert service.available(check, account) >= Decimal("0.00")

    def test_a_failure_mid_transaction_leaves_no_partial_posting(
        self, session, service
    ):
        """Either the whole balanced entry commits, or none of it does."""
        _, credit, clearing = _funded(session, service)
        before = len(session.exec(select(JournalEntry)).all())

        try:
            service.post(
                session,
                "half:written",
                [
                    Posting(clearing, Direction.DEBIT, Decimal("100")),
                    Posting(credit, Direction.CREDIT, Decimal("100")),
                ],
            )
            raise RuntimeError("supplier call failed after posting")
        except RuntimeError:
            session.rollback()

        assert len(session.exec(select(JournalEntry)).all()) == before
        assert (
            session.exec(
                select(JournalEntry).where(
                    JournalEntry.business_event_id == "half:written"
                )
            ).first()
            is None
        )


# --- closed loop -------------------------------------------------------------


class TestClosedLoop:
    def test_service_credit_belongs_to_exactly_one_owner(self, session, service):
        # No transfers: an account is identified by its owner, so there is no
        # operation that moves credit from one customer to another.
        first = _user(session, "first")
        second = _user(session, "second")
        session.commit()
        a = service.account(
            session, "NGN", AccountKind.SERVICE_CREDIT, OwnerKind.USER, first.id
        )
        b = service.account(
            session, "NGN", AccountKind.SERVICE_CREDIT, OwnerKind.USER, second.id
        )
        session.commit()
        assert a.id != b.id

    def test_an_account_cannot_have_two_owners(self, session, service):
        user = _user(session)
        session.commit()
        session.add(
            LedgerAccount(
                owner_kind=OwnerKind.USER,
                owner_user_id=user.id,
                owner_organization_id=uuid4(),
                currency="NGN",
                kind=AccountKind.SERVICE_CREDIT,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_one_account_per_owner_currency_and_kind(self, session, service):
        user = _user(session)
        session.commit()
        first = service.account(
            session, "NGN", AccountKind.SERVICE_CREDIT, OwnerKind.USER, user.id
        )
        session.commit()
        again = service.account(
            session, "NGN", AccountKind.SERVICE_CREDIT, OwnerKind.USER, user.id
        )
        assert first.id == again.id

    def test_balances_in_two_currencies_never_merge(self, session, service):
        user = _user(session)
        session.commit()
        ngn = service.account(
            session, "NGN", AccountKind.SERVICE_CREDIT, OwnerKind.USER, user.id
        )
        usd = service.account(
            session, "USD", AccountKind.SERVICE_CREDIT, OwnerKind.USER, user.id
        )
        clearing_ngn = service.account(
            session, "NGN", AccountKind.SETTLEMENT_CLEARING
        )
        clearing_usd = service.account(
            session, "USD", AccountKind.SETTLEMENT_CLEARING
        )
        service.post(
            session,
            "fund:ngn",
            [
                Posting(clearing_ngn, Direction.DEBIT, Decimal("1000")),
                Posting(ngn, Direction.CREDIT, Decimal("1000")),
            ],
        )
        service.post(
            session,
            "fund:usd",
            [
                Posting(clearing_usd, Direction.DEBIT, Decimal("50")),
                Posting(usd, Direction.CREDIT, Decimal("50")),
            ],
        )
        session.commit()

        assert service.balance(session, ngn) == Decimal("1000.00")
        assert service.balance(session, usd) == Decimal("50.00")
        assert service.trial_balance(session, "NGN")["difference"] == Decimal("0.00")
        assert service.trial_balance(session, "USD")["difference"] == Decimal("0.00")


# --- legacy backfill ---------------------------------------------------------


class TestLegacyBackfill:
    """The backfill's judgement is the thing under test, not its arithmetic.

    What it refuses to do matters more than what it does: the legacy product had
    no wallet, so creating a customer balance would invent a liability that no
    event produced, and converting leftover gigabytes into cash would apply a
    pricing decision nobody made to customers who never agreed to it.
    """

    def _legacy_payment(
        self,
        session,
        amount: str,
        status: TransactionStatus = TransactionStatus.SUCCESS,
        created_at: datetime | None = None,
    ) -> Transaction:
        transaction = Transaction(
            processor=PaymentProcessor.PAYSTACK,
            processor_reference=f"ref-{uuid4().hex[:12]}",
            payment_method=PaymentMethod.CARD,
            amount_ngn=Decimal(amount),
            status=status,
            created_at=created_at or NOW,
        )
        session.add(transaction)
        session.flush()
        return transaction

    def test_each_successful_payment_becomes_one_balanced_entry(
        self, session, service
    ):
        self._legacy_payment(session, "5000.00")
        self._legacy_payment(session, "2500.00")
        session.commit()

        report = LegacyBackfill(service).run(session)
        session.commit()

        assert report.posted == 2
        assert report.posted_total == Decimal("7500.00")
        assert report.reconciles
        assert service.trial_balance(session, "NGN")["difference"] == Decimal("0.00")

    def test_it_creates_no_customer_balance(self, session, service):
        """The refusal that matters.

        A SERVICE_CREDIT balance here would be money a customer never held and
        could never spend -- a liability on our books with no event behind it.
        """
        self._legacy_payment(session, "5000.00")
        session.commit()
        LegacyBackfill(service).run(session)
        session.commit()

        credit_accounts = session.exec(
            select(LedgerAccount).where(
                LedgerAccount.kind == AccountKind.SERVICE_CREDIT
            )
        ).all()
        assert credit_accounts == []

    def test_a_failed_or_pending_charge_posts_nothing(self, session, service):
        self._legacy_payment(session, "5000.00", TransactionStatus.FAILED)
        self._legacy_payment(session, "1000.00", TransactionStatus.PENDING)
        session.commit()

        report = LegacyBackfill(service).run(session)
        session.commit()
        assert report.posted == 0
        assert report.skipped_not_successful == 2
        assert session.exec(select(JournalEntry)).all() == []

    def test_re_running_posts_nothing_new(self, session, service):
        self._legacy_payment(session, "5000.00")
        session.commit()
        backfill = LegacyBackfill(service)
        backfill.run(session)
        session.commit()
        entries_after_first = len(session.exec(select(JournalEntry)).all())

        second = backfill.run(session)
        session.commit()
        assert len(session.exec(select(JournalEntry)).all()) == entries_after_first
        assert second.reconciles

    def test_it_posts_at_the_legacy_date_not_the_migration_date(
        self, session, service
    ):
        """A backfill that stamps everything "today" destroys what it preserves.

        `created_at` is the only date `transactions` has -- there is no payment
        timestamp, and `receipt_sent_at` is a different event -- so that is what
        posts, and the module says so rather than inferring one.
        """
        paid = NOW - timedelta(days=400)
        self._legacy_payment(session, "5000.00", created_at=paid)
        session.commit()
        LegacyBackfill(service).run(session)
        session.commit()

        entry = session.exec(select(JournalEntry)).one()
        assert entry.occurred_at.replace(tzinfo=timezone.utc) == paid

    def test_a_dry_run_writes_nothing_but_still_reconciles(self, session, service):
        self._legacy_payment(session, "5000.00")
        session.commit()

        report = LegacyBackfill(service).run(session, dry_run=True)
        assert report.posted == 1
        assert report.reconciles
        assert session.exec(select(JournalEntry)).all() == []

    def test_a_successful_but_zero_amount_row_is_reported_not_posted(
        self, session, service
    ):
        # Real legacy data has rows like this. Silently posting a zero entry
        # would hide it; silently skipping it would too.
        self._legacy_payment(session, "0.00")
        session.commit()
        report = LegacyBackfill(service).run(session)
        session.commit()

        assert report.posted == 0
        assert report.skipped_zero_amount == 1
        assert any("amount" in note for note in report.notes)

    def test_the_report_says_what_it_deliberately_did_not_do(self, session, service):
        report = LegacyBackfill(service).run(session)
        session.commit()
        joined = " ".join(report.notes)
        assert "no wallet" in joined
        assert "entitlements" in joined

    def test_the_report_serialises_for_an_operator_to_read(self, session, service):
        self._legacy_payment(session, "5000.00")
        session.commit()
        report = LegacyBackfill(service).run(session)
        session.commit()
        as_dict = report.as_dict()
        assert as_dict["reconciles"] is True
        assert as_dict["posted_total"] == "5000.00"
