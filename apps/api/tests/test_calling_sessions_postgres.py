"""Per-device client credentials — issuance, bounding, rate limits, revocation.

The credential model is the part of this chunk with the longest half-life: a
credential that cannot be revoked individually outlives every other mistake here,
because it keeps working after the customer has done everything they know how to
do about a lost device.
"""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app import model_registry  # noqa: F401
from app.auth.models import Platform, User
from app.calling.contract import (
    CallingCapabilities,
    CallingError,
    CallOutcomeUnknown,
    IssuedClientSession,
)
from app.calling.models import CallingClientCredential, CredentialState
from app.calling.sessions import ClientSessionError, ClientSessionService

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="the one-credential-per-device rule is a partial unique index",
)

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
TABLES = "call_events, call_attempts, calling_client_credentials, users"


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: float) -> None:
        self.value += timedelta(**kwargs)


class FakeAdapter:
    name = "fake"

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.issued = 0
        self.revoked: list[str] = []
        self.mode = "ok"
        self.stated_expiry: datetime | None = None

    def capabilities(self) -> CallingCapabilities:
        return CallingCapabilities(name=self.name, supported=frozenset())

    def issue_client_session(self, *, operation_reference, device_label):
        if self.mode == "unknown":
            raise CallOutcomeUnknown("response lost")
        if self.mode == "rejected":
            raise CallingError("provider_rejected", "no")
        self.issued += 1
        return IssuedClientSession(
            token=f"token-{self.issued}",
            identity=f"sip-{self.issued}",
            expires_at=self.stated_expiry or (self.clock() + timedelta(hours=24)),
            provider_credential_id=f"cred-{self.issued}",
            provider_connection_id="conn-1",
        )

    def revoke_client_credential(self, provider_credential_id: str) -> None:
        if self.mode == "revoke_fails":
            raise CallingError("provider_rejected", "cannot delete")
        self.revoked.append(provider_credential_id)

    def create_destination_leg(self, **kwargs):
        raise NotImplementedError

    def reconcile_operation(self, operation_reference):
        return None

    def bridge(self, **kwargs):
        raise NotImplementedError

    def hangup(self, **kwargs):
        raise NotImplementedError

    def parse_event(self, body, headers):
        raise NotImplementedError


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
def service(adapter, clock):
    return ClientSessionService(adapter, clock=clock, sessions_per_hour=3)


def _user(session: Session) -> User:
    user = User(
        phone_number=f"+23480{uuid4().int % 10**8:08d}",
        first_name="caller",
        platform=Platform.ANDROID,
    )
    session.add(user)
    session.flush()
    return user


class TestIssuance:
    def test_each_device_gets_its_own_credential(self, session, service, adapter):
        user = _user(session)

        service.issue(session, user, device_id="phone-a")
        service.issue(session, user, device_id="phone-b")

        credentials = service.active(session, user)
        assert {c.device_id for c in credentials} == {"phone-a", "phone-b"}
        assert len({c.provider_credential_id for c in credentials}) == 2

    def test_the_same_device_reuses_its_credential_row(self, session, service):
        user = _user(session)

        first, _ = service.issue(session, user, device_id="phone-a")
        second, _ = service.issue(session, user, device_id="phone-a")

        assert first.id == second.id
        assert len(service.active(session, user)) == 1

    def test_the_database_refuses_two_live_credentials_for_one_device(
        self, session, service, clock
    ):
        user = _user(session)
        service.issue(session, user, device_id="phone-a")

        session.add(
            CallingClientCredential(
                user_id=user.id,
                device_id="phone-a",
                provider="fake",
                provider_credential_id=f"cred-{uuid4().hex}",
                state=CredentialState.ACTIVE,
                created_at=clock(),
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    def test_a_session_never_outlives_its_parent_credential(
        self, session, service, adapter, clock
    ):
        """Telnyx caps a JWT at 24 hours *or* the credential's earlier expiry.

        Reporting the token's own claim when the credential dies sooner tells a
        client it has a working session for hours after it stopped working.
        """
        user = _user(session)
        credential, _ = service.issue(session, user, device_id="phone-a")
        credential.expires_at = clock() + timedelta(minutes=30)
        session.add(credential)
        session.flush()

        adapter.stated_expiry = clock() + timedelta(hours=24)
        _credential, issued = service.issue(session, user, device_id="phone-a")

        assert issued.expires_at <= clock() + timedelta(hours=24)

    def test_a_blank_device_id_is_refused(self, session, service):
        user = _user(session)
        with pytest.raises(ClientSessionError) as excinfo:
            service.issue(session, user, device_id="   ")
        assert excinfo.value.code == "device_id_required"

    def test_a_lost_response_does_not_create_a_second_credential(
        self, session, service, adapter
    ):
        """An orphan credential at the provider is unrevocable and can register.

        So a lost response stops and says so rather than trying again — the
        retry is what leaves the orphan behind.
        """
        user = _user(session)
        adapter.mode = "unknown"

        with pytest.raises(ClientSessionError) as excinfo:
            service.issue(session, user, device_id="phone-a")

        assert excinfo.value.code == "session_outcome_unknown"
        assert service.active(session, user) == []

    def test_a_provider_refusal_surfaces_its_code(self, session, service, adapter):
        user = _user(session)
        adapter.mode = "rejected"

        with pytest.raises(ClientSessionError) as excinfo:
            service.issue(session, user, device_id="phone-a")
        assert excinfo.value.code == "provider_rejected"


class TestRateLimiting:
    def test_a_device_is_capped_within_the_window(self, session, service):
        user = _user(session)
        for _ in range(3):
            service.issue(session, user, device_id="phone-a")

        with pytest.raises(ClientSessionError) as excinfo:
            service.issue(session, user, device_id="phone-a")
        assert excinfo.value.code == "session_rate_limited"

    def test_the_window_rolls_forward(self, session, service, clock):
        user = _user(session)
        for _ in range(3):
            service.issue(session, user, device_id="phone-a")

        clock.advance(hours=2)
        credential, _ = service.issue(session, user, device_id="phone-a")

        assert credential.sessions_issued == 1

    def test_the_counter_survives_a_restart(self, session, service, adapter, clock):
        """The limit lives on the row, not in a process or in Redis.

        A counter that a restart clears is not a limit; it is a speed bump that
        disappears exactly when somebody is deliberately attacking it.
        """
        user = _user(session)
        for _ in range(3):
            service.issue(session, user, device_id="phone-a")

        fresh = ClientSessionService(adapter, clock=clock, sessions_per_hour=3)
        with pytest.raises(ClientSessionError):
            fresh.issue(session, user, device_id="phone-a")


class TestRevocation:
    def test_revoking_one_device_leaves_the_others(self, session, service, adapter):
        user = _user(session)
        service.issue(session, user, device_id="phone-a")
        service.issue(session, user, device_id="phone-b")

        service.revoke(session, user, device_id="phone-a", reason="lost")

        remaining = service.active(session, user)
        assert [c.device_id for c in remaining] == ["phone-b"]
        assert adapter.revoked == ["cred-1"]

    def test_revoking_everything_takes_every_device(self, session, service):
        user = _user(session)
        service.issue(session, user, device_id="phone-a")
        service.issue(session, user, device_id="phone-b")

        revoked = service.revoke(session, user, reason="logout")

        assert len(revoked) == 2
        assert service.active(session, user) == []

    def test_one_users_revocation_does_not_touch_another(self, session, service):
        first = _user(session)
        second = _user(session)
        service.issue(session, first, device_id="phone-a")
        service.issue(session, second, device_id="phone-a")

        service.revoke(session, first, reason="logout")

        assert len(service.active(session, second)) == 1

    def test_a_provider_failure_still_revokes_locally_and_records_why(
        self, session, service, adapter
    ):
        """A credential we have stopped honouring beats one we failed to delete.

        Leaving the row active because the remote delete failed would keep the
        credential usable in *our* system, which is the half we control.
        """
        user = _user(session)
        service.issue(session, user, device_id="phone-a")
        adapter.mode = "revoke_fails"

        revoked = service.revoke(session, user, device_id="phone-a", reason="lost")

        assert revoked[0].state is CredentialState.REVOKED
        assert "unconfirmed" in (revoked[0].revoked_reason or "")

    def test_a_revoked_device_can_register_again(self, session, service):
        user = _user(session)
        service.issue(session, user, device_id="phone-a")
        service.revoke(session, user, device_id="phone-a", reason="logout")

        credential, _ = service.issue(session, user, device_id="phone-a")

        assert credential.state is CredentialState.ACTIVE
        # The old row survives, because it explains which credential originated a
        # call that was already billed.
        history = session.exec(
            select(CallingClientCredential).where(
                CallingClientCredential.user_id == user.id
            )
        ).all()
        assert len(history) == 2
