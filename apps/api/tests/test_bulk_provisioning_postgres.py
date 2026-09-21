"""Bulk provisioning on real PostgreSQL — US-40, chunk 23.

The assignment asks for one specific scenario and this file builds it: **fifty
recipients, including invalid ones, a partial supplier failure, a lost response,
a duplicate submission and a worker restart.** `TestFiftyRecipients` is that
scenario end to end; everything above it isolates one rule so a failure says
which one broke.

Three strict-TDD categories apply at once — payments and idempotency, order and
provisioning idempotency including accepted-but-response-lost, and tenant
isolation — and every one of them is a database guarantee here: per-line
reservations in `ledger_reservations`, the idempotency constraint on
`bulk_jobs`, and the partial unique index tying one order item to one line.

The claim worth checking hardest is the one in `test_a_lost_response_is_never
_retried_blind`: an item whose supplier outcome is unknown is *not reachable*
from the retry path, because the alternative is a second eSIM bought for
somebody who already has one.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from app import model_registry  # noqa: F401
from app.auth.models import Organization, OrganizationType, Platform, User
from app.bulk.models import (
    ActivationRequestState,
    BulkItemState,
    BulkJob,
    BulkJobState,
)
from app.bulk.service import BulkError, BulkProvisioningService
from app.catalog.market import PublicationStatus, SalesMarket
from app.catalog.models import (
    LegalEntity,
    Product,
    ProductAllowance,
    ProductKind,
)
from app.connectivity.service import ConnectivityService
from app.fulfilment.service import FulfilmentService
from app.ledger.models import AccountKind, Direction, OwnerKind, Reservation
from app.ledger.service import LedgerService, Posting
from app.orders.models import Order, OrderItem, ProvisioningState
from app.people.models import OrganizationPerson, PersonStatus

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="per-line funding and one-line-one-order-item are database guarantees",
)

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
UNIT = Decimal("1000.00")
TABLES = (
    "activation_requests, bulk_job_items, bulk_jobs, entitlements, order_items, "
    "orders, organization_people, organization_teams, organization_cost_centres, "
    "product_allowances, products, sales_markets, legal_entities, "
    "journal_lines, journal_entries, "
    "ledger_reservations, ledger_accounts, organizations, users"
)


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: float) -> None:
        self.value += timedelta(**kwargs)


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
def ledger(clock):
    return LedgerService(clock=clock)


@pytest.fixture
def connectivity(clock):
    return ConnectivityService(FulfilmentService(clock=clock), clock=clock)


@pytest.fixture
def service(ledger, connectivity, clock):
    return BulkProvisioningService(
        ledger,
        connectivity=connectivity,
        carrier_provisioning_confirmed=True,
        clock=clock,
    )


def _organization(session: Session) -> Organization:
    organization = Organization(
        name=f"Org {uuid4().hex[:6]}",
        primary_contact_name="Contact",
        phone_number=f"+23490{uuid4().int % 10**8:08d}",
        email=f"org-{uuid4().hex[:8]}@example.test",
        password_hash="x",
        org_type=OrganizationType.ENTERPRISE,
    )
    session.add(organization)
    session.flush()
    return organization


def _entity(session: Session) -> LegalEntity:
    entity = LegalEntity(code=f"E{uuid4().hex[:6]}", name="Seller", country="NG")
    session.add(entity)
    session.flush()
    return entity


def _market(session: Session, entity: LegalEntity) -> SalesMarket:
    """A published market names the seller and the currency, as a quote's does.

    Idempotent, because `(country, currency)` is unique and a test that plans
    twice must not try to publish Nigeria twice.
    """
    found = session.exec(
        select(SalesMarket).where(
            SalesMarket.country == "NG", SalesMarket.currency == "NGN"
        )
    ).first()
    if found is not None:
        return found
    market = SalesMarket(
        country="NG",
        currency="NGN",
        status=PublicationStatus.PUBLISHED,
        legal_entity_id=entity.id,
        evidence_reference="test fixture",
        verified_at=NOW,
        published_at=NOW,
        created_at=NOW,
    )
    session.add(market)
    session.flush()
    return market


def _product(session: Session, kind: ProductKind = ProductKind.DATA) -> Product:
    product = Product(
        sku=f"sku-{uuid4().hex[:8]}", name="Work data 5GB", kind=kind
    )
    session.add(product)
    session.flush()
    session.add(
        ProductAllowance(
            product_id=product.id,
            data_bytes=5 * 1024**3,
            voice_seconds=0,
            validity_days=30,
        )
    )
    session.flush()
    return product


def _person(
    session: Session,
    organization: Organization,
    index: int,
    *,
    reachable: bool = True,
    archived: bool = False,
) -> OrganizationPerson:
    person = OrganizationPerson(
        organization_id=organization.id,
        full_name=f"Person {index}",
        email=f"person{index}-{uuid4().hex[:6]}@example.test" if reachable else None,
        external_reference=f"E-{index}-{uuid4().hex[:4]}" if not reachable else None,
        status=PersonStatus.ARCHIVED if archived else PersonStatus.ACTIVE,
        archived_at=NOW if archived else None,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(person)
    session.flush()
    return person


def _fund_organization(session, ledger, organization, amount: str) -> None:
    credit = ledger.account(
        session,
        "NGN",
        AccountKind.SERVICE_CREDIT,
        OwnerKind.ORGANIZATION,
        owner_organization_id=organization.id,
    )
    clearing = ledger.account(session, "NGN", AccountKind.SETTLEMENT_CLEARING)
    ledger.post(
        session,
        f"funding:{uuid4()}",
        [
            Posting(clearing, Direction.DEBIT, Decimal(amount)),
            Posting(credit, Direction.CREDIT, Decimal(amount)),
        ],
    )
    session.flush()


def _plan(service, session, organization, product, people, key="bulk-1", market=None):
    if market is None:
        market = _market(session, _entity(session))
    return service.plan(
        session,
        organization.id,
        idempotency_key=key,
        product=product,
        sales_market_id=market.id,
        person_ids=[person.id for person in people],
        currency="NGN",
        unit_amount=UNIT,
    )


def _awaiting_supplier(session: Session, job: BulkJob, item) -> None:
    """Put a fixture-confirmed line at the pre-answer boundary under test."""
    item.state = BulkItemState.ORDERED
    item.provisioned_at = None
    job.provisioned_count -= 1
    job.state = BulkJobState.PROVISIONING
    job.completed_at = None
    if item.order_item_id is not None:
        order_item = session.get(OrderItem, item.order_item_id)
        assert order_item is not None
        order_item.provisioning_state = ProvisioningState.REQUESTED
        session.add(order_item)
    session.add(item)
    session.add(job)
    session.flush()


class TestPlanning:
    def test_a_job_holds_no_money_and_buys_nothing(
        self, session, service, ledger, clock
    ):
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "50000.00")
        product = _product(session)
        people = [_person(session, organization, index) for index in range(3)]

        job = _plan(service, session, organization, product, people)

        assert job.state is BulkJobState.PLANNED
        assert session.exec(select(Reservation)).all() == []
        assert session.exec(select(Order)).all() == []

    def test_reusing_a_key_for_different_recipients_is_a_conflict(
        self, session, service
    ):
        organization = _organization(session)
        product = _product(session)
        first = _person(session, organization, 1)
        second = _person(session, organization, 2)
        _plan(service, session, organization, product, [first], key="same-key")

        with pytest.raises(BulkError) as excinfo:
            _plan(
                service,
                session,
                organization,
                product,
                [second],
                key="same-key",
            )

        assert excinfo.value.code == "idempotency_conflict"


class TestConcurrentCalls:
    def test_identical_plans_converge_on_one_job(
        self, session, engine, service, clock
    ):
        organization = _organization(session)
        entity = _entity(session)
        market = _market(session, entity)
        product = _product(session)
        people = [_person(session, organization, index) for index in range(2)]
        organization_id = organization.id
        market_id = market.id
        product_id = product.id
        person_ids = [person.id for person in people]
        session.commit()
        barrier = Barrier(2)

        def plan() -> str:
            with Session(engine) as concurrent_session:
                concurrent_product = concurrent_session.get(Product, product_id)
                assert concurrent_product is not None
                barrier.wait()
                job = BulkProvisioningService(
                    LedgerService(clock=clock), clock=clock
                ).plan(
                    concurrent_session,
                    organization_id,
                    idempotency_key="concurrent-plan",
                    product=concurrent_product,
                    sales_market_id=market_id,
                    person_ids=person_ids,
                    currency="NGN",
                    unit_amount=UNIT,
                )
                concurrent_session.commit()
                return str(job.id)

        with ThreadPoolExecutor(max_workers=2) as pool:
            job_ids = list(pool.map(lambda _index: plan(), range(2)))

        assert len(set(job_ids)) == 1
        with Session(engine) as check:
            jobs = check.exec(select(BulkJob)).all()
            assert len(jobs) == 1

    def test_concurrent_funding_takes_one_hold(
        self, session, engine, service, ledger, clock
    ):
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "5000.00")
        product = _product(session)
        person = _person(session, organization, 1)
        job = _plan(service, session, organization, product, [person])
        job_id = job.id
        session.commit()
        barrier = Barrier(2)

        def fund() -> int:
            with Session(engine) as concurrent_session:
                concurrent_job = concurrent_session.get(BulkJob, job_id)
                assert concurrent_job is not None
                barrier.wait()
                progress = BulkProvisioningService(
                    LedgerService(clock=clock), clock=clock
                ).fund(concurrent_session, concurrent_job)
                concurrent_session.commit()
                return progress.reserved

        with ThreadPoolExecutor(max_workers=2) as pool:
            reserved = list(pool.map(lambda _index: fund(), range(2)))

        assert reserved == [1, 1]
        with Session(engine) as check:
            reservations = check.exec(select(Reservation)).all()
            assert len(reservations) == 1
            persisted = check.get(BulkJob, job_id)
            assert persisted is not None
            assert persisted.reserved_count == 1

    def test_a_single_use_token_has_one_winner_under_concurrency(
        self, session, engine, service, ledger, clock
    ):
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "5000.00")
        entity = _entity(session)
        product = _product(session)
        person = _person(session, organization, 1)
        job = _plan(service, session, organization, product, [person])
        service.fund(session, job)
        service.provision(session, job, seller_legal_entity_id=entity.id)
        item = service.items(session, job)[0]
        _request, token = service.issue_activation_request(session, job, item)
        users = [
            User(
                phone_number=f"+2348{index}{uuid4().int % 10**8:08d}",
                first_name=f"Claimer {index}",
                platform=Platform.ANDROID,
            )
            for index in range(2)
        ]
        session.add_all(users)
        session.flush()
        user_ids = [user.id for user in users]
        order_item_id = item.order_item_id
        session.commit()
        barrier = Barrier(2)

        def redeem(user_id):
            with Session(engine) as concurrent_session:
                user = concurrent_session.get(User, user_id)
                assert user is not None
                barrier.wait()
                try:
                    BulkProvisioningService(
                        LedgerService(clock=clock), clock=clock
                    ).redeem_activation_request(concurrent_session, token, user)
                    concurrent_session.commit()
                    return "redeemed"
                except BulkError as error:
                    concurrent_session.rollback()
                    return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(redeem, user_ids))

        assert sorted(outcomes) == ["activation_request_spent", "redeemed"]
        with Session(engine) as check:
            order_item = check.get(OrderItem, order_item_id)
            assert order_item is not None
            assert order_item.recipient_user_id in user_ids

    def test_a_replayed_submission_is_the_same_job(
        self, session, service, ledger
    ):
        """A double click is one job, or it is fifty extra lines and charges."""
        organization = _organization(session)
        product = _product(session)
        people = [_person(session, organization, index) for index in range(3)]

        first = _plan(service, session, organization, product, people)
        second = _plan(service, session, organization, product, people)

        assert first.id == second.id
        assert len(service.items(session, first)) == 3

    def test_a_recipient_who_left_is_marked_not_charged(
        self, session, service, ledger
    ):
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "50000.00")
        product = _product(session)
        gone = _person(session, organization, 1, archived=True)

        job = _plan(service, session, organization, product, [gone])
        service.fund(session, job)

        item = service.items(session, job)[0]
        assert item.state is BulkItemState.INVALID
        assert item.error_code == "recipient_archived"
        assert item.reservation_id is None

    def test_a_recipient_nobody_can_be_told_about_is_refused(
        self, session, service
    ):
        """A paid line for somebody with no email and no phone helps nobody."""
        organization = _organization(session)
        product = _product(session)
        unreachable = _person(session, organization, 1, reachable=False)

        job = _plan(service, session, organization, product, [unreachable])

        assert service.items(session, job)[0].error_code == "recipient_unreachable"

    def test_another_organizations_person_cannot_be_a_recipient(
        self, session, service
    ):
        """And is indistinguishable from one that does not exist."""
        mine = _organization(session)
        theirs = _organization(session)
        product = _product(session)
        outsider = _person(session, theirs, 1)

        job = _plan(service, session, mine, product, [outsider])

        item = service.items(session, job)[0]
        assert item.state is BulkItemState.INVALID
        assert item.error_code == "recipient_not_found"

    def test_the_same_person_twice_in_one_submission_is_one_line(
        self, session, service
    ):
        organization = _organization(session)
        product = _product(session)
        person = _person(session, organization, 1)

        job = service.plan(
            session,
            organization.id,
            idempotency_key="bulk-dup",
            product=product,
            sales_market_id=_market(session, _entity(session)).id,
            person_ids=[person.id, person.id],
            currency="NGN",
            unit_amount=UNIT,
        )

        assert len(service.items(session, job)) == 1
        assert job.recipient_count == 1


class TestPerLineFunding:
    def test_every_recipient_gets_their_own_hold(
        self, session, service, ledger, clock
    ):
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "5000.00")
        product = _product(session)
        people = [_person(session, organization, index) for index in range(3)]
        job = _plan(service, session, organization, product, people)

        progress = service.fund(session, job)

        assert progress.reserved == 3
        reservations = session.exec(select(Reservation)).all()
        assert len(reservations) == 3
        assert all(row.amount == UNIT for row in reservations)

    def test_partial_funding_serves_who_it_can(
        self, session, service, ledger
    ):
        """Forty of fifty lines is better than an error message."""
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "2000.00")
        product = _product(session)
        people = [_person(session, organization, index) for index in range(3)]
        job = _plan(service, session, organization, product, people)

        progress = service.fund(session, job)

        assert progress.reserved == 2
        assert progress.failed == 1
        failed = [
            item
            for item in service.items(session, job)
            if item.state is BulkItemState.FAILED
        ]
        assert failed[0].error_code == "insufficient_funds"

    def test_cancelling_one_line_releases_only_that_hold(
        self, session, service, ledger, clock
    ):
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "5000.00")
        product = _product(session)
        people = [_person(session, organization, index) for index in range(3)]
        job = _plan(service, session, organization, product, people)
        service.fund(session, job)
        credit = ledger.account(
            session,
            "NGN",
            AccountKind.SERVICE_CREDIT,
            OwnerKind.ORGANIZATION,
            owner_organization_id=organization.id,
        )
        assert ledger.available(session, credit) == Decimal("2000.00")

        item = service.items(session, job)[0]
        service.cancel_item(session, job, item, reason="not_needed")

        assert ledger.available(session, credit) == Decimal("3000.00")


class TestProvisioning:
    def test_order_total_excludes_invalid_and_unfunded_recipients(
        self, session, service, ledger
    ):
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "2000.00")
        entity = _entity(session)
        product = _product(session)
        people = [_person(session, organization, index) for index in range(3)]
        job = _plan(service, session, organization, product, people)
        service.fund(session, job)

        service.provision(session, job, seller_legal_entity_id=entity.id)

        order = session.get(Order, job.order_id)
        assert order is not None
        assert order.total_amount == Decimal("2000.00")
        assert len(session.exec(select(OrderItem)).all()) == 2

    def test_each_recipient_gets_one_order_item(
        self, session, service, ledger, clock
    ):
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "5000.00")
        entity = _entity(session)
        product = _product(session)
        people = [_person(session, organization, index) for index in range(3)]
        job = _plan(service, session, organization, product, people)
        service.fund(session, job)

        progress = service.provision(
            session, job, seller_legal_entity_id=entity.id
        )

        assert progress.provisioned == 3
        items = session.exec(select(OrderItem)).all()
        assert len(items) == 3
        assert all(item.quantity == 1 for item in items)
        assert all(
            item.provisioning_state is ProvisioningState.PROVISIONED for item in items
        )

    def test_a_line_is_not_bound_to_anybody_until_it_is_claimed(
        self, session, service, ledger, clock
    ):
        """An organization may buy for somebody who has no account with us."""
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "5000.00")
        entity = _entity(session)
        product = _product(session)
        person = _person(session, organization, 1)
        job = _plan(service, session, organization, product, [person])
        service.fund(session, job)
        service.provision(session, job, seller_legal_entity_id=entity.id)

        order_item = session.exec(select(OrderItem)).one()
        assert order_item.recipient_user_id is None

    def test_provisioning_twice_does_not_create_a_second_line(
        self, session, service, ledger, clock
    ):
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "5000.00")
        entity = _entity(session)
        product = _product(session)
        people = [_person(session, organization, index) for index in range(2)]
        job = _plan(service, session, organization, product, people)
        service.fund(session, job)

        service.provision(session, job, seller_legal_entity_id=entity.id)
        service.provision(session, job, seller_legal_entity_id=entity.id)

        assert len(session.exec(select(OrderItem)).all()) == 2
        assert len(session.exec(select(Order)).all()) == 1

    def test_an_internet_only_product_needs_no_carrier_profile(
        self, session, service, ledger, clock
    ):
        """The calling amendment: provision the grant, buy nothing from a carrier."""
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "5000.00")
        entity = _entity(session)
        product = _product(session, ProductKind.VOICE)
        person = _person(session, organization, 1)
        job = _plan(service, session, organization, product, [person])
        service.fund(session, job)

        progress = service.provision(
            session, job, seller_legal_entity_id=entity.id
        )

        assert progress.provisioned == 1
        from app.connectivity.models import CarrierLine, EsimInstallation

        assert session.exec(select(CarrierLine)).all() == []
        assert session.exec(select(EsimInstallation)).all() == []


class TestLostAndFailedOutcomes:
    def test_a_confirmed_line_cannot_be_downgraded_to_unknown(
        self, session, service, ledger
    ):
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "5000.00")
        entity = _entity(session)
        product = _product(session)
        person = _person(session, organization, 1)
        job = _plan(service, session, organization, product, [person])
        service.fund(session, job)
        service.provision(session, job, seller_legal_entity_id=entity.id)
        item = service.items(session, job)[0]

        with pytest.raises(BulkError) as excinfo:
            service.mark_unknown(session, job, item, "late_timeout")

        assert excinfo.value.code == "item_not_awaiting_supplier"

    def test_a_lost_response_is_never_retried_blind(
        self, session, service, ledger, clock
    ):
        """The property this chunk is built around.

        An item whose supplier outcome is unknown is not in the retry list at
        all — a caller that ignored the reconcile list entirely still could not
        buy a second profile for that recipient.
        """
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "5000.00")
        entity = _entity(session)
        product = _product(session)
        people = [_person(session, organization, index) for index in range(2)]
        job = _plan(service, session, organization, product, people)
        service.fund(session, job)
        service.provision(session, job, seller_legal_entity_id=entity.id)

        item = service.items(session, job)[0]
        _awaiting_supplier(session, job, item)
        service.mark_unknown(session, job, item, "supplier_timeout")

        to_reconcile, to_retry = service.resumable(session, job)

        assert [row.id for row in to_reconcile] == [item.id]
        assert item.id not in [row.id for row in to_retry]

    def test_an_unknown_item_keeps_its_hold(
        self, session, service, ledger, clock
    ):
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "5000.00")
        entity = _entity(session)
        product = _product(session)
        person = _person(session, organization, 1)
        job = _plan(service, session, organization, product, [person])
        service.fund(session, job)
        service.provision(session, job, seller_legal_entity_id=entity.id)
        item = service.items(session, job)[0]

        _awaiting_supplier(session, job, item)
        service.mark_unknown(session, job, item, "supplier_timeout")

        reservation = session.get(Reservation, item.reservation_id)
        outstanding = (
            reservation.amount
            - reservation.settled_amount
            - reservation.released_amount
        )
        assert outstanding == UNIT

    def test_reconciliation_that_cannot_answer_leaves_it_unknown(
        self, session, service, ledger, clock
    ):
        """Silence is not permission."""
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "5000.00")
        entity = _entity(session)
        product = _product(session)
        person = _person(session, organization, 1)
        job = _plan(service, session, organization, product, [person])
        service.fund(session, job)
        service.provision(session, job, seller_legal_entity_id=entity.id)
        item = service.items(session, job)[0]
        _awaiting_supplier(session, job, item)
        service.mark_unknown(session, job, item, "supplier_timeout")

        service.resume(
            session,
            job,
            seller_legal_entity_id=entity.id,
            reconcile=lambda _item: None,
        )

        assert service.items(session, job)[0].state is BulkItemState.UNKNOWN

    def test_reconciliation_that_confirms_the_work_completes_the_line(
        self, session, service, ledger, clock
    ):
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "5000.00")
        entity = _entity(session)
        product = _product(session)
        person = _person(session, organization, 1)
        job = _plan(service, session, organization, product, [person])
        service.fund(session, job)
        service.provision(session, job, seller_legal_entity_id=entity.id)
        item = service.items(session, job)[0]
        _awaiting_supplier(session, job, item)
        service.mark_unknown(session, job, item, "supplier_timeout")

        service.resume(
            session,
            job,
            seller_legal_entity_id=entity.id,
            reconcile=lambda _item: True,
        )

        assert service.items(session, job)[0].state is BulkItemState.PROVISIONED

    def test_an_unknown_line_cannot_be_cancelled_without_reconciling(
        self, session, service, ledger, clock
    ):
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "5000.00")
        entity = _entity(session)
        product = _product(session)
        person = _person(session, organization, 1)
        job = _plan(service, session, organization, product, [person])
        service.fund(session, job)
        service.provision(session, job, seller_legal_entity_id=entity.id)
        item = service.items(session, job)[0]
        _awaiting_supplier(session, job, item)
        service.mark_unknown(session, job, item, "supplier_timeout")

        with pytest.raises(BulkError) as excinfo:
            service.cancel_item(session, job, item, reason="giving_up")
        assert excinfo.value.code == "item_outcome_unknown"

    def test_a_provisioned_line_is_refunded_not_cancelled(
        self, session, service, ledger, clock
    ):
        """Releasing a hold for a service somebody has is giving money away."""
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "5000.00")
        entity = _entity(session)
        product = _product(session)
        person = _person(session, organization, 1)
        job = _plan(service, session, organization, product, [person])
        service.fund(session, job)
        service.provision(session, job, seller_legal_entity_id=entity.id)
        item = service.items(session, job)[0]

        with pytest.raises(BulkError) as excinfo:
            service.cancel_item(session, job, item, reason="changed_mind")
        assert excinfo.value.code == "item_already_provisioned"


class TestActivationRequests:
    def _provisioned_job(self, session, service, ledger, clock):
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "5000.00")
        entity = _entity(session)
        product = _product(session)
        person = _person(session, organization, 1)
        job = _plan(service, session, organization, product, [person])
        service.fund(session, job)
        service.provision(session, job, seller_legal_entity_id=entity.id)
        return organization, job, service.items(session, job)[0]

    def test_a_request_is_not_an_installation(
        self, session, service, ledger, clock
    ):
        """The assignment's rule, asserted rather than intended.

        A request that has been issued and even redeemed says nothing about a
        profile reaching a handset or a network seeing it.
        """
        _, job, item = self._provisioned_job(session, service, ledger, clock)
        request, _token = service.issue_activation_request(session, job, item)

        from app.connectivity.models import CarrierLine, EsimInstallation

        assert request.state is ActivationRequestState.PENDING
        assert session.exec(select(EsimInstallation)).all() == []
        assert session.exec(select(CarrierLine)).all() == []

    def test_the_token_is_returned_once_and_stored_as_a_hash(
        self, session, service, ledger, clock
    ):
        _, job, item = self._provisioned_job(session, service, ledger, clock)
        request, token = service.issue_activation_request(session, job, item)

        assert token
        assert token not in request.token_hash
        assert len(request.token_hash) == 64

    def test_redeeming_binds_the_line_to_the_account_that_claimed_it(
        self, session, service, ledger, clock
    ):
        _, job, item = self._provisioned_job(session, service, ledger, clock)
        _request, token = service.issue_activation_request(session, job, item)
        claimer = User(
            phone_number=f"+23480{uuid4().int % 10**8:08d}",
            first_name="Claimer",
            platform=Platform.ANDROID,
        )
        session.add(claimer)
        session.flush()

        service.redeem_activation_request(session, token, claimer)

        order_item = session.get(OrderItem, item.order_item_id)
        assert order_item.recipient_user_id == claimer.id

    def test_a_token_is_spent_once(self, session, service, ledger, clock):
        _, job, item = self._provisioned_job(session, service, ledger, clock)
        _request, token = service.issue_activation_request(session, job, item)
        first = User(
            phone_number=f"+23480{uuid4().int % 10**8:08d}",
            first_name="First",
            platform=Platform.ANDROID,
        )
        second = User(
            phone_number=f"+23481{uuid4().int % 10**8:08d}",
            first_name="Second",
            platform=Platform.ANDROID,
        )
        session.add(first)
        session.add(second)
        session.flush()
        service.redeem_activation_request(session, token, first)

        with pytest.raises(BulkError) as excinfo:
            service.redeem_activation_request(session, token, second)
        assert excinfo.value.code == "activation_request_spent"

    def test_an_expired_request_cannot_be_claimed(
        self, session, service, ledger, clock
    ):
        _, job, item = self._provisioned_job(session, service, ledger, clock)
        _request, token = service.issue_activation_request(session, job, item)
        clock.advance(days=31)
        claimer = User(
            phone_number=f"+23480{uuid4().int % 10**8:08d}",
            first_name="Late",
            platform=Platform.ANDROID,
        )
        session.add(claimer)
        session.flush()

        with pytest.raises(BulkError) as excinfo:
            service.redeem_activation_request(session, token, claimer)
        assert excinfo.value.code == "activation_request_expired"

    def test_a_line_cannot_be_invited_before_it_exists(
        self, session, service, ledger, clock
    ):
        organization = _organization(session)
        _fund_organization(session, ledger, organization, "5000.00")
        product = _product(session)
        person = _person(session, organization, 1)
        job = _plan(service, session, organization, product, [person])
        service.fund(session, job)
        item = service.items(session, job)[0]

        with pytest.raises(BulkError) as excinfo:
            service.issue_activation_request(session, job, item)
        assert excinfo.value.code == "line_not_ready"

    def test_only_one_live_invitation_exists_per_line(
        self, session, service, ledger, clock
    ):
        """Two live tokens for one line is two people who can claim it."""
        _, job, item = self._provisioned_job(session, service, ledger, clock)
        service.issue_activation_request(session, job, item)

        with pytest.raises(BulkError) as excinfo:
            service.issue_activation_request(session, job, item)
        assert excinfo.value.code == "activation_request_exists"


class TestFiftyRecipients:
    """The scenario the assignment names, in one test.

    Fifty recipients: forty-six serviceable, two who left, one unreachable, one
    from another organization. Then a partial supplier failure, a lost response,
    a duplicate submission and a worker restart — and at the end, the numbers
    have to add up and nobody may be charged twice.
    """

    def test_the_whole_scenario(self, session, service, ledger, clock, engine):
        organization = _organization(session)
        other = _organization(session)
        entity = _entity(session)
        product = _product(session)
        # Enough for forty-six lines and not a naira more, so a miscount shows
        # up as a funding failure rather than as a silent overspend.
        _fund_organization(session, ledger, organization, "46000.00")

        serviceable = [_person(session, organization, i) for i in range(46)]
        left = [
            _person(session, organization, 100 + i, archived=True)
            for i in range(2)
        ]
        unreachable = [_person(session, organization, 200, reachable=False)]
        outsider = [_person(session, other, 300)]
        everybody = serviceable + left + unreachable + outsider
        assert len(everybody) == 50

        job = _plan(service, session, organization, product, everybody, key="fifty")

        # A duplicate submission, exactly as a double-clicked button sends it.
        replay = _plan(service, session, organization, product, everybody, key="fifty")
        assert replay.id == job.id
        assert len(service.items(session, job)) == 50

        progress = service.fund(session, job)
        assert progress.reserved == 46
        assert progress.invalid == 4

        progress = service.provision(session, job, seller_legal_entity_id=entity.id)
        assert progress.provisioned == 46

        # A partial supplier failure and a lost response, after the fact.
        items = [
            item
            for item in service.items(session, job)
            if item.state is BulkItemState.PROVISIONED
        ]
        failed_item, unknown_item = items[0], items[1]
        _awaiting_supplier(session, job, failed_item)
        _awaiting_supplier(session, job, unknown_item)
        service.mark_failed(session, job, failed_item, "supplier_rejected")
        service.mark_unknown(session, job, unknown_item, "supplier_timeout")

        # The worker restarts: a fresh service, nothing remembered in memory.
        restarted = BulkProvisioningService(
            LedgerService(clock=clock),
            connectivity=ConnectivityService(
                FulfilmentService(clock=clock), clock=clock
            ),
            carrier_provisioning_confirmed=True,
            clock=clock,
        )
        to_reconcile, to_retry = restarted.resumable(session, job)
        assert [row.id for row in to_reconcile] == [unknown_item.id]
        assert [row.id for row in to_retry] == [failed_item.id]

        progress = restarted.resume(
            session,
            job,
            seller_legal_entity_id=entity.id,
            # The supplier confirms it did provision the one we lost.
            reconcile=lambda _item: True,
        )

        assert progress.provisioned == 46
        assert progress.invalid == 4
        assert progress.unknown == 0
        assert progress.failed == 0

        # No duplicate charge, no duplicate line, no duplicate assignment.
        order_items = session.exec(select(OrderItem)).all()
        assert len(order_items) == 46
        # Forty-six lines, forty-six *live* holds. There are more reservation
        # rows than that on purpose: the line that was definitively refused had
        # its original hold released, and the retry took a fresh one. A released
        # reservation is history and does not disappear because it was reused.
        held = [
            row
            for row in session.exec(select(Reservation)).all()
            if row.amount - row.settled_amount - row.released_amount > 0
        ]
        assert len(held) == 46
        people_with_lines = [
            item.person_id
            for item in service.items(session, job)
            if item.order_item_id is not None
        ]
        assert len(people_with_lines) == len(set(people_with_lines)) == 46

        # Nobody from the other organization got anything.
        assert all(
            session.get(OrganizationPerson, person_id).organization_id
            == organization.id
            for person_id in people_with_lines
        )

        # And the money adds up: 46 lines held at 1,000 each.
        credit = ledger.account(
            session,
            "NGN",
            AccountKind.SERVICE_CREDIT,
            OwnerKind.ORGANIZATION,
            owner_organization_id=organization.id,
        )
        assert ledger.available(session, credit) == Decimal("0.00")
        assert ledger.balance(session, credit) == Decimal("46000.00")

    def test_a_partially_completed_job_says_so(
        self, session, service, ledger, clock
    ):
        """Forty-seven working lines is not a failed job, and not a finished one."""
        organization = _organization(session)
        entity = _entity(session)
        product = _product(session)
        _fund_organization(session, ledger, organization, "2000.00")
        people = [_person(session, organization, index) for index in range(3)]
        job = _plan(service, session, organization, product, people, key="partial")

        service.fund(session, job)
        progress = service.provision(session, job, seller_legal_entity_id=entity.id)

        assert progress.state is BulkJobState.PARTIALLY_COMPLETED
        assert progress.provisioned == 2
        assert progress.failed == 1
