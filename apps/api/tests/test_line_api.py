"""US-38 chunk 20 — My Line and eSIM installation over HTTP.

Two properties this file exists to pin down, and both are about what the API
refuses to do.

**A read never returns a profile.** `GET /v1/me/lines/{id}` is the screen a
pull-to-refresh, a push handler and a support tool all hit; if installation
material travelled in it, a one-time-use eSIM would be sitting in every proxy
log and crash report between here and the handset. Delivery is two deliberate
calls, and the second one is spent.

**No state is inferred from a neighbouring one.** The tests below drive
installation, activation and network attachment apart on purpose — installed but
never attached, active but not installed, suspended with the profile still on the
phone — because those are the combinations the field actually produces and the
ones a collapsed "status" field would have to lie about.
"""

from __future__ import annotations

import os
from base64 import b64encode
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.models import Locale, User, UserStatus
from app.catalog.market import (
    DeviceEligibilityRule,
    NumberAssignment,
    NumberPolicy,
    NumberType,
    PublicationStatus,
)
from app.catalog.models import LegalEntity, Product, ProductKind
from app.catalog.tariffs import DestinationKind, OriginKind, Tariff, TariffRate
from app.config import Settings
from app.connectivity.models import (
    ActivationState,
    AssignedNumber,
    CarrierLine,
    Entitlement,
    EsimInstallation,
    InstallationState,
    NetworkState,
)
from app.controls.models import (
    ControlState,
    Enforcement,
    EntitlementTopUp,
    SpendingControl,
    TopUpState,
)
from app.ledger.models import AccountKind, Reservation, ReservationState
from app.ledger.service import LedgerService
from app.orders.models import Order, OrderItem, PaymentState, ProvisioningState

NOW = datetime(2026, 7, 13, tzinfo=timezone.utc)
LPA = "LPA:1$rsp.example.test$TEST-ACTIVATION-CODE"

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason=(
        "chunk 15's connectivity tables carry PostgreSQL-only DDL and the "
        "credential vault is exercised against real column types"
    ),
)


@pytest.fixture
def settings() -> Settings:
    """The base fixture plus an activation-material key.

    Deliberately a per-test key made here rather than a constant: a key checked
    into the repository is a key, and `security.md` keeps activation material
    out of fixtures for exactly the reason this module is about.
    """
    return Settings(
        app_env="test",
        database_url="sqlite://",
        redis_url="redis://unused",
        jwt_secret="test-secret-at-least-32-characters-long",
        termii_webhook_secret="termii-webhook-secret",
        activation_material_key=b64encode(os.urandom(32)).decode(),
    )


@pytest.fixture
def session_factory():
    """The app on real PostgreSQL, in a schema of its own."""
    url = os.environ["TEST_DATABASE_URL"]
    schema = f"line_{uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        SQLModel.metadata.create_all(engine)
        yield lambda: Session(engine)
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def client(api: FastAPI) -> TestClient:
    return TestClient(api)


def _user(session: Session, suffix: str = "0001") -> User:
    user = User(
        phone_number=f"+234801000{suffix}",
        email=f"holder-{suffix}@example.test",
        locale=Locale.EN,
        status=UserStatus.ACTIVE,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    session.expunge(user)
    return user


def _auth(api: FastAPI, user: User) -> dict[str, str]:
    with api.state.session_factory() as session:
        pair = api.state.otp_service.tokens.issue(
            session, session.get(User, user.id), api.state.clock()
        )
        session.commit()
    return {"Authorization": f"Bearer {pair.access_token}"}


def _line(
    api: FastAPI,
    session: Session,
    holder: User,
    *,
    requires_esim: bool = True,
    with_installation: bool = True,
    installation_state: InstallationState = InstallationState.NOT_INSTALLED,
    with_carrier_line: bool = True,
    activation_state: ActivationState = ActivationState.ACTIVE,
    network_state: NetworkState = NetworkState.UNKNOWN,
    voice_enabled: bool = True,
    with_number: bool = True,
    #: Whether the *plan* promises a number at all. Distinct from `with_number`,
    #: which is whether the carrier has assigned one yet.
    includes_number: bool = True,
    with_credential: bool = True,
    with_tariff: bool = True,
    expires_at: datetime | None = None,
) -> Entitlement:
    """One provisioned line, assembled the way chunks 11 and 15 would leave it.

    Every optional part is a real state the field produces: a profile issued but
    not installed, a line active with no number yet, an internet grant with no
    carrier resources at all. The defaults are the ordinary case; each test
    turns off the one piece it is about.
    """
    entity = LegalEntity(code=uuid4().hex[:8], name="Test Seller Ltd", country="NG")
    session.add(entity)
    product = Product(sku=uuid4().hex[:12], name="Travel 5GB", kind=ProductKind.BUNDLE)
    session.add(product)
    session.commit()
    session.refresh(entity)
    session.refresh(product)

    session.add(
        DeviceEligibilityRule(
            product_id=product.id,
            requires_esim=requires_esim,
            requires_unlocked_device=True,
        )
    )
    session.add(
        NumberPolicy(
            product_id=product.id,
            number_type=NumberType.MOBILE if includes_number else NumberType.NONE,
            number_country="NG" if includes_number else None,
            assignment=(
                NumberAssignment.NEW_ASSIGNED
                if includes_number
                else NumberAssignment.NONE
            ),
        )
    )

    order = Order(
        reference=f"OR-{uuid4().hex[:8].upper()}",
        seller_legal_entity_id=entity.id,
        payer_user_id=holder.id,
        currency="NGN",
        total_amount=Decimal("10000.00"),
        payment_state=PaymentState.PAID,
        placed_at=NOW - timedelta(hours=2),
    )
    session.add(order)
    session.commit()
    session.refresh(order)

    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        recipient_user_id=holder.id,
        quantity=1,
        unit_currency="NGN",
        unit_amount=Decimal("10000.00"),
        provisioning_state=ProvisioningState.PROVISIONED,
    )
    session.add(item)
    session.commit()
    session.refresh(item)

    entitlement = Entitlement(
        order_item_id=item.id,
        holder_user_id=holder.id,
        product_id=product.id,
        data_bytes_total=5_368_709_120,
        voice_seconds_total=3_600,
        granted_at=NOW - timedelta(hours=1),
        expires_at=expires_at,
    )
    session.add(entitlement)
    session.commit()
    session.refresh(entitlement)

    if with_installation:
        installation = EsimInstallation(
            entitlement_id=entitlement.id,
            installation_state=installation_state,
            profile_released_at=NOW - timedelta(minutes=50),
            installed_at=(
                NOW - timedelta(minutes=40)
                if installation_state is InstallationState.INSTALLED
                else None
            ),
        )
        session.add(installation)
        session.commit()
        session.refresh(installation)
        if with_credential:
            api.state.credential_vault.store(session, installation, LPA)
            session.commit()

    if with_carrier_line:
        line = CarrierLine(
            entitlement_id=entitlement.id,
            carrier="telnyx",
            carrier_line_reference=uuid4().hex,
            activation_state=activation_state,
            network_state=network_state,
            network_state_observed_at=(
                NOW - timedelta(minutes=5)
                if network_state is not NetworkState.UNKNOWN
                else None
            ),
            provider_status="active",
            provider_status_observed_at=NOW - timedelta(minutes=5),
            voice_enabled=voice_enabled,
            voice_enabled_observed_at=NOW - timedelta(minutes=5),
        )
        session.add(line)
        session.commit()
        session.refresh(line)
        if with_number:
            session.add(
                AssignedNumber(
                    carrier_line_id=line.id,
                    # Unique per line: `ux_assigned_numbers_live_e164` is a real
                    # constraint, and a fixture that reuses one number is a
                    # fixture that cannot build two lines.
                    e164=f"+234901{uuid4().int % 10_000_000:07d}",
                    country="NG",
                    assigned_at=NOW - timedelta(minutes=30),
                )
            )
            session.commit()

    if with_tariff:
        tariff = Tariff(
            product_id=product.id,
            currency="NGN",
            version=1,
            status=PublicationStatus.PUBLISHED,
            effective_from=NOW - timedelta(days=1),
            evidence_reference="docs/implementation/handoffs/09.md",
            verified_at=NOW - timedelta(days=1),
        )
        session.add(tariff)
        session.commit()
        session.refresh(tariff)
        session.add(
            TariffRate(
                tariff_id=tariff.id,
                origin_kind=OriginKind.CARRIER_VISITED_NETWORK,
                destination_country="NG",
                destination_kind=DestinationKind.MOBILE,
                per_minute_amount=Decimal("25.500000"),
                setup_amount=Decimal("0.00"),
                minimum_seconds=30,
                increment_seconds=60,
            )
        )
        session.commit()

    session.refresh(entitlement)
    session.expunge(entitlement)
    return entitlement


# --- the view ---------------------------------------------------------------


def test_carrier_rates_exclude_internet_and_preserve_roaming_origin(api, client):
    with api.state.session_factory() as session:
        holder = _user(session)
        entitlement = _line(api, session, holder)
        tariff = session.exec(select(Tariff)).one()
        session.add(TariffRate(
            tariff_id=tariff.id, origin_kind=OriginKind.INTERNET,
            destination_country="NG", destination_kind=DestinationKind.MOBILE,
            per_minute_amount=Decimal("0.01"), setup_amount=Decimal("0"),
            minimum_seconds=1, increment_seconds=1,
        ))
        rate = session.exec(select(TariffRate).where(
            TariffRate.origin_kind == OriginKind.CARRIER_VISITED_NETWORK
        )).one()
        rate.origin_country = "GB"
        session.add(rate)
        session.commit()
    body = client.get(
        f"/v1/me/lines/{entitlement.id}", headers=_auth(api, holder)
    ).json()
    rates = body["tariff"]["destinations"]
    assert len(rates) == 1
    assert rates[0]["origin_country"] == "GB"
    assert Decimal(rates[0]["per_minute_amount"]) == Decimal("25.5")


def test_my_line_reports_every_state_separately(
    api: FastAPI, client: TestClient
) -> None:
    """Installed, active, attached and priced are four answers, not one."""
    with api.state.session_factory() as session:
        holder = _user(session)
        entitlement = _line(
            api,
            session,
            holder,
            installation_state=InstallationState.INSTALLED,
            network_state=NetworkState.ATTACHED,
        )
    headers = _auth(api, holder)

    response = client.get(f"/v1/me/lines/{entitlement.id}", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["number_status"] == "assigned"
    assert body["assigned_number"]["e164"].startswith("+234901")
    assert body["assigned_number"]["country"] == "NG"
    assert body["installation"]["state"] == "installed"
    assert body["line"]["activation_state"] == "active"
    assert body["line"]["network_state"] == "attached"
    assert body["line"]["network_state_observed_at"] is not None
    assert body["ready_to_use"] is True
    # Full stored precision, not the currency's two places: a rate rounded to
    # money cannot represent a fraction of a kobo.
    assert body["tariff"]["destinations"][0]["per_minute_amount"].startswith(
        "25.5"
    )
    assert Decimal(
        body["tariff"]["destinations"][0]["per_minute_amount"]
    ) == Decimal("25.5")
    assert body["tariff"]["destinations"][0]["minimum_seconds"] == 30


def test_an_installed_profile_on_an_unattached_line_is_not_ready(
    api: FastAPI, client: TestClient
) -> None:
    """The combination the whole schema split exists for.

    The profile is on the phone and the carrier has not activated the line.
    Reporting this as ready is telling somebody their phone works when it does
    not, which is the single most expensive thing this screen can get wrong.
    """
    with api.state.session_factory() as session:
        holder = _user(session)
        entitlement = _line(
            api,
            session,
            holder,
            installation_state=InstallationState.INSTALLED,
            activation_state=ActivationState.PENDING,
        )
    headers = _auth(api, holder)

    body = client.get(f"/v1/me/lines/{entitlement.id}", headers=headers).json()

    assert body["installation"]["state"] == "installed"
    assert body["line"]["activation_state"] == "pending"
    assert body["ready_to_use"] is False
    assert body["calling"]["native_available"] is False
    assert body["calling"]["native_unavailable_reason"] == "line_not_active"


def test_network_attachment_is_never_inferred_from_activation(
    api: FastAPI, client: TestClient
) -> None:
    with api.state.session_factory() as session:
        holder = _user(session)
        entitlement = _line(
            api,
            session,
            holder,
            installation_state=InstallationState.INSTALLED,
            activation_state=ActivationState.ACTIVE,
            network_state=NetworkState.UNKNOWN,
        )
    headers = _auth(api, holder)

    body = client.get(f"/v1/me/lines/{entitlement.id}", headers=headers).json()

    assert body["line"]["activation_state"] == "active"
    assert body["line"]["network_state"] == "unknown"
    assert body["line"]["network_state_observed_at"] is None


def test_usage_that_has_never_been_measured_says_so(
    api: FastAPI, client: TestClient
) -> None:
    """`unknown` freshness, not a full bar.

    Nothing has ever measured this line, so the grant is all there is. Drawing
    it as a measurement is what AC-36.4 forbids, and a customer reading "5 GB
    left" off a line nobody has polled is being told a number we do not have.
    """
    with api.state.session_factory() as session:
        holder = _user(session)
        entitlement = _line(api, session, holder)
    headers = _auth(api, holder)

    usage = client.get(f"/v1/me/lines/{entitlement.id}", headers=headers).json()[
        "usage"
    ]

    assert usage["freshness"] == "unknown"
    assert usage["observed_at"] is None
    assert usage["data_bytes_total"] == 5_368_709_120
    assert usage["data_bytes_used"] == 0


def test_a_suspended_line_reports_the_restriction_and_who_enforces_it(
    api: FastAPI, client: TestClient
) -> None:
    with api.state.session_factory() as session:
        holder = _user(session)
        entitlement = _line(
            api,
            session,
            holder,
            installation_state=InstallationState.INSTALLED,
            activation_state=ActivationState.SUSPENDED,
        )
        line = session.exec(
            CarrierLine.__table__.select().where(
                CarrierLine.__table__.c.entitlement_id == entitlement.id
            )
        ).first()
        session.add(
            SpendingControl(
                carrier_line_id=line.id,
                enforcement=Enforcement.NONE,
                state=ControlState.FAILED,
                requested_limit_bytes=5_368_709_120,
                confirmed_limit_bytes=None,
                detail="supplier declined the cap",
                requested_at=NOW - timedelta(minutes=20),
            )
        )
        session.commit()
    headers = _auth(api, holder)

    body = client.get(f"/v1/me/lines/{entitlement.id}", headers=headers).json()

    assert body["restriction"]["suspended"] is True
    # The requested figure is not shown as the cap in force. Chunk 17 keeps them
    # apart so a customer is never told a limit moved when it has not.
    assert body["restriction"]["requested_limit_bytes"] == 5_368_709_120
    assert body["restriction"]["confirmed_limit_bytes"] is None
    assert body["restriction"]["enforcement"] == "none"


def _top_up(
    session: Session,
    entitlement: Entitlement,
    *,
    state: TopUpState,
    data_bytes: int,
    voice_seconds: int = 0,
    extends_days: int = 0,
) -> None:
    """One top-up, with the order item and reservation its constraints require.

    Both are real requirements rather than fixture ceremony: `order_item_id` is
    unique per top-up (one purchase, one top-up, however many times a worker
    replays it) and every spendable state must name the reservation the money
    was held against.
    """
    item = session.get(OrderItem, entitlement.order_item_id)
    extra_item = OrderItem(
        order_id=item.order_id,
        product_id=item.product_id,
        recipient_user_id=item.recipient_user_id,
        quantity=1,
        unit_currency="NGN",
        unit_amount=Decimal("2000.00"),
        provisioning_state=ProvisioningState.PROVISIONED,
    )
    session.add(extra_item)
    session.commit()
    session.refresh(extra_item)

    account = LedgerService().account(
        session, "NGN", AccountKind.SERVICE_CREDIT
    )
    reservation = Reservation(
        business_event_id=f"reservation-{uuid4().hex}",
        account_id=account.id,
        currency="NGN",
        amount=Decimal("2000.00"),
        settled_amount=Decimal("2000.00"),
        released_amount=Decimal("0.00"),
        state=ReservationState.SETTLED,
        created_at=NOW - timedelta(minutes=12),
        closed_at=NOW - timedelta(minutes=11),
    )
    session.add(reservation)
    session.commit()
    session.refresh(reservation)

    session.add(
        EntitlementTopUp(
            entitlement_id=entitlement.id,
            order_item_id=extra_item.id,
            business_event_id=f"top-up-{uuid4().hex}",
            reservation_id=reservation.id,
            data_bytes=data_bytes,
            voice_seconds=voice_seconds,
            extends_days=extends_days,
            currency="NGN",
            amount=Decimal("2000.00"),
            state=state,
            requested_at=NOW - timedelta(minutes=10),
            applied_at=(
                NOW - timedelta(minutes=9) if state is TopUpState.APPLIED else None
            ),
        )
    )
    session.commit()


def test_only_applied_top_ups_count_toward_the_balance(
    api: FastAPI, client: TestClient
) -> None:
    """A paid top-up whose cap has not been raised is pending, not spendable.

    Telling a customer they have data the supplier has not granted produces a
    session that fails for a reason the app just denied.
    """
    with api.state.session_factory() as session:
        holder = _user(session)
        entitlement = _line(api, session, holder)
        _top_up(
            session,
            entitlement,
            state=TopUpState.APPLIED,
            data_bytes=1_073_741_824,
            voice_seconds=600,
            extends_days=7,
        )
        _top_up(
            session,
            entitlement,
            state=TopUpState.PAID,
            data_bytes=2_147_483_648,
        )
    headers = _auth(api, holder)

    body = client.get(f"/v1/me/lines/{entitlement.id}", headers=headers).json()

    assert body["top_ups"]["applied_data_bytes"] == 1_073_741_824
    assert body["top_ups"]["pending_count"] == 1
    # The applied top-up is in the balance; the merely paid one is not.
    assert body["usage"]["data_bytes_total"] == 5_368_709_120 + 1_073_741_824


def test_an_internet_grant_reports_no_profile_rather_than_an_uninstalled_one(
    api: FastAPI, client: TestClient
) -> None:
    """Null, not `not_installed`. There is no profile to install."""
    with api.state.session_factory() as session:
        holder = _user(session)
        entitlement = _line(
            api,
            session,
            holder,
            requires_esim=False,
            with_installation=False,
            with_carrier_line=False,
            with_number=False,
        )
    headers = _auth(api, holder)

    body = client.get(f"/v1/me/lines/{entitlement.id}", headers=headers).json()

    assert body["delivery"] == "internet"
    assert body["installation"] is None
    assert body["line"] is None
    assert body["number_status"] == "not_included"
    assert body["ready_to_use"] is True
    assert body["calling"]["requires_line_selection"] is False


def test_a_line_awaiting_its_number_is_distinguishable_from_one_with_none(
    api: FastAPI, client: TestClient
) -> None:
    """Two lines with no number, for two entirely different reasons.

    The discriminator is the plan's **number policy**, not the carrier line's
    voice flag: a voice-capable line sold on a data-only plan is still a plan
    with no number, and using voice as a proxy would report it as waiting for
    one forever.
    """
    with api.state.session_factory() as session:
        holder = _user(session, "0002")
        waiting = _line(api, session, holder, with_number=False)
        data_only = _line(
            api,
            session,
            holder,
            with_number=False,
            includes_number=False,
            # Deliberately voice-capable. A proxy on this flag gets it wrong.
            voice_enabled=True,
        )
    headers = _auth(api, holder)

    waiting_body = client.get(f"/v1/me/lines/{waiting.id}", headers=headers).json()
    data_body = client.get(f"/v1/me/lines/{data_only.id}", headers=headers).json()

    assert waiting_body["number_status"] == "pending"
    assert data_body["number_status"] == "not_included"


def test_the_internet_dialer_is_off_and_says_why(
    api: FastAPI, client: TestClient
) -> None:
    """V04 is not accepted, so the app must not offer an internet dialer."""
    with api.state.session_factory() as session:
        holder = _user(session)
        entitlement = _line(api, session, holder)
    headers = _auth(api, holder)

    calling = client.get(f"/v1/me/lines/{entitlement.id}", headers=headers).json()[
        "calling"
    ]

    assert calling["internet_dialer_enabled"] is False
    assert calling["internet_dialer_reason"] == "v04_not_accepted"


def test_a_top_up_extension_keeps_an_otherwise_expired_line_usable(
    api: FastAPI, client: TestClient
) -> None:
    """The customer has paid to keep the line, so it is not expired.

    Reading `entitlements.expires_at` directly would report this line as dead
    while its owner has already bought the extension — and `ready_to_use` and
    `usage.expired` would disagree with each other in the same response.
    """
    with api.state.session_factory() as session:
        holder = _user(session, "0011")
        entitlement = _line(
            api,
            session,
            holder,
            installation_state=InstallationState.INSTALLED,
            expires_at=NOW - timedelta(days=1),
        )
        _top_up(
            session,
            entitlement,
            state=TopUpState.APPLIED,
            data_bytes=1_073_741_824,
            extends_days=7,
        )
    headers = _auth(api, holder)

    body = client.get(f"/v1/me/lines/{entitlement.id}", headers=headers).json()

    assert body["usage"]["expired"] is False
    assert body["ready_to_use"] is True
    listed = client.get("/v1/me/lines", headers=headers).json()["lines"]
    assert listed[0]["expired"] is False


# --- ownership --------------------------------------------------------------


def test_another_accounts_line_is_not_found_rather_than_forbidden(
    api: FastAPI, client: TestClient
) -> None:
    """404, not 403. "Is not yours" and "does not exist" must look the same.

    Chunk 19's review found a quote id crossing an account boundary; the same
    class of defect on a line would expose installation material, which cannot
    be rotated after it leaks.
    """
    with api.state.session_factory() as session:
        holder = _user(session, "0003")
        intruder = _user(session, "0004")
        entitlement = _line(api, session, holder)
    headers = _auth(api, intruder)

    response = client.get(f"/v1/me/lines/{entitlement.id}", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"] == "line_not_found"


def test_lines_lists_only_what_this_account_holds(
    api: FastAPI, client: TestClient
) -> None:
    with api.state.session_factory() as session:
        holder = _user(session, "0005")
        other = _user(session, "0006")
        mine = _line(api, session, holder)
        _line(api, session, other)
    headers = _auth(api, holder)

    body = client.get("/v1/me/lines", headers=headers).json()

    assert [line["entitlement_id"] for line in body["lines"]] == [str(mine.id)]


def test_every_line_route_requires_a_session(client: TestClient) -> None:
    identifier = uuid4()
    for method, path, body in (
        ("GET", "/v1/me/lines", None),
        ("GET", f"/v1/me/lines/{identifier}", None),
        ("POST", f"/v1/me/lines/{identifier}/installation/grant", {}),
        (
            "POST",
            f"/v1/me/lines/{identifier}/installation/redeem",
            {"grant_token": "anything"},
        ),
        (
            "POST",
            f"/v1/me/lines/{identifier}/installation/confirm",
            {"installed": True},
        ),
    ):
        response = client.request(method, path, json=body)
        # Rejected before the path is resolved, so an unauthenticated caller
        # cannot use a 404 to learn whether an entitlement id exists.
        assert response.status_code in (401, 403), path


# --- installation material --------------------------------------------------


def test_reading_a_line_never_returns_the_profile(
    api: FastAPI, client: TestClient
) -> None:
    """The property that makes the read screen safe to poll."""
    with api.state.session_factory() as session:
        holder = _user(session)
        entitlement = _line(api, session, holder)
    headers = _auth(api, holder)

    response = client.get(f"/v1/me/lines/{entitlement.id}", headers=headers)

    assert LPA not in response.text
    assert "LPA:" not in response.text
    assert response.json()["installation"]["credential_available"] is True


def test_a_grant_authorizes_a_delivery_and_carries_no_profile(
    api: FastAPI, client: TestClient
) -> None:
    with api.state.session_factory() as session:
        holder = _user(session)
        entitlement = _line(api, session, holder)
    headers = _auth(api, holder)

    response = client.post(
        f"/v1/me/lines/{entitlement.id}/installation/grant", headers=headers
    )

    assert response.status_code == 201
    assert LPA not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["one_time_use"] is True
    assert response.json()["delivery_count"] == 0


def test_a_grant_is_spent_exactly_once(api: FastAPI, client: TestClient) -> None:
    with api.state.session_factory() as session:
        holder = _user(session)
        entitlement = _line(api, session, holder)
    headers = _auth(api, holder)
    token = client.post(
        f"/v1/me/lines/{entitlement.id}/installation/grant", headers=headers
    ).json()["grant_token"]

    first = client.post(
        f"/v1/me/lines/{entitlement.id}/installation/redeem",
        headers=headers,
        json={"grant_token": token},
    )
    second = client.post(
        f"/v1/me/lines/{entitlement.id}/installation/redeem",
        headers=headers,
        json={"grant_token": token},
    )

    assert first.status_code == 200
    assert first.json()["lpa"] == LPA
    assert first.headers["Cache-Control"] == "no-store"
    assert second.status_code == 409
    assert second.json()["error"] == "grant_not_redeemable"
    assert LPA not in second.text


def test_a_grant_cannot_be_spent_by_another_account(
    api: FastAPI, client: TestClient
) -> None:
    with api.state.session_factory() as session:
        holder = _user(session, "0007")
        intruder = _user(session, "0008")
        entitlement = _line(api, session, holder)
        stolen = _line(api, session, intruder)
    holder_headers = _auth(api, holder)
    intruder_headers = _auth(api, intruder)
    token = client.post(
        f"/v1/me/lines/{entitlement.id}/installation/grant", headers=holder_headers
    ).json()["grant_token"]

    # Against the holder's line, with the wrong session: the line is not theirs.
    against_holders_line = client.post(
        f"/v1/me/lines/{entitlement.id}/installation/redeem",
        headers=intruder_headers,
        json={"grant_token": token},
    )
    # Against their own line, with a token for somebody else's: the token is not
    # redeemable, and the answer is identical to an expired one.
    against_own_line = client.post(
        f"/v1/me/lines/{stolen.id}/installation/redeem",
        headers=intruder_headers,
        json={"grant_token": token},
    )

    assert against_holders_line.status_code == 404
    assert against_own_line.status_code == 409
    assert LPA not in against_holders_line.text
    assert LPA not in against_own_line.text


def test_an_already_delivered_profile_warns_rather_than_hiding_itself(
    api: FastAPI, client: TestClient
) -> None:
    """A one-time code that has been shown once is still the only one there is.

    The customer must be told it has already been revealed — refusing outright
    would strand somebody whose screen locked mid-scan, and saying nothing would
    hide that the profile may already be installed elsewhere.
    """
    with api.state.session_factory() as session:
        holder = _user(session)
        entitlement = _line(api, session, holder)
    headers = _auth(api, holder)
    token = client.post(
        f"/v1/me/lines/{entitlement.id}/installation/grant", headers=headers
    ).json()["grant_token"]
    client.post(
        f"/v1/me/lines/{entitlement.id}/installation/redeem",
        headers=headers,
        json={"grant_token": token},
    )

    installation = client.get(
        f"/v1/me/lines/{entitlement.id}", headers=headers
    ).json()["installation"]

    assert installation["delivery_count"] == 1
    assert installation["credential_available"] is True
    assert installation["credential_unavailable_reason"] == "already_delivered"


def test_a_one_time_profile_never_offers_a_reinstall(
    api: FastAPI, client: TestClient
) -> None:
    """Telnyx documents that a downloaded profile cannot be re-downloaded.

    A replacement device needs a new purchase. A "reinstall" button would be
    offering something the supplier cannot do, which is worse than saying so.
    """
    with api.state.session_factory() as session:
        holder = _user(session)
        entitlement = _line(api, session, holder)
    headers = _auth(api, holder)

    installation = client.get(
        f"/v1/me/lines/{entitlement.id}", headers=headers
    ).json()["installation"]

    assert installation["reinstall_available"] is False
    assert installation["reinstall_blocked_reason"] == "one_time_profile"


def test_a_line_whose_profile_is_not_issued_says_so(
    api: FastAPI, client: TestClient
) -> None:
    with api.state.session_factory() as session:
        holder = _user(session)
        entitlement = _line(api, session, holder, with_credential=False)
    headers = _auth(api, holder)

    view = client.get(f"/v1/me/lines/{entitlement.id}", headers=headers).json()
    grant = client.post(
        f"/v1/me/lines/{entitlement.id}/installation/grant", headers=headers
    )

    assert view["installation"]["credential_available"] is False
    assert view["installation"]["credential_unavailable_reason"] == "profile_not_issued"
    assert grant.status_code == 409
    assert grant.json()["error"] == "profile_not_issued"


def test_a_token_for_one_line_cannot_be_spent_against_another(
    api: FastAPI, client: TestClient
) -> None:
    """Two lines, one account, and a token that belongs to the first.

    The vault authorizes by *holder*, and this customer holds both — so the
    token passes the vault's own check and would spend line A's profile while
    the caller asked about line B.

    **Line B is delivered once first, deliberately.** That is what makes this a
    regression test rather than a restatement: a guard that compared line B's
    delivery count against a fixed zero would pass here, hand back line A's
    profile under line B's id, and burn a one-time eSIM nobody asked about. The
    route compares the count it read before against the one after instead.
    """
    with api.state.session_factory() as session:
        holder = _user(session, "0009")
        first = _line(api, session, holder)
        second = _line(api, session, holder)
    headers = _auth(api, holder)

    # Line B, delivered honestly. Its count is now 1, not 0.
    own_token = client.post(
        f"/v1/me/lines/{second.id}/installation/grant", headers=headers
    ).json()["grant_token"]
    client.post(
        f"/v1/me/lines/{second.id}/installation/redeem",
        headers=headers,
        json={"grant_token": own_token},
    )

    token_for_first = client.post(
        f"/v1/me/lines/{first.id}/installation/grant", headers=headers
    ).json()["grant_token"]
    crossed = client.post(
        f"/v1/me/lines/{second.id}/installation/redeem",
        headers=headers,
        json={"grant_token": token_for_first},
    )

    assert crossed.status_code == 409
    assert crossed.json()["error"] == "grant_not_redeemable"
    assert LPA not in crossed.text

    # Line A's one-time profile survived the attempt: raising before the commit
    # rolls back the delivery the vault had already recorded against it.
    first_view = client.get(f"/v1/me/lines/{first.id}", headers=headers).json()
    assert first_view["installation"]["delivery_count"] == 0
    honest = client.post(
        f"/v1/me/lines/{first.id}/installation/redeem",
        headers=headers,
        json={"grant_token": token_for_first},
    )
    assert honest.status_code == 200
    assert honest.json()["lpa"] == LPA


def test_a_second_delivery_of_the_same_line_still_counts_correctly(
    api: FastAPI, client: TestClient
) -> None:
    """The case a fixed zero-check would have got wrong.

    Once a line has been delivered, its `delivery_count` is no longer zero, so
    the cross-line guard has to compare a delta rather than a constant.
    """
    with api.state.session_factory() as session:
        holder = _user(session, "0010")
        entitlement = _line(api, session, holder)
    headers = _auth(api, holder)

    for expected in (1, 2):
        token = client.post(
            f"/v1/me/lines/{entitlement.id}/installation/grant", headers=headers
        ).json()["grant_token"]
        response = client.post(
            f"/v1/me/lines/{entitlement.id}/installation/redeem",
            headers=headers,
            json={"grant_token": token},
        )
        assert response.status_code == 200
        assert response.json()["delivery_count"] == expected


# --- reporting what the device did ------------------------------------------


def test_only_the_device_can_report_an_installation(
    api: FastAPI, client: TestClient
) -> None:
    """And the response immediately shows activation is a separate wait."""
    with api.state.session_factory() as session:
        holder = _user(session)
        entitlement = _line(
            api, session, holder, activation_state=ActivationState.PENDING
        )
    headers = _auth(api, holder)

    before = client.get(f"/v1/me/lines/{entitlement.id}", headers=headers).json()
    after = client.post(
        f"/v1/me/lines/{entitlement.id}/installation/confirm",
        headers=headers,
        json={"installed": True},
    )

    assert before["installation"]["state"] == "not_installed"
    assert after.status_code == 200
    assert after.json()["installation"]["state"] == "installed"
    assert after.json()["installation"]["installed_at"] is not None
    # Installing did not activate anything.
    assert after.json()["line"]["activation_state"] == "pending"
    assert after.json()["ready_to_use"] is False


def test_a_failed_installation_is_recorded_as_failed(
    api: FastAPI, client: TestClient
) -> None:
    """Reporting `false` must not leave the record saying installed.

    Otherwise a customer whose install failed is told their line is ready, and
    the support agent reading the row has to disbelieve it.
    """
    with api.state.session_factory() as session:
        holder = _user(session)
        entitlement = _line(
            api,
            session,
            holder,
            installation_state=InstallationState.INSTALLED,
        )
    headers = _auth(api, holder)

    response = client.post(
        f"/v1/me/lines/{entitlement.id}/installation/confirm",
        headers=headers,
        json={"installed": False},
    )

    assert response.status_code == 200
    assert response.json()["installation"]["state"] == "not_installed"
    assert response.json()["installation"]["installed_at"] is None
    assert response.json()["ready_to_use"] is False
