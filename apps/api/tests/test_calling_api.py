"""The calling API surface — US-45, chunk V02.

These run against SQLite through the ordinary app fixture, which is the right
level for *this* file: it checks status codes, scoping, response shapes and the
refusals a client can provoke. The guarantees that are database guarantees —
single-use grants, duplicate legs, shared-funds races — are proved in
`test_calling_authorization_postgres.py` and `test_calling_lifecycle_postgres.py`
against real PostgreSQL, because a SQLite pass would prove they did not exist.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.routes import request_otp, verify_otp
from app.auth.schemas import OTPRequest, OTPVerifyRequest
from app.calling.contract import (
    CallingCapabilities,
    CallingCapability,
    IssuedClientSession,
    ProviderLegHandle,
)
from app.calling.models import CallingClientCredential
from app.calling.telnyx import DisabledCallingAdapter, TelnyxCallingAdapter
from app.catalog.market import PublicationStatus
from app.catalog.models import Product, ProductKind
from app.catalog.tariffs import DestinationKind, OriginKind, Tariff, TariffRate
from app.config import Settings
from app.ledger.models import AccountKind, Direction, OwnerKind
from app.ledger.service import LedgerService, Posting
from app.main import create_app

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)


@dataclass
class FakeCallingAdapter:
    """A provider that always succeeds, so the *API* is what is under test."""

    name: str = "fake"
    issued: list[str] = field(default_factory=list)
    revoked: list[str] = field(default_factory=list)

    def capabilities(self) -> CallingCapabilities:
        return CallingCapabilities(
            name=self.name,
            supported=frozenset({CallingCapability.PARKED_ORIGINATION}),
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
        self.issued.append(device_label)
        suffix = len(self.issued)
        return IssuedClientSession(
            token=f"token-{suffix}",
            identity=sip_identity or f"sip-user-{suffix}",
            expires_at=credential_expires_at or (NOW + timedelta(hours=1)),
            provider_credential_id=provider_credential_id or f"cred-{suffix}",
            provider_connection_id="conn-1",
        )

    def revoke_client_credential(self, provider_credential_id: str) -> None:
        self.revoked.append(provider_credential_id)

    def create_destination_leg(self, **kwargs):
        return ProviderLegHandle(control_id="dest-1")

    def reconcile_operation(self, operation_reference):
        return None

    def bridge(self, **kwargs) -> None:
        return None

    def hangup(self, **kwargs) -> None:
        return None

    def parse_event(self, body, headers):
        raise NotImplementedError


@pytest.fixture
def calling_settings() -> Settings:
    """A deployment with the live route on, as its validator requires.

    Every field below is required together: `Settings` refuses to start with the
    flag set and any of them missing, which is the point — a flag alone must not
    put billable calls on a wire.
    """
    return Settings(
        app_env="test",
        database_url="sqlite://",
        redis_url="redis://unused",
        jwt_secret="test-secret-at-least-32-characters-long",
        otp_provider_primary="termii",
        otp_provider_secondary="twilio",
        otp_failover_threshold_seconds=180,
        otp_request_timeout_seconds=10,
        termii_webhook_secret="termii-webhook-secret",
        calling_live_routes_enabled=True,
        telnyx_api_key="test-key",
        telnyx_connection_id="conn-1",
        telnyx_public_key="dGVzdC1wdWJsaWMta2V5LTMyLWJ5dGVzLWxvbmchIQ==",
        calling_containment_evidence_reference="docs/.../B1-account-test.md",
        calling_outbound_identity_e164="+2347000000001",
        calling_supported_destination_countries=["NG"],
    )


@pytest.fixture
def adapter() -> FakeCallingAdapter:
    return FakeCallingAdapter()


def test_calling_revocation_hooks_are_registered(calling_api):
    assert (
        calling_api.state.call_lifecycle_service
        in calling_api.state.membership_service.revocation_listeners
    )
    assert (
        calling_api.state.client_session_service
        in calling_api.state.identity_service.recovery_listeners
    )


@pytest.fixture
def calling_api(
    calling_settings,
    redis_client,
    providers,
    scheduler,
    clock,
    session_factory,
    adapter,
):
    clock.value = NOW
    return create_app(
        settings=calling_settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
        calling_adapter=adapter,
    )


def _authenticated(api, phone_number: str = "08012345678") -> tuple[TestClient, UUID]:
    request = SimpleNamespace(app=api)
    request_otp(OTPRequest(phone_number=phone_number), request)
    auth = verify_otp(
        OTPVerifyRequest(phone_number=phone_number, otp="123456", platform="android"),
        request,
    )
    return (
        TestClient(
            api,
            headers={"Authorization": f"Bearer {auth.access_token}"},
            raise_server_exceptions=False,
        ),
        auth.user.id,
    )


def _publish_rate(session_factory, clock) -> None:
    with session_factory() as session:
        product = Product(
            sku=f"voice-{uuid4().hex[:8]}",
            name="Internet calling",
            kind=ProductKind.VOICE,
        )
        session.add(product)
        session.flush()
        tariff = Tariff(
            product_id=product.id,
            currency="NGN",
            version=1,
            status=PublicationStatus.PUBLISHED,
            effective_from=NOW - timedelta(days=1),
            evidence_reference="test fixture — not a rate claim (B2 open)",
            verified_at=NOW - timedelta(days=1),
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
        session.commit()


def _fund(session_factory, user_id: UUID, amount: str = "10000.00") -> None:
    ledger = LedgerService()
    with session_factory() as session:
        credit = ledger.account(
            session,
            "NGN",
            AccountKind.SERVICE_CREDIT,
            OwnerKind.USER,
            owner_user_id=user_id,
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
        session.commit()


class TestEligibility:
    def test_prices_a_call_without_holding_anything(
        self, calling_api, session_factory, clock
    ):
        client, user_id = _authenticated(calling_api)
        _publish_rate(session_factory, clock)
        _fund(session_factory, user_id)

        response = client.get(
            "/v1/calls/eligibility",
            params={
                "destination": "+2348031234567",
                "currency": "NGN",
                "requested_seconds": 600,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["destination_e164"] == "+2348031234567"
        assert body["max_charge_amount"] == "300.00"
        assert body["fundable"] is True
        assert body["route_enabled"] is True

    def test_an_emergency_number_is_refused(self, calling_api, session_factory, clock):
        client, user_id = _authenticated(calling_api)
        _publish_rate(session_factory, clock)
        _fund(session_factory, user_id)

        response = client.get(
            "/v1/calls/eligibility",
            params={"destination": "+234112", "currency": "NGN"},
        )

        assert response.status_code == 409
        assert response.json()["error"] == "destination_emergency_or_special"

    def test_it_requires_authentication(self, calling_api):
        anonymous = TestClient(calling_api, raise_server_exceptions=False)
        response = anonymous.get(
            "/v1/calls/eligibility",
            params={"destination": "+2348031234567", "currency": "NGN"},
        )
        assert response.status_code == 401


class TestClientSessions:
    def test_a_session_is_issued_per_device(self, calling_api, adapter):
        client, _user_id = _authenticated(calling_api)

        response = client.post(
            "/v1/calls/client-session",
            json={"device_id": "phone-a", "device_label": "Pixel"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["token"] == "token-1"
        assert body["sip_identity"] == "sip-user-1"
        assert adapter.issued == ["Pixel"]

    def test_revoking_one_device_leaves_the_other(
        self, calling_api, session_factory, adapter
    ):
        client, user_id = _authenticated(calling_api)
        client_session = client.post(
            "/v1/calls/client-session", json={"device_id": "phone-a"}
        )
        assert client_session.status_code == 200, client_session.text
        client.post("/v1/calls/client-session", json={"device_id": "phone-b"})

        response = client.request(
            "DELETE", "/v1/calls/client-session", params={"device_id": "phone-a"}
        )

        assert response.status_code == 204
        with session_factory() as session:
            from sqlmodel import select

            live = session.exec(
                select(CallingClientCredential).where(
                    CallingClientCredential.user_id == user_id,
                    CallingClientCredential.state == "active",
                )
            ).all()
        # This is the whole reason credentials are per device: signing out one
        # installation must not sign out the customer's other devices.
        assert [credential.device_id for credential in live] == ["phone-b"]


class TestAuthorizeAndStart:
    def test_the_full_authorize_then_start_path(
        self, calling_api, session_factory, clock
    ):
        client, user_id = _authenticated(calling_api)
        _publish_rate(session_factory, clock)
        _fund(session_factory, user_id)
        client.post("/v1/calls/client-session", json={"device_id": "phone-a"})

        authorized = client.post(
            "/v1/calls/authorize",
            json={
                "destination": "+2348031234567",
                "idempotency_key": "call-key-0001",
                "currency": "NGN",
                "device_id": "phone-a",
                "requested_seconds": 600,
            },
        )
        assert authorized.status_code == 201, authorized.text
        attempt_id = authorized.json()["attempt_id"]
        assert authorized.json()["state"] == "authorized"
        # The identity is the server's, never the client's request.
        assert authorized.json()["identity_e164"] == "+2347000000001"

        started = client.post(
            f"/v1/calls/{attempt_id}/start", params={"device_id": "phone-a"}
        )
        assert started.status_code == 200
        assert started.json()["destination_e164"] == "+2348031234567"
        assert started.json()["correlation"] == attempt_id

    def test_no_provider_identifier_reaches_the_client(
        self, calling_api, session_factory, clock
    ):
        client, user_id = _authenticated(calling_api)
        _publish_rate(session_factory, clock)
        _fund(session_factory, user_id)

        body = client.post(
            "/v1/calls/authorize",
            json={
                "destination": "+2348031234567",
                "idempotency_key": "call-key-0002",
                "currency": "NGN",
            },
        ).json()

        # Our attempt-to-leg mapping is authoritative; a client that learned a
        # provider id would start correlating on it (invariant 7).
        for forbidden in ("call_control_id", "connection_id", "call_session_id"):
            assert forbidden not in body

    def test_replaying_the_key_returns_the_same_attempt(
        self, calling_api, session_factory, clock
    ):
        client, user_id = _authenticated(calling_api)
        _publish_rate(session_factory, clock)
        _fund(session_factory, user_id)
        payload = {
            "destination": "+2348031234567",
            "idempotency_key": "call-key-0003",
            "currency": "NGN",
        }

        first = client.post("/v1/calls/authorize", json=payload)
        second = client.post("/v1/calls/authorize", json=payload)

        assert first.json()["attempt_id"] == second.json()["attempt_id"]

    def test_an_unfunded_call_is_refused_with_409(
        self, calling_api, session_factory, clock
    ):
        client, _user_id = _authenticated(calling_api)
        _publish_rate(session_factory, clock)

        response = client.post(
            "/v1/calls/authorize",
            json={
                "destination": "+2348031234567",
                "idempotency_key": "call-key-0004",
                "currency": "NGN",
            },
        )

        assert response.status_code == 409
        assert response.json()["error"] == "insufficient_funds"

    def test_another_users_attempt_is_not_found(
        self, calling_api, session_factory, clock
    ):
        owner, owner_id = _authenticated(calling_api, "08011111111")
        intruder, _ = _authenticated(calling_api, "08022222222")
        _publish_rate(session_factory, clock)
        _fund(session_factory, owner_id)
        attempt_id = owner.post(
            "/v1/calls/authorize",
            json={
                "destination": "+2348031234567",
                "idempotency_key": "call-key-0005",
                "currency": "NGN",
            },
        ).json()["attempt_id"]

        response = intruder.get(f"/v1/calls/{attempt_id}")

        # 404 and not 403: a distinct answer would confirm the id is real.
        assert response.status_code == 404
        assert response.json()["error"] == "attempt_not_found"

    def test_history_is_scoped_to_the_caller(
        self, calling_api, session_factory, clock
    ):
        owner, owner_id = _authenticated(calling_api, "08011111111")
        intruder, _ = _authenticated(calling_api, "08022222222")
        _publish_rate(session_factory, clock)
        _fund(session_factory, owner_id)
        owner.post(
            "/v1/calls/authorize",
            json={
                "destination": "+2348031234567",
                "idempotency_key": "call-key-0006",
                "currency": "NGN",
            },
        )

        assert len(owner.get("/v1/calls").json()["attempts"]) == 1
        assert intruder.get("/v1/calls").json()["attempts"] == []


class TestDisabledRoute:
    @pytest.fixture
    def disabled_api(
        self, settings, redis_client, providers, scheduler, clock, session_factory
    ):
        clock.value = NOW
        return create_app(
            settings=settings,
            redis_client=redis_client,
            providers=providers,
            scheduler=scheduler,
            session_factory=session_factory,
            clock=clock,
        )

    def test_a_default_deployment_cannot_start_a_call(
        self, disabled_api, session_factory, clock
    ):
        client, user_id = _authenticated(disabled_api)
        _publish_rate(session_factory, clock)
        _fund(session_factory, user_id)

        # The default deployment sells to no country, so nothing is even
        # priceable. That is the honest state while B2 is open.
        response = client.get(
            "/v1/calls/eligibility",
            params={"destination": "+2348031234567", "currency": "NGN"},
        )
        assert response.status_code == 409
        assert response.json()["error"] == "destination_country_not_supported"

    def test_a_client_session_is_refused_with_503(self, disabled_api):
        client, _user_id = _authenticated(disabled_api)
        response = client.post(
            "/v1/calls/client-session", json={"device_id": "phone-a"}
        )
        # 503, not 4xx: the request is fine and no request the client can make
        # will work while the route is off.
        assert response.status_code == 503
        assert response.json()["error"] == "calling_route_disabled"


class TestConfiguration:
    @pytest.mark.parametrize(
        ("configured", "value"),
        (("telnyx_api_key", "control-key"), ("telnyx_public_key", "event-key")),
    )
    def test_disabling_new_calls_keeps_configured_provider_recovery(
        self,
        settings,
        redis_client,
        providers,
        scheduler,
        clock,
        session_factory,
        configured,
        value,
    ):
        retained = settings.model_copy(update={configured: value})
        api = create_app(
            settings=retained,
            redis_client=redis_client,
            providers=providers,
            scheduler=scheduler,
            session_factory=session_factory,
            clock=clock,
        )

        assert retained.calling_live_routes_enabled is False
        assert isinstance(api.state.calling_adapter, TelnyxCallingAdapter)

    def test_an_unconfigured_deployment_uses_the_disabled_adapter(
        self,
        settings,
        redis_client,
        providers,
        scheduler,
        clock,
        session_factory,
    ):
        api = create_app(
            settings=settings,
            redis_client=redis_client,
            providers=providers,
            scheduler=scheduler,
            session_factory=session_factory,
            clock=clock,
        )

        assert isinstance(api.state.calling_adapter, DisabledCallingAdapter)

    def test_enabling_the_route_without_evidence_fails_at_startup(self):
        """A flag alone must not put billable calls on a wire."""
        with pytest.raises(ValueError) as excinfo:
            Settings(
                app_env="test",
                database_url="sqlite://",
                redis_url="redis://unused",
                jwt_secret="test-secret-at-least-32-characters-long",
                otp_provider_primary="termii",
                otp_provider_secondary="twilio",
                calling_live_routes_enabled=True,
            )
        message = str(excinfo.value)
        assert "CALLING_CONTAINMENT_EVIDENCE_REFERENCE" in message
        assert "B1" in message

    def test_enabling_the_route_without_a_destination_country_fails(self):
        with pytest.raises(ValueError) as excinfo:
            Settings(
                app_env="test",
                database_url="sqlite://",
                redis_url="redis://unused",
                jwt_secret="test-secret-at-least-32-characters-long",
                otp_provider_primary="termii",
                otp_provider_secondary="twilio",
                calling_live_routes_enabled=True,
                telnyx_api_key="k",
                telnyx_connection_id="c",
                telnyx_public_key="p",
                calling_containment_evidence_reference="ref",
                calling_outbound_identity_e164="+2347000000001",
            )
        assert "destination country" in str(excinfo.value)
