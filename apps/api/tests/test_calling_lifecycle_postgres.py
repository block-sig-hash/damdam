"""Call lifecycle on real PostgreSQL — the event inbox and durable operations.

Covers V01's negative matrix rows that are about the *provider* rather than the
customer: replayed events (N8), unsigned and stale ones (N9), reordering and late
delivery (N10), a lost originate response (N11), duplicate commands past the
provider's 60-second window (N12), quarantine on identity mismatch (N6), and a
`client_state` that names somebody else's attempt (N7).

The fake adapter here is a fake on purpose and its limits are the point: it
proves our state machine, our inbox and our indexes behave. It proves nothing
about Telnyx, and `AGENTS.md` is explicit that a mock passing itself is not
evidence of external compatibility. The Telnyx contract probe covers that
separately, and B1–B5 remain open.
"""

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app import model_registry  # noqa: F401
from app.auth.models import Organization, OrganizationType, Platform, User
from app.calling.contract import (
    CallingCapabilities,
    CallingCapability,
    CallingError,
    CallOutcomeUnknown,
    LegRole,
    LegState,
    ProviderEvent,
    ProviderLegHandle,
)
from app.calling.lifecycle import CallLifecycleService
from app.calling.models import (
    AttemptState,
    CallEvent,
    CallingClientCredential,
    CallLeg,
    CallOperation,
    EventDisposition,
    OperationKind,
    OperationOutcome,
    PayerKind,
)
from app.calling.service import CallAuthorizationService
from app.catalog.market import PublicationStatus
from app.catalog.models import Product, ProductKind
from app.catalog.tariffs import DestinationKind, OriginKind, Tariff, TariffRate
from app.ledger.models import (
    AccountKind,
    Direction,
    OwnerKind,
    Reservation,
    ReservationState,
)
from app.ledger.service import LedgerService, Posting
from app.organizations.models import (
    MembershipStatus,
    OrganizationMember,
    OrganizationRole,
)

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="the inbox and duplicate-leg guarantees are database guarantees",
)

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
TABLES = (
    "call_events, call_operations, call_legs, call_attempts, "
    "calling_client_credentials, journal_lines, journal_entries, "
    "ledger_reservations, ledger_accounts, tariff_rates, tariffs, products, users"
)


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: float) -> None:
        self.value += timedelta(**kwargs)


class FakeAdapter:
    """A calling provider that does what the test tells it to.

    `next_outcome` drives the three answers a real provider gives: a handle, a
    definite refusal, or nothing at all because the response was lost. The third
    is the one worth having a fake for — it is almost impossible to provoke on
    demand against a real API, and it is the failure that causes duplicate calls.
    """

    name = "fake"

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.created: list[dict] = []
        self.bridged: list[tuple[str, str]] = []
        self.hangups: list[str] = []
        self.next_outcome: str = "ok"
        self.reconcile_answer: ProviderLegHandle | None = None
        self.parsed: ProviderEvent | None = None

    def capabilities(self) -> CallingCapabilities:
        return CallingCapabilities(
            name=self.name,
            supported=frozenset(
                {
                    CallingCapability.PARKED_ORIGINATION,
                    CallingCapability.BRIDGE,
                    CallingCapability.HANGUP,
                    CallingCapability.LEG_TIME_LIMIT,
                }
            ),
            evidence_reference="test fake — not provider evidence",
        )

    def issue_client_session(
        self,
        *,
        operation_reference,
        device_label,
        provider_credential_id=None,
        sip_identity=None,
        credential_expires_at=None,
    ):
        raise NotImplementedError

    def revoke_client_credential(self, provider_credential_id: str) -> None:
        return None

    def create_destination_leg(
        self,
        *,
        operation_reference,
        destination,
        identity,
        time_limit_seconds,
        correlation,
    ):
        self.created.append(
            {
                "operation": operation_reference,
                "destination": destination,
                "identity": identity,
                "time_limit_seconds": time_limit_seconds,
                "correlation": correlation,
            }
        )
        if self.next_outcome == "unknown":
            raise CallOutcomeUnknown("response lost", operation_reference)
        if self.next_outcome == "rejected":
            raise CallingError("provider_rejected", "destination unreachable")
        return ProviderLegHandle(
            control_id=f"dest-{len(self.created)}",
            leg_id=f"dest-{len(self.created)}-leg",
            session_id="session-1",
        )

    def reconcile_operation(self, operation_reference):
        return self.reconcile_answer

    def bridge(self, *, operation_reference, first, second):
        self.bridged.append((first, second))

    def hangup(self, *, operation_reference, control_id):
        self.hangups.append(control_id)

    def parse_event(self, body, headers):
        if self.parsed is None:
            raise CallingError("invalid_webhook_signature")
        return self.parsed


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
def adapter(clock):
    return FakeAdapter(clock)


@pytest.fixture
def authorization(clock):
    return CallAuthorizationService(
        LedgerService(clock=clock),
        clock=clock,
        supported_countries=frozenset({"NG"}),
        route_enabled=True,
    )


@pytest.fixture
def lifecycle(adapter, authorization, clock):
    return CallLifecycleService(adapter, authorization, clock=clock)


_AUTO_CREDENTIAL = object()


def _attempt(session, authorization, clock, *, credential=_AUTO_CREDENTIAL):
    user = User(
        phone_number=f"+23480{uuid4().int % 10**8:08d}",
        first_name="caller",
        platform=Platform.ANDROID,
    )
    session.add(user)
    session.flush()
    if credential is _AUTO_CREDENTIAL:
        credential = CallingClientCredential(
            user_id=user.id,
            device_id=f"phone-{uuid4().hex[:8]}",
            provider="fake",
            provider_credential_id="cred-1",
            provider_connection_id="conn-1",
            sip_identity="sip-1",
            expires_at=clock() + timedelta(hours=1),
            created_at=clock(),
        )
        session.add(credential)
        session.flush()
    ledger = authorization.ledger
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
            Posting(clearing, Direction.DEBIT, Decimal("10000.00")),
            Posting(credit, Direction.CREDIT, Decimal("10000.00")),
        ],
    )
    product = Product(
        sku=f"voice-{uuid4().hex[:8]}", name="Internet calling", kind=ProductKind.VOICE
    )
    session.add(product)
    session.flush()
    tariff = Tariff(
        product_id=product.id,
        currency="NGN",
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
    attempt = authorization.authorize(
        session,
        user,
        "+2348031234567",
        idempotency_key=f"key-{uuid4()}",
        currency="NGN",
        identity_e164="+2347000000001",
        requested_seconds=600,
        client_credential_id=None if credential is None else credential.id,
    )
    return user, attempt


def _event(
    attempt,
    event_type: str,
    *,
    control_id: str = "client-1",
    event_id: str | None = None,
    occurred_at: datetime | None = None,
    credential_id: str | None = "cred-1",
    claimed_destination: str | None = None,
    hangup_cause: str | None = None,
    client_state: dict | None = None,
) -> ProviderEvent:
    return ProviderEvent(
        event_id=event_id or f"evt-{uuid4()}",
        event_type=event_type,
        occurred_at=occurred_at or NOW,
        leg=ProviderLegHandle(
            control_id=control_id,
            leg_id=f"{control_id}-leg",
            session_id="session-1",
            connection_id="conn-1",
            credential_id=credential_id,
        ),
        claimed_destination=claimed_destination or attempt.e164_destination,
        client_state=(
            client_state
            if client_state is not None
            else {"attempt_id": str(attempt.id)}
        ),
        hangup_cause=hangup_cause,
        raw={"data": {"event_type": event_type}},
    )


class TestN8ReplayInsideTheToleranceWindow:
    def test_the_same_signed_event_is_applied_once(
        self, session, lifecycle, adapter, authorization, clock
    ):
        _user, attempt = _attempt(session, authorization, clock)
        event = _event(attempt, "call.initiated", event_id="evt-fixed")

        adapter.parsed = event
        first = lifecycle.ingest(session, b"{}", {})
        second = lifecycle.ingest(session, b"{}", {})

        assert first.disposition is EventDisposition.APPLIED
        # A valid signature and a fresh timestamp both pass on the replay. The
        # unique provider event id is the only thing that says "already done".
        assert second.disposition is EventDisposition.DUPLICATE
        assert len(session.exec(select(CallEvent)).all()) == 1
        assert {leg.role for leg in session.exec(select(CallLeg)).all()} == {
            LegRole.CLIENT,
            LegRole.DESTINATION,
        }
        assert len(adapter.created) == 1


class TestN9RejectedBeforePersistence:
    def test_an_unverifiable_event_stores_nothing(self, session, lifecycle, adapter):
        adapter.parsed = None  # the adapter raises on signature failure

        with pytest.raises(CallingError):
            lifecycle.ingest(session, b"{}", {})

        # No row: an endpoint that recorded every unauthenticated POST is a free
        # write amplifier for anybody who finds the URL.
        assert session.exec(select(CallEvent)).all() == []


class TestN7ClientStateIsNotAuthority:
    def test_an_event_naming_no_attempt_is_stored_unmatched(
        self, session, lifecycle, adapter, authorization, clock
    ):
        _user, attempt = _attempt(session, authorization, clock)
        adapter.parsed = _event(attempt, "call.initiated", client_state={})

        record = lifecycle.ingest(session, b"{}", {})

        assert record.disposition is EventDisposition.UNMATCHED
        assert record.attempt_id is None
        assert session.exec(select(CallLeg)).all() == []

    def test_malformed_client_state_does_not_authorize(
        self, session, lifecycle, adapter, authorization, clock
    ):
        _user, attempt = _attempt(session, authorization, clock)
        adapter.parsed = _event(
            attempt, "call.initiated", client_state={"attempt_id": "not-a-uuid"}
        )

        record = lifecycle.ingest(session, b"{}", {})
        assert record.disposition is EventDisposition.UNMATCHED


class TestN6QuarantineOnIdentityMismatch:
    def test_a_foreign_credential_quarantines_rather_than_dials(
        self, session, lifecycle, adapter, authorization, clock
    ):
        credential = CallingClientCredential(
            user_id=uuid4(),
            device_id="phone",
            provider="fake",
            provider_credential_id="cred-ours",
            created_at=clock(),
        )
        user, attempt = _attempt(session, authorization, clock)
        credential.user_id = user.id
        session.add(credential)
        session.flush()
        attempt.client_credential_id = credential.id
        session.add(attempt)
        session.flush()

        adapter.parsed = _event(
            attempt, "call.initiated", credential_id="cred-somebody-elses"
        )
        record = lifecycle.ingest(session, b"{}", {})

        assert record.disposition is EventDisposition.QUARANTINED
        assert "not the one the grant was bound to" in (record.disposition_reason or "")
        # Stored for an operator, and emphatically not acted on.
        assert session.exec(select(CallLeg)).all() == []
        assert adapter.created == []


class TestN10LateAndReorderedEvents:
    def test_an_answer_arriving_after_a_hangup_does_not_resurrect_the_leg(
        self, session, lifecycle, adapter, authorization, clock
    ):
        _user, attempt = _attempt(session, authorization, clock)
        adapter.parsed = _event(attempt, "call.initiated")
        lifecycle.ingest(session, b"{}", {})

        adapter.parsed = _event(
            attempt,
            "call.hangup",
            occurred_at=NOW + timedelta(seconds=30),
            hangup_cause="normal_clearing",
        )
        lifecycle.ingest(session, b"{}", {})
        # The straggler: an answer the provider emitted earlier and delivered
        # later.
        adapter.parsed = _event(
            attempt, "call.answered", occurred_at=NOW + timedelta(seconds=10)
        )
        late = lifecycle.ingest(session, b"{}", {})

        assert late.disposition is EventDisposition.SUPERSEDED
        leg = session.exec(
            select(CallLeg).where(CallLeg.role == LegRole.CLIENT)
        ).one()
        assert leg.state is LegState.ENDED
        assert leg.answered_at is None
        assert adapter.hangups == ["dest-1"]
        # And no negative duration, which is what the constraint exists for.
        assert leg.ended_at is not None

    def test_states_converge_forward_through_an_ordinary_call(
        self, session, lifecycle, adapter, authorization, clock
    ):
        _user, attempt = _attempt(session, authorization, clock)
        for kind, offset in (
            ("call.initiated", 0),
            ("call.ringing", 2),
            ("call.answered", 5),
        ):
            adapter.parsed = _event(
                attempt, kind, occurred_at=NOW + timedelta(seconds=offset)
            )
            lifecycle.ingest(session, b"{}", {})

        session.refresh(attempt)
        assert attempt.state is AttemptState.ANSWERED
        assert attempt.answered_at is not None


class TestN11LostOriginateResponse:
    def test_an_unknown_outcome_creates_no_leg_and_releases_nothing(
        self, session, lifecycle, adapter, authorization, clock
    ):
        _user, attempt = _attempt(session, authorization, clock)
        operation = lifecycle.begin_operation(
            session, attempt, OperationKind.CREATE_DESTINATION_LEG
        )
        adapter.next_outcome = "unknown"

        leg = lifecycle.create_destination_leg(session, attempt, operation)

        assert leg is None
        session.refresh(operation)
        assert operation.outcome is OperationOutcome.OUTCOME_UNKNOWN
        session.refresh(attempt)
        assert attempt.state is AttemptState.UNKNOWN
        assert session.exec(select(CallLeg)).all() == []
        # The hold stays. A call that may be connected must stay funded —
        # releasing here is how an unknown liability becomes an unfunded one
        # (invariant 8).
        reservation = session.get(Reservation, attempt.reservation_id)
        assert reservation is not None
        assert reservation.state is ReservationState.HELD
        assert reservation.released_amount == Decimal("0")
        assert reservation.settled_amount == Decimal("0")

    def test_a_second_originate_is_refused_while_the_first_is_unknown(
        self, session, lifecycle, adapter, authorization, clock
    ):
        _user, attempt = _attempt(session, authorization, clock)
        first = lifecycle.begin_operation(
            session, attempt, OperationKind.CREATE_DESTINATION_LEG
        )
        adapter.next_outcome = "unknown"
        lifecycle.create_destination_leg(session, attempt, first)

        # A worker restarting and trying again gets the *same* operation back,
        # not a new one, so it reconciles instead of dialling.
        second = lifecycle.begin_operation(
            session, attempt, OperationKind.CREATE_DESTINATION_LEG
        )
        assert second.id == first.id

    def test_reconciliation_records_the_leg_the_provider_did_create(
        self, session, lifecycle, adapter, authorization, clock
    ):
        _user, attempt = _attempt(session, authorization, clock)
        operation = lifecycle.begin_operation(
            session, attempt, OperationKind.CREATE_DESTINATION_LEG
        )
        adapter.next_outcome = "unknown"
        lifecycle.create_destination_leg(session, attempt, operation)

        adapter.reconcile_answer = ProviderLegHandle(control_id="dest-recovered")
        settled = lifecycle.reconcile(session, operation)

        assert settled.outcome is OperationOutcome.ACCEPTED
        legs = session.exec(
            select(CallLeg).where(CallLeg.role == LegRole.DESTINATION)
        ).all()
        assert len(legs) == 1
        assert legs[0].provider_call_control_id == "dest-recovered"

    def test_reconciliation_replays_an_answer_that_overtook_the_response(
        self, session, lifecycle, adapter, authorization, clock
    ):
        _user, attempt = _attempt(session, authorization, clock)
        adapter.next_outcome = "unknown"
        adapter.parsed = _event(attempt, "call.initiated")
        lifecycle.ingest(session, b"{}", {})

        operation = session.exec(
            select(CallOperation).where(
                CallOperation.kind == OperationKind.CREATE_DESTINATION_LEG
            )
        ).one()

        adapter.parsed = _event(
            attempt,
            "call.answered",
            control_id="dest-recovered",
            client_state={
                "attempt_id": str(attempt.id),
                "operation_id": str(operation.id),
            },
        )
        early = lifecycle.ingest(session, b"{}", {})
        assert early.disposition is EventDisposition.UNMATCHED

        adapter.reconcile_answer = ProviderLegHandle(
            control_id="dest-recovered",
            leg_id="dest-recovered-leg",
            session_id="session-1",
        )
        lifecycle.reconcile(session, operation)

        session.refresh(early)
        assert early.disposition is EventDisposition.APPLIED
        assert adapter.bridged == [("client-1", "dest-recovered")]

    def test_an_unanswerable_reconciliation_is_held_for_a_human(
        self, session, lifecycle, adapter, authorization, clock
    ):
        _user, attempt = _attempt(session, authorization, clock)
        operation = lifecycle.begin_operation(
            session, attempt, OperationKind.CREATE_DESTINATION_LEG
        )
        adapter.next_outcome = "unknown"
        lifecycle.create_destination_leg(session, attempt, operation)

        adapter.reconcile_answer = None
        settled = lifecycle.reconcile(session, operation)

        # Never a blind retry. A human decides, because the alternative is a
        # second PSTN leg to a destination that may already be connected.
        assert settled.outcome is OperationOutcome.HELD_FOR_REVIEW
        assert adapter.created == [adapter.created[0]]


class TestDuplicateDestinationLeg:
    def test_the_database_refuses_a_second_live_destination_leg(
        self, session, lifecycle, adapter, authorization, clock
    ):
        _user, attempt = _attempt(session, authorization, clock)
        operation = lifecycle.begin_operation(
            session, attempt, OperationKind.CREATE_DESTINATION_LEG
        )
        first = lifecycle.create_destination_leg(session, attempt, operation)
        assert first is not None

        # Force a second insert past the service-level guard, the way a confused
        # worker or a reconciliation race would.
        duplicate = CallLeg(
            attempt_id=attempt.id,
            role=LegRole.DESTINATION,
            provider="fake",
            provider_call_control_id="dest-other",
            state=LegState.CREATED,
            created_at=clock(),
        )
        session.add(duplicate)
        # The partial unique index, not a service-level check, is what refuses
        # this. A second live destination leg is a second billable PSTN call.
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    def test_the_destination_dialled_is_the_authorized_one(
        self, session, lifecycle, adapter, authorization, clock
    ):
        _user, attempt = _attempt(session, authorization, clock)
        operation = lifecycle.begin_operation(
            session, attempt, OperationKind.CREATE_DESTINATION_LEG
        )
        lifecycle.create_destination_leg(session, attempt, operation)

        assert adapter.created[0]["destination"] == "+2348031234567"
        assert adapter.created[0]["identity"] == "+2347000000001"
        # The provider bound comes from the reservation, so the only limit that
        # survives this process dying matches the money that was actually held.
        assert adapter.created[0]["time_limit_seconds"] == attempt.max_seconds


class TestN12DuplicateCommandsPastTheProviderWindow:
    def test_a_retry_an_hour_later_reuses_the_live_operation(
        self, session, lifecycle, adapter, authorization, clock
    ):
        _user, attempt = _attempt(session, authorization, clock)
        first = lifecycle.begin_operation(
            session, attempt, OperationKind.CREATE_DESTINATION_LEG
        )
        lifecycle.create_destination_leg(session, attempt, first)

        # Well past Telnyx's 60-second `command_id` window, where the provider
        # would no longer deduplicate for us.
        clock.advance(hours=1)
        again = lifecycle.begin_operation(
            session, attempt, OperationKind.CREATE_DESTINATION_LEG
        )

        assert again.id == first.id
        assert len(adapter.created) == 1
        assert len(session.exec(select(CallOperation)).all()) == 1


class TestBridgeOrdering:
    def test_a_bridge_before_the_destination_answers_is_refused(
        self, session, lifecycle, adapter, authorization, clock
    ):
        from app.calling.lifecycle import CallLifecycleError

        _user, attempt = _attempt(session, authorization, clock)
        adapter.parsed = _event(attempt, "call.initiated")
        lifecycle.ingest(session, b"{}", {})
        client_leg = session.exec(
            select(CallLeg).where(CallLeg.role == LegRole.CLIENT)
        ).one()
        operation = lifecycle.begin_operation(
            session, attempt, OperationKind.CREATE_DESTINATION_LEG
        )
        destination = lifecycle.create_destination_leg(session, attempt, operation)
        assert destination is not None

        with pytest.raises(CallLifecycleError) as excinfo:
            lifecycle.bridge(session, attempt, client_leg, destination)
        assert excinfo.value.code == "destination_not_answered"
        assert adapter.bridged == []


class TestN14DestinationNeverAnswers:
    def test_the_attempt_fails_rather_than_completing(
        self, session, lifecycle, adapter, authorization, clock
    ):
        _user, attempt = _attempt(session, authorization, clock)
        adapter.parsed = _event(attempt, "call.initiated")
        lifecycle.ingest(session, b"{}", {})
        adapter.parsed = _event(
            attempt,
            "call.hangup",
            occurred_at=NOW + timedelta(seconds=20),
            hangup_cause="no_answer",
        )
        lifecycle.ingest(session, b"{}", {})
        adapter.parsed = _event(
            attempt,
            "call.hangup",
            control_id="dest-1",
            occurred_at=NOW + timedelta(seconds=21),
            hangup_cause="no_answer",
        )
        lifecycle.ingest(session, b"{}", {})

        session.refresh(attempt)
        # `failed`, not `completed`: nothing answered, so there is no talk time
        # to charge, and the two must not look alike to settlement.
        assert attempt.state is AttemptState.FAILED
        assert attempt.answered_at is None
        assert attempt.end_reason == "no_answer"


class TestUnknownEventTypes:
    def test_an_unrecognised_event_is_stored_and_changes_nothing(
        self, session, lifecycle, adapter, authorization, clock
    ):
        _user, attempt = _attempt(session, authorization, clock)
        adapter.parsed = _event(attempt, "call.machine.detection.ended")

        record = lifecycle.ingest(session, b"{}", {})

        # Not an error. Treating an unknown provider event as a failure makes
        # every feature release on their side an outage on ours.
        assert record.disposition is EventDisposition.SUPERSEDED
        assert session.exec(select(CallLeg)).all() == []


def test_unknown_originate_is_not_dispatched_again(
    session, lifecycle, adapter, authorization, clock
):
    _, attempt = _attempt(session, authorization, clock)
    operation = lifecycle.begin_operation(
        session, attempt, OperationKind.CREATE_DESTINATION_LEG
    )
    adapter.next_outcome = "unknown"
    lifecycle.create_destination_leg(session, attempt, operation)
    session.commit()
    clock.advance(minutes=5)
    lifecycle.create_destination_leg(session, attempt, operation)
    assert len(adapter.created) == 1


def test_originate_intent_is_committed_before_provider_call(
    engine, session, lifecycle, adapter, authorization, clock
):
    _, attempt = _attempt(session, authorization, clock)
    operation = lifecycle.begin_operation(
        session, attempt, OperationKind.CREATE_DESTINATION_LEG
    )
    original = adapter.create_destination_leg
    def probe(**kwargs):
        with Session(engine) as observer:
            assert observer.get(CallOperation, operation.id) is not None
        return original(**kwargs)
    adapter.create_destination_leg = probe
    lifecycle.create_destination_leg(session, attempt, operation)


def test_unbound_event_cannot_accept_a_grant(
    session, lifecycle, adapter, authorization, clock
):
    _, attempt = _attempt(session, authorization, clock, credential=None)
    adapter.parsed = _event(attempt, "call.initiated")
    record = lifecycle.ingest(session, b"{}", {})
    assert record.disposition is EventDisposition.QUARANTINED
    assert session.exec(select(CallLeg)).all() == []


def test_membership_revocation_stops_only_the_members_work_calls(
    session, lifecycle, adapter, authorization, clock
):
    personal_user, personal = _attempt(
        session, authorization, clock, credential=None
    )
    work_user, work = _attempt(session, authorization, clock)
    organization = Organization(
        name="Revoking organization",
        primary_contact_name="Owner",
        phone_number=f"+23490{uuid4().int % 10**8:08d}",
        email=f"revocation-{uuid4().hex[:8]}@example.test",
        password_hash="test",
        org_type=OrganizationType.ENTERPRISE,
    )
    session.add(organization)
    session.flush()
    session.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=work_user.id,
            role=OrganizationRole.MEMBER,
            status=MembershipStatus.ACTIVE,
        )
    )
    work.organization_id = organization.id
    work.payer_kind = PayerKind.ORGANIZATION
    session.add(work)
    session.flush()

    adapter.parsed = _event(work, "call.initiated")
    initiated = lifecycle.ingest(session, b"{}", {})
    assert initiated.disposition is EventDisposition.APPLIED
    lifecycle.on_membership_revoked(
        session, organization.id, work_user.id, clock()
    )

    session.refresh(work)
    session.refresh(personal)
    assert work.stop_requested_at == clock()
    assert work.end_reason == "membership_revoked"
    assert set(adapter.hangups) == {"client-1", "dest-1"}
    assert personal_user.id != work_user.id
    assert personal.stop_requested_at is None
