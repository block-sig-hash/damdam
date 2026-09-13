"""Enterprise funding, reporting and offboarding — US-40, chunk 24.

The test this file exists for is
`test_a_personal_line_survives_work_offboarding`. Everything else supports it.

Offboarding is the most destructive routine operation this product has, and the
failure is not a wrong number on a screen: it is somebody losing their own phone
service on the day they change jobs. The scoping that prevents it — every work
query runs through `orders.payer_organization_id` — is a mechanism rather than a
filter somebody remembers, and this file proves the mechanism holds.

The reporting tests are about a quieter failure: a departmental total that does
not say how fresh it is, or that counts evidence-only usage twice. Both produce
a reconciliation meeting where the numbers do not match and nobody can say why.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from app import model_registry  # noqa: F401
from app.auth.models import Organization, OrganizationType, Platform, User
from app.bulk.models import (
    ActivationRequest,
    ActivationRequestState,
    BulkItemState,
    BulkJob,
    BulkJobItem,
    BulkJobState,
)
from app.catalog.market import PublicationStatus, SalesMarket
from app.catalog.models import LegalEntity, Product, ProductAllowance, ProductKind
from app.connectivity.models import ActivationState, CarrierLine, Entitlement
from app.controls.models import OrganizationSpendingPolicy
from app.enterprise.models import (
    OffboardingActionKind,
    OffboardingActionState,
    OffboardingState,
)
from app.enterprise.offboarding import OffboardingError, OffboardingService
from app.enterprise.reporting import EnterpriseReportingService
from app.ledger.models import AccountKind, Direction, OwnerKind
from app.ledger.service import LedgerService, Posting
from app.orders.models import Order, OrderItem, PaymentState
from app.organizations.models import (
    MembershipStatus,
    OrganizationMember,
    OrganizationRole,
)
from app.people.models import (
    OrganizationCostCentre,
    OrganizationPerson,
    OrganizationTeam,
    PersonStatus,
)
from app.usage.models import (
    AdapterChannel,
    UsageKind,
    UsageRecord,
    UsageSource,
    UsageState,
)

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="offboarding scope and report reconciliation are database behaviour",
)

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
TABLES = (
    "offboarding_actions, organization_offboardings, activation_requests, "
    "bulk_job_items, bulk_jobs, usage_records, carrier_lines, entitlements, "
    "order_items, orders, organization_people, organization_teams, "
    "organization_cost_centres, organization_spending_policies, "
    "product_allowances, products, sales_markets, legal_entities, "
    "journal_lines, journal_entries, ledger_reservations, ledger_accounts, "
    "organization_members, organizations, users"
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
def offboarding(ledger, clock):
    return OffboardingService(ledger, clock=clock)


@pytest.fixture
def reporting(ledger, clock):
    return EnterpriseReportingService(ledger, clock=clock)


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


def _user(session: Session, label: str = "employee") -> User:
    user = User(
        phone_number=f"+23486{uuid4().int % 10**8:08d}",
        first_name=label,
        platform=Platform.ANDROID,
    )
    session.add(user)
    session.flush()
    return user


def _person(
    session: Session,
    organization: Organization,
    *,
    user: User | None = None,
    team: OrganizationTeam | None = None,
    centre: OrganizationCostCentre | None = None,
) -> OrganizationPerson:
    person = OrganizationPerson(
        organization_id=organization.id,
        user_id=user.id if user else None,
        full_name="Ada Obi",
        email=f"ada-{uuid4().hex[:6]}@example.test",
        team_id=team.id if team else None,
        cost_centre_id=centre.id if centre else None,
        status=PersonStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(person)
    session.flush()
    return person


def _entity(session: Session) -> LegalEntity:
    entity = LegalEntity(code=f"E{uuid4().hex[:6]}", name="Seller", country="NG")
    session.add(entity)
    session.flush()
    return entity


def _product(session: Session) -> Product:
    product = Product(
        sku=f"sku-{uuid4().hex[:8]}", name="Work data", kind=ProductKind.DATA
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


def _line(
    session: Session,
    *,
    entity: LegalEntity,
    product: Product,
    holder: User,
    payer_organization: Organization | None,
    payer_user: User | None = None,
    amount: str = "1000.00",
    activation: ActivationState = ActivationState.ACTIVE,
) -> tuple[Order, OrderItem, Entitlement, CarrierLine]:
    """A line, bought by whoever paid for it.

    `payer_organization` versus `payer_user` is the entire distinction between a
    work line and a personal one, so the fixture takes them as separate
    arguments and the tests set exactly one.
    """
    order = Order(
        reference=f"ORD-{uuid4().hex[:8].upper()}",
        seller_legal_entity_id=entity.id,
        payer_user_id=payer_user.id if payer_user else None,
        payer_organization_id=payer_organization.id if payer_organization else None,
        currency="NGN",
        total_amount=Decimal(amount),
        payment_state=PaymentState.PAID,
        placed_at=NOW,
    )
    session.add(order)
    session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        recipient_user_id=holder.id,
        quantity=1,
        unit_currency="NGN",
        unit_amount=Decimal(amount),
    )
    session.add(item)
    session.flush()
    entitlement = Entitlement(
        order_item_id=item.id,
        holder_user_id=holder.id,
        product_id=product.id,
        data_bytes_total=5 * 1024**3,
        voice_seconds_total=0,
        granted_at=NOW,
    )
    session.add(entitlement)
    session.flush()
    line = CarrierLine(
        entitlement_id=entitlement.id,
        carrier="telnyx",
        carrier_line_reference=f"line-{uuid4().hex[:10]}",
        activation_state=activation,
        created_at=NOW,
    )
    session.add(line)
    session.flush()
    return order, item, entitlement, line


def _fund(session, ledger, organization, amount: str = "10000.00"):
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
    return credit


class TestOffboardingPreservesPersonalService:
    def test_a_personal_line_survives_work_offboarding(
        self, session, offboarding, ledger, clock
    ):
        """The test this chunk exists to pass.

        Somebody leaves their job. Their work line is suspended; the phone plan
        they bought themselves is untouched — not "usually", not "unless the
        holder matches", but because the query that finds work lines runs
        through `orders.payer_organization_id` and a personal order is not in it.
        """
        organization = _organization(session)
        employee = _user(session)
        person = _person(session, organization, user=employee)
        entity = _entity(session)
        product = _product(session)

        _order, _item, _ent, work_line = _line(
            session,
            entity=entity,
            product=product,
            holder=employee,
            payer_organization=organization,
        )
        _order2, _item2, _ent2, personal_line = _line(
            session,
            entity=entity,
            product=product,
            holder=employee,
            payer_organization=None,
            payer_user=employee,
        )

        offboarding.offboard(session, organization.id, person.id)

        run = offboarding.history(session, organization.id)[0]
        actions = offboarding.actions(session, run)

        # The work line has a suspension request against it.
        suspended = [
            action
            for action in actions
            if action.kind is OffboardingActionKind.SUSPEND_LINE
            and action.target_reference == f"line:{work_line.id}"
        ]
        assert len(suspended) == 1

        # The personal line has nothing against it, at all.
        touched = [
            action
            for action in actions
            if action.target_reference == f"line:{personal_line.id}"
        ]
        assert touched == []
        assert (
            session.get(CarrierLine, personal_line.id).activation_state
            is ActivationState.ACTIVE
        )

    def test_a_personal_order_is_not_in_the_work_line_query(
        self, session, offboarding
    ):
        """Proved directly, because the whole guarantee rests on this query."""
        organization = _organization(session)
        employee = _user(session)
        person = _person(session, organization, user=employee)
        entity = _entity(session)
        product = _product(session)
        _line(
            session,
            entity=entity,
            product=product,
            holder=employee,
            payer_organization=None,
            payer_user=employee,
        )

        lines = offboarding._work_lines(session, organization.id, person)

        assert lines == []


class TestOffboardingEndsWorkAccess:
    def test_membership_is_revoked_immediately(self, session, offboarding, clock):
        organization = _organization(session)
        employee = _user(session)
        person = _person(session, organization, user=employee)
        membership = OrganizationMember(
            organization_id=organization.id,
            user_id=employee.id,
            role=OrganizationRole.MEMBER,
            status=MembershipStatus.ACTIVE,
        )
        session.add(membership)
        session.flush()

        offboarding.offboard(session, organization.id, person.id)

        assert membership.status is MembershipStatus.REVOKED
        assert membership.revoked_at is not None

    def test_unclaimed_invitations_are_withdrawn(self, session, offboarding, clock):
        organization = _organization(session)
        person = _person(session, organization)
        product = _product(session)
        entity = _entity(session)
        market = SalesMarket(
            country="NG",
            currency="NGN",
            status=PublicationStatus.PUBLISHED,
            legal_entity_id=entity.id,
            evidence_reference="fixture",
            verified_at=NOW,
            published_at=NOW,
            created_at=NOW,
        )
        session.add(market)
        session.flush()
        job = BulkJob(
            organization_id=organization.id,
            idempotency_key="job-1",
            product_id=product.id,
            sales_market_id=market.id,
            state=BulkJobState.PROVISIONING,
            currency="NGN",
            unit_amount=Decimal("1000.00"),
            recipient_count=1,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(job)
        session.flush()
        item = BulkJobItem(
            job_id=job.id,
            person_id=person.id,
            state=BulkItemState.PROVISIONED,
            updated_at=NOW,
        )
        session.add(item)
        session.flush()
        request = ActivationRequest(
            organization_id=organization.id,
            bulk_job_item_id=item.id,
            person_id=person.id,
            token_hash="a" * 64,
            state=ActivationRequestState.SENT,
            expires_at=NOW + timedelta(days=30),
            created_at=NOW,
        )
        session.add(request)
        session.flush()

        offboarding.offboard(session, organization.id, person.id)

        assert request.state is ActivationRequestState.REVOKED
        assert request.revoked_reason == "offboarded"

    def test_a_funded_but_unprovisioned_line_is_cancelled_and_released(
        self, session, offboarding, ledger, clock
    ):
        organization = _organization(session)
        credit = _fund(session, ledger, organization, "5000.00")
        person = _person(session, organization)
        product = _product(session)
        entity = _entity(session)
        market = SalesMarket(
            country="NG",
            currency="NGN",
            status=PublicationStatus.PUBLISHED,
            legal_entity_id=entity.id,
            evidence_reference="fixture",
            verified_at=NOW,
            published_at=NOW,
            created_at=NOW,
        )
        session.add(market)
        session.flush()
        job = BulkJob(
            organization_id=organization.id,
            idempotency_key="job-2",
            product_id=product.id,
            sales_market_id=market.id,
            state=BulkJobState.FUNDED,
            currency="NGN",
            unit_amount=Decimal("1000.00"),
            recipient_count=1,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(job)
        session.flush()
        reservation = ledger.reserve(
            session, credit, Decimal("1000.00"), "bulk:test:item"
        )
        item = BulkJobItem(
            job_id=job.id,
            person_id=person.id,
            state=BulkItemState.RESERVED,
            reservation_id=reservation.id,
            updated_at=NOW,
        )
        session.add(item)
        session.flush()
        assert ledger.available(session, credit) == Decimal("4000.00")

        offboarding.offboard(session, organization.id, person.id)

        assert item.state is BulkItemState.CANCELLED
        assert ledger.available(session, credit) == Decimal("5000.00")

    def test_the_person_is_archived_not_deleted(self, session, offboarding):
        organization = _organization(session)
        person = _person(session, organization)

        offboarding.offboard(session, organization.id, person.id)

        kept = session.get(OrganizationPerson, person.id)
        assert kept is not None
        assert kept.status is PersonStatus.ARCHIVED


class TestPendingCarrierActionsAreVisible:
    def test_a_live_line_is_pending_not_confirmed(
        self, session, offboarding, clock
    ):
        """An administrator told "done" about a live line finds out by invoice."""
        organization = _organization(session)
        employee = _user(session)
        person = _person(session, organization, user=employee)
        entity = _entity(session)
        product = _product(session)
        _line(
            session,
            entity=entity,
            product=product,
            holder=employee,
            payer_organization=organization,
        )

        summary = offboarding.offboard(session, organization.id, person.id)

        assert summary.state is OffboardingState.COMPLETED_WITH_PENDING
        assert summary.pending_carrier == 1
        assert summary.has_pending

    def test_an_offboarding_with_nothing_outstanding_is_completed(
        self, session, offboarding
    ):
        organization = _organization(session)
        person = _person(session, organization)

        summary = offboarding.offboard(session, organization.id, person.id)

        assert summary.state is OffboardingState.COMPLETED
        assert summary.pending_carrier == 0

    def test_confirming_the_carrier_answer_finishes_the_run(
        self, session, offboarding, clock
    ):
        organization = _organization(session)
        employee = _user(session)
        person = _person(session, organization, user=employee)
        entity = _entity(session)
        product = _product(session)
        _line(
            session,
            entity=entity,
            product=product,
            holder=employee,
            payer_organization=organization,
        )
        offboarding.offboard(session, organization.id, person.id)
        run = offboarding.history(session, organization.id)[0]
        pending = [
            action
            for action in offboarding.actions(session, run)
            if action.state is OffboardingActionState.PENDING_CARRIER
        ][0]

        offboarding.confirm_action(session, pending, detail="carrier suspended it")

        assert run.state is OffboardingState.COMPLETED

    def test_an_already_suspended_line_is_not_asked_about_again(
        self, session, offboarding
    ):
        organization = _organization(session)
        employee = _user(session)
        person = _person(session, organization, user=employee)
        entity = _entity(session)
        product = _product(session)
        _line(
            session,
            entity=entity,
            product=product,
            holder=employee,
            payer_organization=organization,
            activation=ActivationState.SUSPENDED,
        )

        summary = offboarding.offboard(session, organization.id, person.id)

        assert summary.pending_carrier == 0
        assert summary.state is OffboardingState.COMPLETED


class TestOffboardingScopeAndReplay:
    def test_offboarding_twice_returns_the_same_run(self, session, offboarding):
        organization = _organization(session)
        person = _person(session, organization)

        first = offboarding.offboard(session, organization.id, person.id)
        second = offboarding.offboard(session, organization.id, person.id)

        assert first.offboarding_id == second.offboarding_id

    def test_another_organizations_person_cannot_be_offboarded(
        self, session, offboarding
    ):
        mine = _organization(session)
        theirs = _organization(session)
        person = _person(session, theirs)

        with pytest.raises(OffboardingError) as excinfo:
            offboarding.offboard(session, mine.id, person.id)
        assert excinfo.value.code == "person_not_found"

    def test_every_kind_is_recorded_even_when_there_was_nothing_to_do(
        self, session, offboarding
    ):
        """"Was their line suspended?" should answer "they had none"."""
        organization = _organization(session)
        person = _person(session, organization)

        offboarding.offboard(session, organization.id, person.id)
        run = offboarding.history(session, organization.id)[0]
        kinds = {action.kind for action in offboarding.actions(session, run)}

        assert OffboardingActionKind.SUSPEND_LINE in kinds
        assert OffboardingActionKind.REVOKE_MEMBERSHIP in kinds


class TestFundingIsThreeDifferentThings:
    def test_credit_allowance_and_pooling_are_reported_apart(
        self, session, reporting, ledger, clock
    ):
        organization = _organization(session)
        _fund(session, ledger, organization, "10000.00")

        summary = reporting.funding(
            session, organization.id, "NGN", since=NOW - timedelta(days=30)
        )

        assert summary.balance == Decimal("10000.00")
        assert summary.available == Decimal("10000.00")
        assert summary.held == Decimal("0.00")
        # The claim the assignment cares about: no supplier pooling exists.
        assert summary.pooling is False
        assert "pooling" in summary.pooling_note

    def test_a_hold_shows_as_held_not_spent(
        self, session, reporting, ledger, clock
    ):
        organization = _organization(session)
        credit = _fund(session, ledger, organization, "10000.00")
        ledger.reserve(session, credit, Decimal("2500.00"), "hold:test")

        summary = reporting.funding(
            session, organization.id, "NGN", since=NOW - timedelta(days=30)
        )

        assert summary.balance == Decimal("10000.00")
        assert summary.held == Decimal("2500.00")
        assert summary.available == Decimal("7500.00")

    def test_no_recorded_cap_is_undecided_not_unlimited(
        self, session, reporting, ledger
    ):
        organization = _organization(session)
        _fund(session, ledger, organization, "10000.00")

        summary = reporting.funding(
            session, organization.id, "NGN", since=NOW - timedelta(days=30)
        )

        assert summary.period_cap is None
        assert summary.headroom is None

    def test_a_recorded_cap_produces_headroom(
        self, session, reporting, ledger, clock
    ):
        organization = _organization(session)
        _fund(session, ledger, organization, "10000.00")
        session.add(
            OrganizationSpendingPolicy(
                organization_id=organization.id,
                currency="NGN",
                period_cap_amount=Decimal("5000.00"),
                enforced=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()

        summary = reporting.funding(
            session, organization.id, "NGN", since=NOW - timedelta(days=30)
        )

        assert summary.period_cap == Decimal("5000.00")
        assert summary.headroom == Decimal("5000.00")


class TestDepartmentalReporting:
    def _team_world(self, session, ledger):
        organization = _organization(session)
        entity = _entity(session)
        product = _product(session)
        centre = OrganizationCostCentre(
            organization_id=organization.id,
            code="CC-1",
            name="Operations",
            created_at=NOW,
        )
        session.add(centre)
        session.flush()
        team = OrganizationTeam(
            organization_id=organization.id,
            name="Field",
            cost_centre_id=centre.id,
            created_at=NOW,
        )
        session.add(team)
        session.flush()
        employee = _user(session)
        person = _person(session, organization, user=employee, team=team, centre=centre)
        _order, _item, entitlement, line_row = _line(
            session,
            entity=entity,
            product=product,
            holder=employee,
            payer_organization=organization,
            amount="1000.00",
        )
        return organization, team, person, entitlement, line_row

    def test_purchases_are_grouped_by_team(self, session, reporting, ledger):
        organization, team, _person, _ent, _line_row = self._team_world(session, ledger)

        report = reporting.departmental(
            session,
            organization.id,
            "NGN",
            period_from=NOW - timedelta(days=1),
            period_to=NOW + timedelta(days=1),
            by="team",
        )

        assert len(report.totals) == 1
        assert report.totals[0].label == "Field"
        assert report.totals[0].purchased_amount == Decimal("1000.00")
        assert report.totals[0].lines == 1

    def test_a_report_with_no_usage_says_it_has_observed_nothing(
        self, session, reporting, ledger
    ):
        """`None` is not zero. A stalled poller and an unused line look alike
        on a screen that renders both as 0.00."""
        organization, _team, _person, _ent, _line_row = (
            self._team_world(session, ledger)
        )

        report = reporting.departmental(
            session,
            organization.id,
            "NGN",
            period_from=NOW - timedelta(days=1),
            period_to=NOW + timedelta(days=1),
        )

        assert report.observed_through is None
        assert report.usage_total == Decimal("0.00")

    def test_usage_is_reported_beside_purchases_and_carries_its_freshness(
        self, session, reporting, ledger
    ):
        organization, _team, _person, entitlement, line_row = self._team_world(
            session, ledger
        )
        observed_to = NOW - timedelta(hours=2)
        session.add(
            UsageRecord(
                channel=AdapterChannel.CARRIER,
                # A carrier-channel record must name its line: the schema says
                # so, and a reading with no line is a reading about nothing.
                carrier_line_id=line_row.id,
                entitlement_id=entitlement.id,
                provider="telnyx",
                kind=UsageKind.DATA,
                source=UsageSource.EVENT,
                state=UsageState.FINAL,
                natural_key=f"usage-{uuid4()}",
                quantity=1024,
                occurred_from=observed_to - timedelta(hours=1),
                occurred_to=observed_to,
                received_at=NOW,
                charged_currency="NGN",
                charged_amount=Decimal("120.00"),
                created_at=NOW,
            )
        )
        session.flush()

        report = reporting.departmental(
            session,
            organization.id,
            "NGN",
            period_from=NOW - timedelta(days=1),
            period_to=NOW + timedelta(days=1),
        )

        assert report.totals[0].usage_amount == Decimal("120.00")
        assert report.totals[0].purchased_amount == Decimal("1000.00")
        assert report.observed_through == observed_to

    def test_evidence_only_usage_is_not_counted(
        self, session, reporting, ledger
    ):
        """Chunk 16 keeps non-authoritative readings as evidence. Counting them
        bills the same bytes twice in a report."""
        organization, _team, _person, entitlement, line_row = self._team_world(
            session, ledger
        )
        session.add(
            UsageRecord(
                channel=AdapterChannel.CARRIER,
                # A carrier-channel record must name its line: the schema says
                # so, and a reading with no line is a reading about nothing.
                carrier_line_id=line_row.id,
                entitlement_id=entitlement.id,
                provider="telnyx",
                kind=UsageKind.DATA,
                source=UsageSource.COUNTER,
                state=UsageState.EVIDENCE,
                natural_key=f"usage-{uuid4()}",
                quantity=2048,
                occurred_from=NOW - timedelta(hours=3),
                occurred_to=NOW - timedelta(hours=2),
                received_at=NOW,
                charged_currency="NGN",
                charged_amount=Decimal("500.00"),
                created_at=NOW,
            )
        )
        session.flush()

        report = reporting.departmental(
            session,
            organization.id,
            "NGN",
            period_from=NOW - timedelta(days=1),
            period_to=NOW + timedelta(days=1),
        )

        assert report.usage_total == Decimal("0.00")

    def test_another_organizations_spend_is_not_in_the_report(
        self, session, reporting, ledger
    ):
        mine, _team, _person, _ent, _l1 = self._team_world(session, ledger)
        theirs, _t2, _p2, _e2, _l2 = self._team_world(session, ledger)

        report = reporting.departmental(
            session,
            mine.id,
            "NGN",
            period_from=NOW - timedelta(days=1),
            period_to=NOW + timedelta(days=1),
        )

        assert report.purchased_total == Decimal("1000.00")

    def test_grouping_by_cost_centre_uses_its_code(
        self, session, reporting, ledger
    ):
        organization, _team, _person, _ent, _line_row = (
            self._team_world(session, ledger)
        )

        report = reporting.departmental(
            session,
            organization.id,
            "NGN",
            period_from=NOW - timedelta(days=1),
            period_to=NOW + timedelta(days=1),
            by="cost_centre",
        )

        assert report.totals[0].label.startswith("CC-1")

    def test_report_purchases_reconcile_with_the_orders_behind_them(
        self, session, reporting, ledger
    ):
        """The acceptance criterion: totals reconcile with what is in the books."""
        organization, _team, _person, _ent, _line_row = (
            self._team_world(session, ledger)
        )

        report = reporting.departmental(
            session,
            organization.id,
            "NGN",
            period_from=NOW - timedelta(days=1),
            period_to=NOW + timedelta(days=1),
        )
        from sqlalchemy import func

        booked = session.exec(
            select(func.coalesce(func.sum(OrderItem.unit_amount), 0))
            .join(Order, OrderItem.order_id == Order.id)
            .where(Order.payer_organization_id == organization.id)
        ).first()

        assert report.purchased_total == Decimal(booked)
