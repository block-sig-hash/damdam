"""Call authorization on real PostgreSQL — US-45, chunk V02.

Authorization, idempotency, money and concurrency are all strict-TDD categories
in `AGENTS.md`, and every one of them applies here at once. None of it is
testable on SQLite: the single-use grant is a conditional UPDATE, the duplicate
leg is a partial unique index, the shared-funds race is `SELECT … FOR UPDATE`
inside the ledger, and a passing SQLite run would prove that none of those
existed.

The test names map to V01's negative matrix (`docs/implementation/voice/
GO-NO-GO.md`), which is the acceptance surface for AC-45.1 to AC-45.4.
"""

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
from app.calling.models import AttemptState, CallAttempt, CallingClientCredential
from app.calling.service import CallAuthorizationError, CallAuthorizationService
from app.catalog.market import PublicationStatus
from app.catalog.models import Product, ProductKind
from app.catalog.tariffs import DestinationKind, OriginKind, Tariff, TariffRate
from app.ledger.models import AccountKind, Direction, OwnerKind, Reservation
from app.ledger.service import LedgerService, Posting
from app.organizations.models import (
    MembershipStatus,
    OrganizationMember,
    OrganizationRole,
)

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="the grant's guarantees are database guarantees",
)

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
TABLES = (
    "call_events, call_operations, call_legs, call_attempts, "
    "calling_client_credentials, journal_lines, journal_entries, "
    "ledger_reservations, ledger_accounts, tariff_rates, tariffs, products, "
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
def service(ledger, clock):
    return CallAuthorizationService(
        ledger, clock=clock, supported_countries=frozenset({"NG"}), route_enabled=True
    )


def _user(session: Session, label: str = "caller") -> User:
    user = User(
        phone_number=f"+23480{uuid4().int % 10**8:08d}",
        first_name=label,
        platform=Platform.ANDROID,
    )
    session.add(user)
    session.flush()
    return user


def _tariff(session: Session, clock: Clock, currency: str = "NGN") -> Tariff:
    """A published internet-voice tariff with one Nigerian mobile rate.

    Rates are invented for the test and are not a market claim: B2 is open and
    no Nigeria rate deck has been obtained. `evidence_reference` says so.
    """
    product = Product(
        sku=f"voice-{uuid4().hex[:8]}", name="Internet calling", kind=ProductKind.VOICE
    )
    session.add(product)
    session.flush()
    tariff = Tariff(
        product_id=product.id,
        currency=currency,
        version=1,
        status=PublicationStatus.PUBLISHED,
        effective_from=clock() - timedelta(days=1),
        evidence_reference="test fixture — not a rate claim (B2 open)",
        verified_at=clock() - timedelta(days=1),
    )
    session.add(tariff)
    session.flush()
    session.add(
        TariffRate(
            tariff_id=tariff.id,
            origin_kind=OriginKind.INTERNET,
            origin_country=None,
            destination_country="NG",
            destination_kind=DestinationKind.MOBILE,
            per_minute_amount=Decimal("30.0000000000"),
            setup_amount=Decimal("0.000000"),
            minimum_seconds=0,
            increment_seconds=60,
        )
    )
    session.flush()
    return tariff


def _fund(session: Session, ledger: LedgerService, user: User, amount="10000.00"):
    credit = ledger.account(
        session,
        "NGN",
        AccountKind.SERVICE_CREDIT,
        OwnerKind.USER,
        owner_user_id=user.id,
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


def _authorize(service, session, user, **overrides):
    destination = overrides.pop("destination", "+2348031234567")
    kwargs = dict(
        idempotency_key=f"key-{uuid4()}",
        currency="NGN",
        identity_e164="+2347000000001",
        requested_seconds=600,
    )
    kwargs.update(overrides)
    return service.authorize(session, user, destination, **kwargs)


class TestAuthorizationBindsTheCall:
    def test_the_grant_records_every_fact_the_call_is_judged_against(
        self, session, service, ledger, clock
    ):
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)

        attempt = _authorize(service, session, user)

        assert attempt.e164_destination == "+2348031234567"
        assert attempt.destination_country == "NG"
        assert attempt.destination_kind is DestinationKind.MOBILE
        assert attempt.origin_kind is OriginKind.INTERNET
        assert attempt.currency == "NGN"
        assert attempt.payer_kind.value == "user"
        assert attempt.organization_id is None
        assert attempt.state is AttemptState.AUTHORIZED
        assert attempt.grant_consumed_at is None
        # The rate is pinned, not referenced. A later tariff version cannot
        # reprice a call that was already authorized.
        assert attempt.tariff_version == 1
        assert attempt.rate_per_minute_amount == Decimal("30.0000000000")
        assert attempt.rate_increment_seconds == 60

    def test_money_is_held_before_the_grant_exists(
        self, session, service, ledger, clock
    ):
        user = _user(session)
        credit = _fund(session, ledger, user, "10000.00")
        _tariff(session, clock)

        attempt = _authorize(service, session, user, requested_seconds=600)

        # 600s at NGN 30/min = NGN 300.
        assert attempt.max_charge_amount == Decimal("300.00")
        reservation = session.get(Reservation, attempt.reservation_id)
        assert reservation is not None
        assert reservation.amount == Decimal("300.00")
        assert ledger.available(session, credit) == Decimal("9700.00")

    def test_the_expiry_is_short_and_in_the_future(
        self, session, service, ledger, clock
    ):
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)
        attempt = _authorize(service, session, user)
        assert attempt.expires_at > attempt.created_at
        assert (attempt.expires_at - attempt.created_at) <= timedelta(minutes=5)


class TestN1IdempotentAuthorize:
    def test_replaying_the_key_returns_one_attempt_and_one_reservation(
        self, session, service, ledger, clock
    ):
        user = _user(session)
        credit = _fund(session, ledger, user)
        _tariff(session, clock)
        key = "same-key"

        first = _authorize(service, session, user, idempotency_key=key)
        second = _authorize(service, session, user, idempotency_key=key)

        assert first.id == second.id
        assert first.reservation_id == second.reservation_id
        assert len(session.exec(select(CallAttempt)).all()) == 1
        # One hold, not two. Two holds would silently double the customer's
        # committed exposure for one call.
        assert ledger.available(session, credit) == Decimal("9700.00")

    def test_the_same_key_with_a_different_destination_is_refused(
        self, session, service, ledger, clock
    ):
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)
        _authorize(service, session, user, idempotency_key="k")

        with pytest.raises(CallAuthorizationError) as excinfo:
            _authorize(
                service,
                session,
                user,
                idempotency_key="k",
                destination="+2348039999999",
            )
        assert excinfo.value.code == "idempotency_conflict"

    def test_two_customers_may_use_the_same_key(self, session, service, ledger, clock):
        # Idempotency is scoped per user. A global key space would let one
        # customer's replay return another customer's call.
        first_user = _user(session, "first")
        second_user = _user(session, "second")
        _fund(session, ledger, first_user)
        _fund(session, ledger, second_user)
        _tariff(session, clock)

        first = _authorize(service, session, first_user, idempotency_key="shared")
        second = _authorize(service, session, second_user, idempotency_key="shared")

        assert first.id != second.id


class TestN4DestinationIsNeverTakenFromTheClientAgain:
    def test_the_stored_destination_is_the_normalized_one(
        self, session, service, ledger, clock
    ):
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)
        attempt = _authorize(
            service, session, user, destination=" +234 (803) 123-4567 "
        )
        assert attempt.e164_destination == "+2348031234567"


class TestN5ForbiddenDestinations:
    @pytest.mark.parametrize(
        "destination,code",
        [
            ("+234112", "destination_emergency_or_special"),
            ("+2347001234567", "destination_premium"),
            ("+15551234567", "destination_country_not_supported"),
            ("08031234567", "destination_not_e164"),
        ],
    )
    def test_refused_before_any_money_moves(
        self, session, service, ledger, clock, destination, code
    ):
        user = _user(session)
        credit = _fund(session, ledger, user)
        _tariff(session, clock)

        with pytest.raises(CallAuthorizationError) as excinfo:
            _authorize(service, session, user, destination=destination)

        assert excinfo.value.code == code
        # No attempt, and critically no hold: a refusal that reserved money
        # would let a client drain its own available balance by dialling
        # emergency numbers.
        assert session.exec(select(CallAttempt)).all() == []
        assert ledger.available(session, credit) == Decimal("10000.00")


class TestN3SingleUseGrant:
    def test_a_grant_is_consumed_exactly_once(self, session, service, ledger, clock):
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)
        attempt = _authorize(service, session, user)

        assert service.consume_grant(session, attempt.id) is True
        assert service.consume_grant(session, attempt.id) is False

        session.refresh(attempt)
        assert attempt.state is AttemptState.ACCEPTED
        assert attempt.grant_consumed_at is not None

    def test_an_expired_grant_cannot_be_consumed(
        self, session, service, ledger, clock
    ):
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)
        attempt = _authorize(service, session, user)

        clock.advance(minutes=10)

        assert service.consume_grant(session, attempt.id) is False
        session.refresh(attempt)
        assert attempt.grant_consumed_at is None

    def test_starting_an_expired_attempt_is_refused(
        self, session, service, ledger, clock
    ):
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)
        attempt = _authorize(service, session, user)
        clock.advance(minutes=10)

        with pytest.raises(CallAuthorizationError) as excinfo:
            service.start(session, user, attempt.id)
        assert excinfo.value.code == "attempt_expired"


class TestN2Ownership:
    def test_another_user_cannot_start_the_attempt(
        self, session, service, ledger, clock
    ):
        owner = _user(session, "owner")
        intruder = _user(session, "intruder")
        _fund(session, ledger, owner)
        _tariff(session, clock)
        attempt = _authorize(service, session, owner)

        with pytest.raises(CallAuthorizationError) as excinfo:
            service.start(session, intruder, attempt.id)
        # Not "forbidden": a distinct answer would confirm the id is real.
        assert excinfo.value.code == "attempt_not_found"

    def test_another_user_cannot_read_or_stop_the_attempt(
        self, session, service, ledger, clock
    ):
        owner = _user(session, "owner")
        intruder = _user(session, "intruder")
        _fund(session, ledger, owner)
        _tariff(session, clock)
        attempt = _authorize(service, session, owner)

        for call in (service.get, service.stop):
            with pytest.raises(CallAuthorizationError) as excinfo:
                call(session, intruder, attempt.id)
            assert excinfo.value.code == "attempt_not_found"

    def test_a_grant_bound_to_one_device_refuses_another(
        self, session, service, ledger, clock
    ):
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)
        credential = CallingClientCredential(
            user_id=user.id,
            device_id="phone-a",
            provider="telnyx",
            provider_credential_id=f"cred-{uuid4().hex}",
            created_at=clock(),
        )
        session.add(credential)
        session.flush()
        attempt = _authorize(service, session, user, client_credential_id=credential.id)

        with pytest.raises(CallAuthorizationError) as excinfo:
            service.start(session, user, attempt.id, device_id="phone-b")
        assert excinfo.value.code == "device_not_authorized"

    def test_authorizing_against_another_users_credential_is_refused(
        self, session, service, ledger, clock
    ):
        owner = _user(session, "owner")
        other = _user(session, "other")
        _fund(session, ledger, owner)
        _tariff(session, clock)
        credential = CallingClientCredential(
            user_id=other.id,
            device_id="their-phone",
            provider="telnyx",
            provider_credential_id=f"cred-{uuid4().hex}",
            created_at=clock(),
        )
        session.add(credential)
        session.flush()

        with pytest.raises(CallAuthorizationError) as excinfo:
            _authorize(service, session, owner, client_credential_id=credential.id)
        assert excinfo.value.code == "device_not_authorized"


class TestTenantBoundaries:
    def _organization(self, session, clock):
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

    def test_a_non_member_cannot_bill_an_organization(
        self, session, service, ledger, clock
    ):
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)
        organization = self._organization(session, clock)

        with pytest.raises(CallAuthorizationError) as excinfo:
            _authorize(service, session, user, organization_id=organization.id)
        assert excinfo.value.code == "not_a_member"

    def test_a_revoked_member_cannot_start_a_new_work_call(
        self, session, service, ledger, clock
    ):
        user = _user(session)
        organization = self._organization(session, clock)
        member = OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=OrganizationRole.MEMBER,
            status=MembershipStatus.REVOKED,
            revoked_at=clock(),
        )
        session.add(member)
        session.flush()
        _tariff(session, clock)

        with pytest.raises(CallAuthorizationError) as excinfo:
            _authorize(service, session, user, organization_id=organization.id)
        assert excinfo.value.code == "not_a_member"

    def test_personal_history_excludes_work_calls(
        self, session, service, ledger, clock
    ):
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)
        organization = self._organization(session, clock)
        session.add(
            OrganizationMember(
                organization_id=organization.id,
                user_id=user.id,
                role=OrganizationRole.MEMBER,
                status=MembershipStatus.ACTIVE,
            )
        )
        session.flush()
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
            f"org-funding:{uuid4()}",
            [
                Posting(clearing, Direction.DEBIT, Decimal("5000.00")),
                Posting(credit, Direction.CREDIT, Decimal("5000.00")),
            ],
        )
        session.flush()

        personal = _authorize(service, session, user)
        work = _authorize(service, session, user, organization_id=organization.id)

        personal_ids = {a.id for a in service.history(session, user)}
        work_ids = {
            a.id
            for a in service.history(session, user, organization_id=organization.id)
        }
        assert personal.id in personal_ids and work.id not in personal_ids
        assert work.id in work_ids and personal.id not in work_ids

    def test_work_calls_are_billed_to_the_organization(
        self, session, service, ledger, clock
    ):
        user = _user(session)
        _tariff(session, clock)
        organization = self._organization(session, clock)
        session.add(
            OrganizationMember(
                organization_id=organization.id,
                user_id=user.id,
                role=OrganizationRole.MEMBER,
                status=MembershipStatus.ACTIVE,
            )
        )
        session.flush()
        org_credit = ledger.account(
            session,
            "NGN",
            AccountKind.SERVICE_CREDIT,
            OwnerKind.ORGANIZATION,
            owner_organization_id=organization.id,
        )
        clearing = ledger.account(session, "NGN", AccountKind.SETTLEMENT_CLEARING)
        ledger.post(
            session,
            f"org-funding:{uuid4()}",
            [
                Posting(clearing, Direction.DEBIT, Decimal("1000.00")),
                Posting(org_credit, Direction.CREDIT, Decimal("1000.00")),
            ],
        )
        session.flush()
        personal_credit = _fund(session, ledger, user, "1000.00")

        attempt = _authorize(
            service,
            session,
            user,
            organization_id=organization.id,
            requested_seconds=60,
        )

        assert attempt.payer_kind.value == "organization"
        # The company's money moved and the member's did not. Deriving the payer
        # later would put this call on whichever account happened to be handy.
        assert ledger.available(session, org_credit) == Decimal("970.00")
        assert ledger.available(session, personal_credit) == Decimal("1000.00")


class TestFunding:
    def test_an_unfundable_call_is_refused_and_nothing_is_held(
        self, session, service, ledger, clock
    ):
        user = _user(session)
        credit = _fund(session, ledger, user, "10.00")
        _tariff(session, clock)

        with pytest.raises(CallAuthorizationError) as excinfo:
            _authorize(service, session, user, requested_seconds=600)
        assert excinfo.value.code == "insufficient_funds"
        assert ledger.available(session, credit) == Decimal("10.00")

    def test_preview_reserves_nothing(self, session, service, ledger, clock):
        user = _user(session)
        credit = _fund(session, ledger, user)
        _tariff(session, clock)

        preview = service.preview(
            session, user, "+2348031234567", currency="NGN", requested_seconds=600
        )

        assert preview.max_charge_amount == Decimal("300.00")
        assert preview.fundable is True
        assert ledger.available(session, credit) == Decimal("10000.00")
        assert session.exec(select(Reservation)).all() == []

    def test_a_call_with_no_published_internet_rate_is_refused(
        self, session, service, ledger, clock
    ):
        user = _user(session)
        _fund(session, ledger, user)
        # No tariff at all. "Unknown means unavailable" — the call is refused
        # rather than priced at zero or at a carrier rate.
        with pytest.raises(CallAuthorizationError) as excinfo:
            _authorize(service, session, user)
        assert excinfo.value.code == "rate_unavailable"

    def test_a_carrier_roaming_rate_never_prices_an_internet_call(
        self, session, service, ledger, clock
    ):
        user = _user(session)
        _fund(session, ledger, user)
        product = Product(
            sku=f"voice-{uuid4().hex[:8]}",
            name="Carrier voice",
            kind=ProductKind.VOICE,
        )
        session.add(product)
        session.flush()
        tariff = Tariff(
            product_id=product.id,
            currency="NGN",
            version=1,
            status=PublicationStatus.PUBLISHED,
            effective_from=clock() - timedelta(days=1),
            evidence_reference="test fixture",
            verified_at=clock() - timedelta(days=1),
        )
        session.add(tariff)
        session.flush()
        session.add(
            TariffRate(
                tariff_id=tariff.id,
                origin_kind=OriginKind.CARRIER_VISITED_NETWORK,
                origin_country=None,
                destination_country="NG",
                destination_kind=DestinationKind.MOBILE,
                per_minute_amount=Decimal("10.0000000000"),
                setup_amount=Decimal("0.000000"),
                minimum_seconds=0,
                increment_seconds=60,
            )
        )
        session.flush()

        with pytest.raises(CallAuthorizationError) as excinfo:
            _authorize(service, session, user)
        assert excinfo.value.code == "rate_unavailable"


class TestRouteGate:
    def test_start_refuses_while_the_route_is_disabled(
        self, session, ledger, clock
    ):
        disabled = CallAuthorizationService(
            ledger,
            clock=clock,
            supported_countries=frozenset({"NG"}),
            route_enabled=False,
        )
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)
        attempt = _authorize(disabled, session, user)

        with pytest.raises(CallAuthorizationError) as excinfo:
            disabled.start(session, user, attempt.id)
        assert excinfo.value.code == "calling_route_disabled"

    def test_stop_still_works_while_the_route_is_disabled(
        self, session, ledger, clock
    ):
        # Disabling new calling must not disable termination or financial
        # recovery. A deployment that switched the route off mid-call would
        # otherwise be unable to end the calls it had already started.
        disabled = CallAuthorizationService(
            ledger,
            clock=clock,
            supported_countries=frozenset({"NG"}),
            route_enabled=False,
        )
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)
        attempt = _authorize(disabled, session, user)

        stopped = disabled.stop(session, user, attempt.id, reason="user_hung_up")
        assert stopped.end_reason == "user_hung_up"

    def test_preview_reports_the_route_as_disabled(self, session, ledger, clock):
        disabled = CallAuthorizationService(
            ledger,
            clock=clock,
            supported_countries=frozenset({"NG"}),
            route_enabled=False,
        )
        user = _user(session)
        _fund(session, ledger, user)
        _tariff(session, clock)
        preview = disabled.preview(session, user, "+2348031234567", currency="NGN")
        assert preview.route_enabled is False


class TestConcurrency:
    """Two threads, one database, and the guarantees that only exist there."""

    def test_n16_two_calls_race_for_insufficient_funds(self, engine, clock):
        """Only one of two concurrent calls may hold the last of the money."""
        with Session(engine) as setup:
            setup.exec(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
            ledger = LedgerService(clock=clock)
            user = _user(setup)
            _fund(setup, ledger, user, "300.00")  # exactly one 600s call
            _tariff(setup, clock)
            setup.commit()
            user_id = user.id

        barrier = Barrier(2)
        results: list[object] = []

        def authorize(index: int) -> None:
            service = CallAuthorizationService(
                LedgerService(clock=clock),
                clock=clock,
                supported_countries=frozenset({"NG"}),
                route_enabled=True,
            )
            with Session(engine) as session:
                caller = session.get(User, user_id)
                barrier.wait(timeout=10)
                try:
                    attempt = service.authorize(
                        session,
                        caller,
                        "+2348031234567",
                        idempotency_key=f"race-{index}",
                        currency="NGN",
                        identity_e164="+2347000000001",
                        requested_seconds=600,
                    )
                    session.commit()
                    results.append(attempt.id)
                except CallAuthorizationError as exc:
                    session.rollback()
                    results.append(exc.code)

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(authorize, range(2)))

        assert sum(1 for r in results if isinstance(r, str)) == 1, results
        assert "insufficient_funds" in results, results

        with Session(engine) as check:
            held = check.exec(select(Reservation)).all()
            assert len(held) == 1

    def test_same_key_concurrently_produces_one_attempt(self, engine, clock):
        """A double-tapped call button is one call, not two.

        The client retrying while the first request is still in flight is the
        ordinary case on a mobile network, and it is the case a check-then-insert
        gets wrong.
        """
        with Session(engine) as setup:
            setup.exec(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
            ledger = LedgerService(clock=clock)
            user = _user(setup)
            _fund(setup, ledger, user, "10000.00")
            _tariff(setup, clock)
            setup.commit()
            user_id = user.id

        barrier = Barrier(2)
        outcomes: list[str] = []

        def authorize(_index: int) -> None:
            service = CallAuthorizationService(
                LedgerService(clock=clock),
                clock=clock,
                supported_countries=frozenset({"NG"}),
                route_enabled=True,
            )
            with Session(engine) as session:
                caller = session.get(User, user_id)
                barrier.wait(timeout=10)
                try:
                    service.authorize(
                        session,
                        caller,
                        "+2348031234567",
                        idempotency_key="double-tap",
                        currency="NGN",
                        identity_e164="+2347000000001",
                        requested_seconds=600,
                    )
                    session.commit()
                    outcomes.append("ok")
                except Exception as exc:  # noqa: BLE001 - the class is the result
                    session.rollback()
                    outcomes.append(type(exc).__name__)

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(authorize, range(2)))

        with Session(engine) as check:
            attempts = check.exec(select(CallAttempt)).all()
            reservations = check.exec(select(Reservation)).all()
        assert len(attempts) == 1, outcomes
        assert len(reservations) == 1, outcomes

    def test_two_workers_cannot_consume_one_grant(self, engine, clock):
        """The single-use latch, under the race it exists for.

        Two webhook deliveries for the same parked call, landing on two workers.
        A read-then-write would let both proceed to dial.
        """
        with Session(engine) as setup:
            setup.exec(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
            ledger = LedgerService(clock=clock)
            service = CallAuthorizationService(
                ledger,
                clock=clock,
                supported_countries=frozenset({"NG"}),
                route_enabled=True,
            )
            user = _user(setup)
            _fund(setup, ledger, user, "10000.00")
            _tariff(setup, clock)
            attempt = service.authorize(
                setup,
                user,
                "+2348031234567",
                idempotency_key="consume-race",
                currency="NGN",
                identity_e164="+2347000000001",
                requested_seconds=600,
            )
            setup.commit()
            attempt_id = attempt.id

        barrier = Barrier(2)
        wins: list[bool] = []

        def consume(_index: int) -> None:
            service = CallAuthorizationService(
                LedgerService(clock=clock),
                clock=clock,
                supported_countries=frozenset({"NG"}),
                route_enabled=True,
            )
            with Session(engine) as session:
                barrier.wait(timeout=10)
                won = service.consume_grant(session, attempt_id)
                session.commit()
                wins.append(won)

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(consume, range(2)))

        assert sorted(wins) == [False, True], wins
