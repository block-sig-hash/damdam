"""US-35 chunk 15 — line lifecycle and installation material, on PostgreSQL.

The invariant the chunk turns on: **an unknown supplier outcome never buys a
second line.** `AGENTS.md` calls accepted-but-response-lost the single most
expensive failure mode in this product, and strict TDD is required for it, so it
is the first thing tested here and it is tested at the adapter boundary rather
than against a fake that agrees with itself.

The rest are the ways a connectivity system lies to a customer: telling them a
profile is installed because a QR code exists, telling them a line is attached
because it was activated, telling them a suspension happened because a 202 came
back, and handing out a one-time-use activation code more than once.

PostgreSQL, not SQLite: the open-action guard is a partial unique index and the
grant redemption is a `SELECT … FOR UPDATE`, and neither means anything without
a server that enforces them under concurrency.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app import model_registry  # noqa: F401  -- completes SQLModel.metadata
from app.auth.models import Platform, User
from app.catalog.models import LegalEntity, Product, ProductAllowance, ProductKind
from app.connectivity.contract import (
    ActivationCredential,
    AdapterCapabilities,
    Capability,
    ConnectivityError,
    ConnectivityOutcomeUnknown,
    ProviderAction,
    ProviderLine,
    ProviderLineState,
    ProvisionResult,
)
from app.connectivity.credentials import CredentialError, CredentialVault
from app.connectivity.models import (
    ActivationState,
    AssignedNumber,
    CarrierLine,
    CarrierLineAction,
    CredentialGrant,
    Entitlement,
    EsimActivationCredential,
    EsimInstallation,
    InstallationState,
    LineActionKind,
    LineActionState,
    NetworkState,
)
from app.connectivity.service import (
    ConnectivityService,
    ConnectivityServiceError,
    operation_reference,
)
from app.fulfilment.models import AttemptOutcome, SupplierAttempt
from app.fulfilment.service import FulfilmentService
from app.orders.models import Order, OrderItem, ProvisioningState

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="line lifecycle races and partial indexes require PostgreSQL",
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
KEY = b"0123456789abcdef0123456789abcdef"
TABLES = (
    "esim_credential_grants, esim_activation_credentials, carrier_line_actions, "
    "assigned_numbers, carrier_lines, esim_installations, entitlements, "
    "supplier_attempts, outbox_messages, order_items, orders, "
    "product_allowances, products, legal_entities, users"
)


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: float) -> None:
        self.value += timedelta(**kwargs)


# --- a fake carrier ---------------------------------------------------------
#
# Deliberately a *fake carrier*, not a fake adapter: it implements
# `ConnectivityAdapter` and is driven through the same surface Telnyx is. The
# Telnyx-specific parsing has its own tests; what needs a supplier here is the
# service's behaviour when one goes wrong, and no sandbox produces a lost
# response when you ask it to.


class FakeCarrier:
    name = "fakecarrier"

    def __init__(self, capabilities: frozenset[Capability] | None = None) -> None:
        self.capability_set = capabilities or frozenset(
            {Capability.DATA, Capability.ACTIVATION_CREDENTIAL, Capability.SUSPENSION}
        )
        self.provision_calls: list[UUID] = []
        self.reconcile_calls: list[UUID] = []
        self.lose_response = False
        self.refuse: str | None = None
        self.reconcile_answer: ProvisionResult | None = None
        self.reconcile_returns_none = False
        self.lines: dict[str, ProviderLine] = {}
        self.actions: dict[str, ProviderAction] = {}
        self.next_number: str | None = None
        self.activation_code = "LPA:1$smdp.example$FAKE"
        self.action_settles = False

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supported=self.capability_set,
            undocumented={
                capability.value: "not verified for this fake"
                for capability in Capability
                if capability not in self.capability_set
            },
        )

    def provision(
        self, operation: UUID, quantity: int, options: dict[str, Any] | None = None
    ) -> ProvisionResult:
        self.provision_calls.append(operation)
        if self.lose_response:
            raise ConnectivityOutcomeUnknown("the response never arrived")
        if self.refuse:
            raise ConnectivityError("refused", self.refuse)
        lines = tuple(
            self._line(f"line-{operation}-{index}") for index in range(quantity)
        )
        for line in lines:
            self.lines[line.provider_reference] = line
        return ProvisionResult(lines=lines)

    def reconcile(self, operation: UUID, quantity: int) -> ProvisionResult | None:
        self.reconcile_calls.append(operation)
        if self.reconcile_returns_none:
            return None
        return self.reconcile_answer

    def fetch_line(self, provider_reference: str) -> ProviderLine | None:
        return self.lines.get(provider_reference)

    def fetch_activation_credential(
        self, provider_reference: str
    ) -> ActivationCredential:
        self.capabilities().require(Capability.ACTIVATION_CREDENTIAL)
        return ActivationCredential(secret=self.activation_code, one_time_use=True)

    def enable_voice(self, provider_reference: str) -> ProviderAction:
        self.capabilities().require(Capability.NATIVE_VOICE)
        return self._action("enable_voice")

    def assigned_number(self, provider_reference: str) -> str | None:
        self.capabilities().require(Capability.NUMBER_ASSIGNMENT)
        return self.next_number

    def set_state(
        self, provider_reference: str, target: ProviderLineState
    ) -> ProviderAction:
        self.capabilities().require(Capability.SUSPENSION)
        return self._action(target.value)

    def fetch_action(self, provider_action_reference: str) -> ProviderAction | None:
        return self.actions.get(provider_action_reference)

    def settle(
        self, reference: str, succeeded: bool, reason: str | None = None
    ) -> None:
        self.actions[reference] = ProviderAction(
            provider_reference=reference,
            succeeded=succeeded,
            settled=True,
            provider_status="completed" if succeeded else "failed",
            reason=reason,
        )

    def _line(self, reference: str, **overrides: Any) -> ProviderLine:
        defaults: dict[str, Any] = {
            "provider_reference": reference,
            "state": ProviderLineState.PROVISIONED,
            "provider_status": "standby",
            "iccid": f"893104101065437893{reference[-2:]}",
            "installation_released": True,
            "observed_at": NOW,
        }
        defaults.update(overrides)
        return ProviderLine(**defaults)

    def _action(self, kind: str) -> ProviderAction:
        reference = f"action-{kind}-{len(self.actions) + 1}"
        action = ProviderAction(
            provider_reference=reference,
            succeeded=True if self.action_settles else None,
            settled=self.action_settles,
            provider_status="completed" if self.action_settles else "in-progress",
        )
        self.actions[reference] = action
        return action


# --- fixtures ---------------------------------------------------------------


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
def clock() -> Clock:
    return Clock()


@pytest.fixture
def vault(clock: Clock) -> CredentialVault:
    return CredentialVault(KEY, "test-key-1", clock=clock)


@pytest.fixture
def service(clock: Clock, vault: CredentialVault) -> ConnectivityService:
    return ConnectivityService(FulfilmentService(clock=clock), vault, clock=clock)


@pytest.fixture
def carrier() -> FakeCarrier:
    return FakeCarrier()


def _order_item(
    session: Session,
    data_bytes: int = 5_000_000_000,
    voice_seconds: int = 3600,
    validity_days: int | None = 30,
    *,
    include_allowance: bool = True,
) -> OrderItem:
    entity = LegalEntity(code=f"E{uuid4().hex[:6]}", name="Seller", country="NG")
    product = Product(
        sku=f"sku-{uuid4().hex[:8]}",
        name="Global 5GB",
        kind=ProductKind.BUNDLE,
    )
    payer = User(
        phone_number=f"+23488{uuid4().int % 10**8:08d}",
        first_name="payer",
        platform=Platform.ANDROID,
    )
    session.add_all([entity, product, payer])
    session.flush()
    if include_allowance:
        session.add(
            ProductAllowance(
                product_id=product.id,
                data_bytes=data_bytes,
                voice_seconds=voice_seconds,
                validity_days=validity_days,
                created_at=NOW,
            )
        )
    order = Order(
        reference=f"ord-{uuid4().hex[:12]}",
        seller_legal_entity_id=entity.id,
        payer_user_id=payer.id,
        currency="NGN",
        total_amount=Decimal("5000.00"),
    )
    session.add(order)
    session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        recipient_user_id=payer.id,
        unit_currency="NGN",
        unit_amount=Decimal("5000.00"),
    )
    session.add(item)
    session.flush()
    return item


# --- the expensive failure --------------------------------------------------


def test_a_lost_response_never_provisions_twice(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    """The attempt is recorded, the response is lost, and nothing buys again.

    The item lands in `OUTCOME_UNKNOWN` — not `FAILED` — because a failure looks
    retryable and the retry is the second purchase.
    """
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()  # before the call, always

    carrier.lose_response = True
    service.dispatch_provisioning(session, attempt, carrier)
    session.commit()

    session.refresh(item)
    session.refresh(attempt)
    assert attempt.outcome is AttemptOutcome.OUTCOME_UNKNOWN
    assert item.provisioning_state is ProvisioningState.OUTCOME_UNKNOWN
    assert len(carrier.provision_calls) == 1
    assert session.exec(select(CarrierLine)).all() == []


def test_a_second_attempt_is_refused_while_the_first_is_unresolved(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    """The database guard, not just the service one.

    `ux_supplier_attempts_live_item` allows one live attempt per item. An
    unknown outcome is live: the supplier may still be holding it.
    """
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    carrier.lose_response = True
    service.dispatch_provisioning(session, attempt, carrier)
    session.commit()

    again = service.begin_provisioning(session, item, carrier)
    assert again.id == attempt.id

    session.add(
        SupplierAttempt(
            order_item_id=item.id,
            provider=carrier.name,
            idempotency_key="hand-written",
            attempt_number=99,
            outcome=AttemptOutcome.IN_FLIGHT,
            requested_at=NOW,
            created_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_reconciliation_adopts_the_line_the_purchase_actually_created(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    """A recovered order is indistinguishable from one that never lost anything."""
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    carrier.lose_response = True
    service.dispatch_provisioning(session, attempt, carrier)
    session.commit()

    carrier.lose_response = False
    carrier.reconcile_answer = ProvisionResult(
        lines=(carrier._line("line-recovered"),)
    )
    resolved = service.reconcile_provisioning(session, attempt, carrier)
    session.commit()

    assert resolved.outcome is AttemptOutcome.ACCEPTED
    assert carrier.reconcile_calls == [operation_reference(attempt.idempotency_key)]
    line = session.exec(select(CarrierLine)).one()
    assert line.carrier_line_reference == "line-recovered"
    session.refresh(item)
    assert item.provisioning_state is ProvisioningState.PROVISIONED
    # And nothing was bought to get there.
    assert len(carrier.provision_calls) == 1


def test_an_unanswerable_reconciliation_stops_for_a_human(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    """Guessing costs money one way and service the other."""
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    carrier.lose_response = True
    service.dispatch_provisioning(session, attempt, carrier)
    session.commit()

    carrier.reconcile_returns_none = True
    resolved = service.reconcile_provisioning(session, attempt, carrier)
    session.commit()

    assert resolved.outcome is AttemptOutcome.HELD_FOR_REVIEW
    assert resolved.review_reason is not None
    assert session.exec(select(CarrierLine)).all() == []


def test_reconciliation_against_another_supplier_is_refused(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    """`AGENTS.md`: an unknown outcome never fails over to another vendor."""
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    carrier.lose_response = True
    service.dispatch_provisioning(session, attempt, carrier)
    session.commit()

    other = FakeCarrier()
    other.name = "someone-else"
    with pytest.raises(Exception, match="wrong_supplier|not someone-else"):
        service.reconcile_provisioning(session, attempt, other)


def test_a_partial_delivery_is_unknown_not_success(
    session: Session, service: ConnectivityService
) -> None:
    """Two of three lines is not two-thirds of a fulfilled order.

    Topping up the shortfall is a new decision. Retrying the attempt would ask
    a supplier that already honoured part of it to honour all of it again.
    """
    from app.connectivity.service import ConnectivitySupplierClient

    class ShortCarrier(FakeCarrier):
        def provision(
            self, operation: UUID, quantity: int, options: Any = None
        ) -> ProvisionResult:
            self.provision_calls.append(operation)
            return ProvisionResult(
                lines=(self._line("line-1"),), errors=("70001",)
            )

    item = _order_item(session)
    carrier = ShortCarrier()
    service_ = ConnectivityService(FulfilmentService(clock=Clock()), clock=Clock())
    attempt = service_.begin_provisioning(session, item, carrier)
    session.commit()

    client = ConnectivitySupplierClient(carrier, quantity=3)
    service_.dispatch_provisioning(session, attempt, carrier)  # quantity 1 path
    session.rollback()

    with pytest.raises(Exception, match="shortfall"):
        client.provision(attempt.idempotency_key, {})


def test_a_definite_refusal_is_final_and_re_orderable(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    """A refusal frees the item for a *new* attempt with a new key.

    The distinction from an unknown outcome is the whole design: this one is
    safe to try again, and it gets a different idempotency key so the supplier
    does not de-duplicate the new purchase against the old refusal.
    """
    item = _order_item(session)
    first = service.begin_provisioning(session, item, carrier)
    session.commit()
    carrier.refuse = "no inventory in that region"
    service.dispatch_provisioning(session, first, carrier)
    session.commit()

    session.refresh(item)
    assert item.provisioning_state is ProvisioningState.FAILED

    carrier.refuse = None
    second = service.begin_provisioning(session, item, carrier)
    session.commit()
    assert second.id != first.id
    assert second.idempotency_key != first.idempotency_key
    assert operation_reference(second.idempotency_key) != operation_reference(
        first.idempotency_key
    )


# --- the four separate states ------------------------------------------------


def test_provisioning_a_line_does_not_install_or_attach_it(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    """The chunk's second requirement, in one assertion each.

    A supplier releasing a profile for download is not a handset holding it,
    and a provisioned line is not an attached one.
    """
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    session.commit()

    line = session.exec(select(CarrierLine)).one()
    installation = session.exec(select(EsimInstallation)).one()

    assert line.activation_state is ActivationState.PENDING
    assert line.network_state is NetworkState.UNKNOWN
    assert line.network_state_observed_at is None
    # The supplier said the profile was released for download...
    assert installation.profile_released_at == NOW
    # ...which is not an installation.
    assert installation.installation_state is InstallationState.NOT_INSTALLED
    assert installation.installed_at is None


def test_only_a_device_report_marks_a_profile_installed(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    installation = session.exec(select(EsimInstallation)).one()

    service.record_device_installation(session, installation)
    session.commit()

    session.refresh(installation)
    assert installation.installation_state is InstallationState.INSTALLED
    assert installation.installed_at == NOW
    # Still nothing claimed about the network.
    line = session.exec(select(CarrierLine)).one()
    assert line.network_state is NetworkState.UNKNOWN


def test_activating_a_line_never_claims_it_is_attached(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    """The lie this column exists to prevent.

    A carrier telling us a line is enabled is telling us about its own records.
    Reporting the handset as attached on that basis is how a support agent
    tells somebody their phone works when it does not.
    """
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    line = session.exec(select(CarrierLine)).one()

    carrier.lines[line.carrier_line_reference] = ProviderLine(
        provider_reference=line.carrier_line_reference,
        state=ProviderLineState.ACTIVE,
        provider_status="enabled",
        observed_at=NOW,
    )
    service.refresh_line(session, line, carrier)
    session.commit()

    session.refresh(line)
    assert line.activation_state is ActivationState.ACTIVE
    assert line.network_state is NetworkState.UNKNOWN

    service.record_network_observation(session, line, attached=True)
    session.commit()
    session.refresh(line)
    assert line.network_state is NetworkState.ATTACHED
    assert line.network_state_observed_at == NOW


def test_a_transitional_status_does_not_move_the_line(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    """`enabling` is not `enabled`, and the next poll will say so anyway."""
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    line = session.exec(select(CarrierLine)).one()
    service.settle_action(
        session,
        service.request_action(session, line, LineActionKind.ACTIVATE),
        line,
        succeeded=True,
    )
    session.commit()
    assert line.activation_state is ActivationState.ACTIVE

    carrier.lines[line.carrier_line_reference] = ProviderLine(
        provider_reference=line.carrier_line_reference,
        state=ProviderLineState.TRANSITIONING,
        provider_status="setting_standby",
        observed_at=NOW,
    )
    service.refresh_line(session, line, carrier)
    session.commit()

    session.refresh(line)
    assert line.activation_state is ActivationState.ACTIVE
    assert line.provider_status == "setting_standby"


def test_a_terminated_line_is_not_resurrected_by_a_supplier_read(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    line = session.exec(select(CarrierLine)).one()
    line.activation_state = ActivationState.TERMINATED
    session.add(line)
    session.commit()

    carrier.lines[line.carrier_line_reference] = ProviderLine(
        provider_reference=line.carrier_line_reference,
        state=ProviderLineState.ACTIVE,
        provider_status="enabled",
        observed_at=NOW,
    )
    service.refresh_line(session, line, carrier)
    session.commit()
    session.refresh(line)
    assert line.activation_state is ActivationState.TERMINATED


def test_a_carrier_restriction_is_not_our_suspension(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    """A data cap stops the line, but resuming it is not ours to do.

    The provider status survives so chunk 17 can tell the two apart: only
    raising the limit clears `data_limit_exceeded`, and a resume request would
    be refused.
    """
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    line = session.exec(select(CarrierLine)).one()

    carrier.lines[line.carrier_line_reference] = ProviderLine(
        provider_reference=line.carrier_line_reference,
        state=ProviderLineState.RESTRICTED,
        provider_status="data_limit_exceeded",
        observed_at=NOW,
    )
    service.refresh_line(session, line, carrier)
    session.commit()

    session.refresh(line)
    assert line.activation_state is ActivationState.SUSPENDED
    assert line.provider_status == "data_limit_exceeded"


# --- correlation -------------------------------------------------------------


def test_one_profile_line_and_number_correlate(
    session: Session, service: ConnectivityService
) -> None:
    """The chunk's acceptance criterion, against a fixture supplier.

    Live evidence needs an account and D1 has not produced one; this proves the
    correlation our side of the boundary and says nothing about Telnyx.
    """
    carrier = FakeCarrier(
        frozenset(
            {
                Capability.DATA,
                Capability.ACTIVATION_CREDENTIAL,
                Capability.NUMBER_ASSIGNMENT,
                Capability.SUSPENSION,
            }
        )
    )
    carrier.next_number = "+2348012345678"
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    line = session.exec(select(CarrierLine)).one()
    installation = session.exec(select(EsimInstallation)).one()
    service.fetch_and_store_credential(session, installation, line, carrier)
    number = service.assign_number(session, line, carrier, country="NG")
    session.commit()

    entitlement = session.exec(select(Entitlement)).one()
    credential = session.exec(select(EsimActivationCredential)).one()

    assert entitlement.order_item_id == item.id
    assert installation.entitlement_id == entitlement.id
    assert line.entitlement_id == entitlement.id
    assert number is not None
    assert number.carrier_line_id == line.id
    assert number.e164 == "+2348012345678"
    assert credential.esim_installation_id == installation.id


def test_the_entitlement_comes_from_the_catalog_not_the_caller(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    """A grant invented at fulfilment time is a grant nobody agreed to."""
    item = _order_item(session, data_bytes=5_000_000_000, voice_seconds=1800)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    session.commit()

    entitlement = session.exec(select(Entitlement)).one()
    assert entitlement.data_bytes_total == 5_000_000_000
    assert entitlement.voice_seconds_total == 1800
    assert entitlement.expires_at == NOW + timedelta(days=30)


def test_a_published_product_allowance_cannot_be_rewritten_or_deleted(
    session: Session,
) -> None:
    """The product id is the order's allowance snapshot boundary.

    Fulfilment may happen long after checkout.  If the one allowance row for a
    product can change in between, the customer receives today's package rather
    than the package they bought.
    """
    item = _order_item(session, data_bytes=5_000_000_000)
    session.commit()

    with pytest.raises(DBAPIError, match="product allowances are immutable"):
        session.exec(
            text(
                "UPDATE product_allowances SET data_bytes = 1 "
                "WHERE product_id = :product_id"
            ),
            params={"product_id": item.product_id},
        )
        session.commit()
    session.rollback()

    with pytest.raises(DBAPIError, match="product allowances are immutable"):
        session.exec(
            text("DELETE FROM product_allowances WHERE product_id = :product_id"),
            params={"product_id": item.product_id},
        )
        session.commit()
    session.rollback()


def test_one_supplier_line_cannot_fulfil_two_order_items(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    first = _order_item(session)
    second = _order_item(session)
    provider_line = carrier._line("shared-provider-line")

    service.adopt_line(session, first, provider_line, carrier)
    with pytest.raises(ConnectivityServiceError) as caught:
        service.adopt_line(session, second, provider_line, carrier)

    assert caught.value.code == "provider_line_already_assigned"


def test_a_product_with_no_recorded_allowance_refuses_to_provision(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    item = _order_item(session, include_allowance=False)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    with pytest.raises(ConnectivityServiceError) as caught:
        service.dispatch_provisioning(session, attempt, carrier)
    assert caught.value.code == "product_allowance_missing"


def test_adopting_the_same_line_twice_creates_one_row(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    """A dispatch and a reconciliation can both see the same line."""
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    session.commit()
    line = session.exec(select(CarrierLine)).one()

    service.adopt_line(
        session,
        item,
        carrier.lines[line.carrier_line_reference],
        carrier,
    )
    session.commit()
    assert len(session.exec(select(CarrierLine)).all()) == 1
    assert len(session.exec(select(Entitlement)).all()) == 1


def test_a_reassigned_number_releases_the_old_row(
    session: Session, service: ConnectivityService
) -> None:
    """History survives, because an old assignment explains an old call.

    `ux_assigned_numbers_live_e164` is over live assignments only, so the same
    number can legitimately be assigned again later — and the released row has
    to remain to say who held it when a call was billed.
    """
    carrier = FakeCarrier(
        frozenset(
            {
                Capability.DATA,
                Capability.NUMBER_ASSIGNMENT,
                Capability.SUSPENSION,
            }
        )
    )
    carrier.next_number = "+2348011111111"
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    line = session.exec(select(CarrierLine)).one()
    first = service.assign_number(session, line, carrier, country="NG")
    session.commit()

    carrier.next_number = "+2348022222222"
    second = service.assign_number(session, line, carrier, country="NG")
    session.commit()

    assert first is not None and second is not None
    session.refresh(first)
    assert first.released_at == NOW
    assert second.released_at is None
    assert len(session.exec(select(AssignedNumber)).all()) == 2


# --- asynchronous lifecycle actions ------------------------------------------


def test_a_202_makes_an_action_pending_not_confirmed(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    """The line has not moved yet, and the app must not say it has."""
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    line = session.exec(select(CarrierLine)).one()
    line.activation_state = ActivationState.ACTIVE
    session.add(line)

    action = service.request_action(session, line, LineActionKind.SUSPEND)
    assert action.state is LineActionState.REQUESTED
    assert action.provider_action_reference is None

    service.dispatch_action(session, action, line, carrier)
    session.commit()

    session.refresh(action)
    session.refresh(line)
    assert action.state is LineActionState.PENDING
    assert action.provider_action_reference is not None
    assert action.settled_at is None
    assert line.activation_state is ActivationState.ACTIVE  # not yet suspended


def test_a_confirmed_action_moves_the_line_and_a_failed_one_does_not(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    line = session.exec(select(CarrierLine)).one()
    line.activation_state = ActivationState.ACTIVE
    session.add(line)

    action = service.request_action(session, line, LineActionKind.SUSPEND)
    service.dispatch_action(session, action, line, carrier)
    reference = action.provider_action_reference
    assert reference is not None
    carrier.settle(reference, succeeded=False, reason="carrier said no")
    service.poll_action(session, action, line, carrier)
    session.commit()

    session.refresh(action)
    session.refresh(line)
    assert action.state is LineActionState.FAILED
    assert action.settled_at == NOW
    assert action.failure_reason == "carrier said no"
    # A suspension that did not happen has not happened.
    assert line.activation_state is ActivationState.ACTIVE

    second = service.request_action(session, line, LineActionKind.SUSPEND)
    service.dispatch_action(session, second, line, carrier)
    reference = second.provider_action_reference
    assert reference is not None
    carrier.settle(reference, succeeded=True)
    service.poll_action(session, second, line, carrier)
    session.commit()

    session.refresh(line)
    assert line.activation_state is ActivationState.SUSPENDED
    # Suspending does not observe the handset detaching.
    assert line.network_state is NetworkState.UNKNOWN


def test_a_line_may_have_only_one_open_action(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    """A suspend racing a resume has no defined answer."""
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    line = session.exec(select(CarrierLine)).one()
    session.commit()

    service.request_action(session, line, LineActionKind.SUSPEND)
    session.commit()
    with pytest.raises(ConnectivityServiceError) as caught:
        service.request_action(session, line, LineActionKind.RESUME)
    assert caught.value.code == "line_action_conflict"


def test_the_open_action_guard_holds_under_concurrency(
    engine, session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    """The partial unique index, not the service read.

    Two workers reading "no open action" and both writing one is the classic
    race, and only the database can arbitrate it.
    """
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    session.commit()
    line_id = session.exec(select(CarrierLine)).one().id

    barrier = Barrier(2)

    def suspend() -> str:
        with Session(engine) as worker_session:
            line = worker_session.get(CarrierLine, line_id)
            assert line is not None
            action = CarrierLineAction(
                carrier_line_id=line.id,
                provider=carrier.name,
                kind=LineActionKind.SUSPEND,
                state=LineActionState.REQUESTED,
                requested_at=NOW,
            )
            worker_session.add(action)
            barrier.wait(timeout=10)
            try:
                worker_session.commit()
            except IntegrityError:
                return "refused"
            return "accepted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(suspend), pool.submit(suspend)]
        outcomes = sorted(future.result() for future in futures)

    assert outcomes == ["accepted", "refused"]
    session.rollback()
    assert len(session.exec(select(CarrierLineAction)).all()) == 1


def test_a_lost_lifecycle_dispatch_stays_open_without_a_reference(
    session: Session, service: ConnectivityService
) -> None:
    """Re-sending would race a request that may already be in flight."""

    class LosingCarrier(FakeCarrier):
        def set_state(
            self, provider_reference: str, target: ProviderLineState
        ) -> ProviderAction:
            raise ConnectivityOutcomeUnknown("the response never arrived")

    carrier = LosingCarrier()
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    line = session.exec(select(CarrierLine)).one()

    action = service.request_action(session, line, LineActionKind.SUSPEND)
    service.dispatch_action(session, action, line, carrier)
    session.commit()

    session.refresh(action)
    assert action.state is LineActionState.PENDING
    assert action.provider_action_reference is None
    assert action.settled_at is None
    # Polling cannot resolve it: there is no id to poll.
    service.poll_action(session, action, line, carrier)
    assert action.state is LineActionState.PENDING


def test_an_action_cannot_be_dispatched_against_another_line(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    first = _order_item(session)
    second = _order_item(session)
    for item in (first, second):
        attempt = service.begin_provisioning(session, item, carrier)
        session.commit()
        service.dispatch_provisioning(session, attempt, carrier)
        session.commit()
    lines = session.exec(select(CarrierLine).order_by(CarrierLine.created_at)).all()
    assert len(lines) == 2

    action = service.request_action(session, lines[0], LineActionKind.SUSPEND)
    with pytest.raises(ConnectivityServiceError) as caught:
        service.dispatch_action(session, action, lines[1], carrier)

    assert caught.value.code == "action_line_mismatch"


def test_a_settled_action_must_carry_a_timestamp(session: Session) -> None:
    """`ck_line_actions_settled_at`, at the database.

    "When did this line stop working" has to be answerable.
    """
    item = _order_item(session)
    entitlement = Entitlement(
        order_item_id=item.id,
        product_id=item.product_id,
        data_bytes_total=1,
        voice_seconds_total=0,
        granted_at=NOW,
    )
    session.add(entitlement)
    session.flush()
    line = CarrierLine(
        entitlement_id=entitlement.id,
        carrier="fakecarrier",
        carrier_line_reference=f"line-{uuid4().hex[:8]}",
        created_at=NOW,
    )
    session.add(line)
    session.flush()
    session.add(
        CarrierLineAction(
            carrier_line_id=line.id,
            provider="fakecarrier",
            kind=LineActionKind.SUSPEND,
            state=LineActionState.CONFIRMED,
            provider_action_reference="a1",
            requested_at=NOW,
            settled_at=None,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


# --- installation material ---------------------------------------------------


def test_the_activation_code_is_never_stored_in_the_clear(
    session: Session, service: ConnectivityService, carrier: FakeCarrier, vault
) -> None:
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    installation = session.exec(select(EsimInstallation)).one()
    line = session.exec(select(CarrierLine)).one()
    service.fetch_and_store_credential(session, installation, line, carrier)
    session.commit()

    credential = session.exec(select(EsimActivationCredential)).one()
    assert carrier.activation_code.encode() not in credential.ciphertext
    assert credential.fingerprint != carrier.activation_code
    assert vault.unseal(credential) == carrier.activation_code

    row = session.exec(
        text("SELECT ciphertext::text FROM esim_activation_credentials")
    ).one()
    assert "LPA" not in str(row)


def test_a_credential_cannot_be_stored_for_another_lines_installation(
    session: Session, service: ConnectivityService, carrier: FakeCarrier
) -> None:
    for _ in range(2):
        item = _order_item(session)
        attempt = service.begin_provisioning(session, item, carrier)
        session.commit()
        service.dispatch_provisioning(session, attempt, carrier)
        session.commit()
    lines = session.exec(select(CarrierLine).order_by(CarrierLine.created_at)).all()
    installations = session.exec(
        select(EsimInstallation).order_by(EsimInstallation.id)
    ).all()
    first_installation = next(
        installation
        for installation in installations
        if installation.entitlement_id == lines[0].entitlement_id
    )

    with pytest.raises(ConnectivityServiceError) as caught:
        service.fetch_and_store_credential(
            session, first_installation, lines[1], carrier
        )

    assert caught.value.code == "installation_line_mismatch"


def test_a_credential_moved_between_installations_fails_to_decrypt(
    session: Session, service: ConnectivityService, carrier: FakeCarrier, vault
) -> None:
    """AES-GCM additional data binds a ciphertext to its row.

    Without it, somebody with write access could swap two customers' profiles
    and both would decrypt cleanly.
    """
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    installation = session.exec(select(EsimInstallation)).one()
    line = session.exec(select(CarrierLine)).one()
    service.fetch_and_store_credential(session, installation, line, carrier)
    session.commit()

    credential = session.exec(select(EsimActivationCredential)).one()
    credential.esim_installation_id = uuid4()
    with pytest.raises(CredentialError) as caught:
        vault.unseal(credential)
    assert caught.value.code == "authentication_failed"


def test_a_grant_is_single_use_and_bound_to_its_subject(
    session: Session,
    service: ConnectivityService,
    carrier: FakeCarrier,
    vault,
    clock,
) -> None:
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    installation = session.exec(select(EsimInstallation)).one()
    line = session.exec(select(CarrierLine)).one()
    service.fetch_and_store_credential(session, installation, line, carrier)
    credential = session.exec(select(EsimActivationCredential)).one()
    holder = item.recipient_user_id
    assert holder is not None

    issued = vault.issue_grant(session, credential, holder)
    session.commit()

    assert "LPA" not in repr(issued)
    stored = session.exec(select(CredentialGrant)).one()
    assert issued.token != stored.token_fingerprint
    assert issued.token not in stored.token_fingerprint

    assert vault.redeem(session, issued.token, holder) == carrier.activation_code
    session.commit()

    with pytest.raises(CredentialError, match="grant_not_redeemable"):
        vault.redeem(session, issued.token, holder)

    session.rollback()
    session.refresh(credential)
    assert credential.delivery_count == 1
    assert credential.last_delivered_at == NOW


def test_a_grant_for_somebody_else_is_refused(
    session: Session, service: ConnectivityService, carrier: FakeCarrier, vault
) -> None:
    """And with the same error as an unknown token, so nothing is learned."""
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    installation = session.exec(select(EsimInstallation)).one()
    line = session.exec(select(CarrierLine)).one()
    service.fetch_and_store_credential(session, installation, line, carrier)
    credential = session.exec(select(EsimActivationCredential)).one()
    holder = item.recipient_user_id
    assert holder is not None
    issued = vault.issue_grant(session, credential, holder)
    session.commit()

    intruder = User(
        phone_number=f"+23488{uuid4().int % 10**8:08d}",
        first_name="intruder",
        platform=Platform.ANDROID,
    )
    session.add(intruder)
    session.flush()
    with pytest.raises(CredentialError, match="grant_not_redeemable"):
        vault.redeem(session, issued.token, intruder.id)

    with pytest.raises(CredentialError, match="grant_not_redeemable"):
        vault.redeem(session, "a-token-that-never-existed", holder)


def test_a_grant_cannot_be_issued_to_somebody_other_than_the_holder(
    session: Session, service: ConnectivityService, carrier: FakeCarrier, vault
) -> None:
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    installation = session.exec(select(EsimInstallation)).one()
    line = session.exec(select(CarrierLine)).one()
    service.fetch_and_store_credential(session, installation, line, carrier)
    credential = session.exec(select(EsimActivationCredential)).one()
    intruder = User(
        phone_number=f"+23488{uuid4().int % 10**8:08d}",
        first_name="intruder",
        platform=Platform.ANDROID,
    )
    session.add(intruder)
    session.flush()

    with pytest.raises(CredentialError, match="grant_not_authorized"):
        vault.issue_grant(session, credential, intruder.id)


def test_a_grant_stops_working_if_the_entitlement_changes_holder(
    session: Session, service: ConnectivityService, carrier: FakeCarrier, vault
) -> None:
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    credential = session.exec(select(EsimActivationCredential)).first()
    if credential is None:
        installation = session.exec(select(EsimInstallation)).one()
        line = session.exec(select(CarrierLine)).one()
        service.fetch_and_store_credential(session, installation, line, carrier)
        credential = session.exec(select(EsimActivationCredential)).one()
    holder = item.recipient_user_id
    assert holder is not None
    issued = vault.issue_grant(session, credential, holder)
    entitlement = session.exec(select(Entitlement)).one()
    replacement = User(
        phone_number=f"+23488{uuid4().int % 10**8:08d}",
        first_name="replacement",
        platform=Platform.ANDROID,
    )
    session.add(replacement)
    session.flush()
    entitlement.holder_user_id = replacement.id
    session.add(entitlement)
    session.commit()

    with pytest.raises(CredentialError, match="grant_not_redeemable"):
        vault.redeem(session, issued.token, holder)


def test_an_expired_grant_is_refused(
    session: Session,
    service: ConnectivityService,
    carrier: FakeCarrier,
    vault,
    clock,
) -> None:
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    installation = session.exec(select(EsimInstallation)).one()
    line = session.exec(select(CarrierLine)).one()
    service.fetch_and_store_credential(session, installation, line, carrier)
    credential = session.exec(select(EsimActivationCredential)).one()
    holder = item.recipient_user_id
    assert holder is not None
    issued = vault.issue_grant(session, credential, holder)
    session.commit()

    clock.advance(minutes=11)
    with pytest.raises(CredentialError, match="grant_not_redeemable"):
        vault.redeem(session, issued.token, holder)


def test_revoking_burns_outstanding_grants_without_losing_the_audit_trail(
    session: Session, service: ConnectivityService, carrier: FakeCarrier, vault
) -> None:
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    installation = session.exec(select(EsimInstallation)).one()
    line = session.exec(select(CarrierLine)).one()
    service.fetch_and_store_credential(session, installation, line, carrier)
    credential = session.exec(select(EsimActivationCredential)).one()
    holder = item.recipient_user_id
    assert holder is not None
    issued = vault.issue_grant(session, credential, holder)
    session.commit()

    assert vault.revoke_open_grants(session, credential) == 1
    session.commit()

    with pytest.raises(CredentialError, match="grant_not_redeemable"):
        vault.redeem(session, issued.token, holder)
    # Who was granted access is still recorded.
    assert len(session.exec(select(CredentialGrant)).all()) == 1


def test_a_second_different_code_for_one_installation_is_refused(
    session: Session, service: ConnectivityService, carrier: FakeCarrier, vault
) -> None:
    """An eSIM code is one-time use; silently replacing one loses a profile."""
    item = _order_item(session)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    installation = session.exec(select(EsimInstallation)).one()
    line = session.exec(select(CarrierLine)).one()
    service.fetch_and_store_credential(session, installation, line, carrier)
    session.commit()

    # The same code again is harmless -- a supplier repeating itself.
    service.fetch_and_store_credential(session, installation, line, carrier)
    assert len(session.exec(select(EsimActivationCredential)).all()) == 1

    carrier.activation_code = "LPA:1$smdp.example$DIFFERENT"
    with pytest.raises(CredentialError) as caught:
        service.fetch_and_store_credential(session, installation, line, carrier)
    assert caught.value.code == "credential_conflict"


def test_a_vault_without_a_key_refuses_rather_than_storing_plaintext() -> None:
    with pytest.raises(CredentialError) as caught:
        CredentialVault(b"too-short", "k1")
    assert caught.value.code == "invalid_key"
    with pytest.raises(CredentialError) as caught:
        CredentialVault(KEY, "")
    assert caught.value.code == "missing_key_reference"


def test_a_service_without_a_vault_refuses_to_store_material(
    session: Session, carrier: FakeCarrier, clock
) -> None:
    item = _order_item(session)
    service = ConnectivityService(FulfilmentService(clock=clock), None, clock=clock)
    attempt = service.begin_provisioning(session, item, carrier)
    session.commit()
    service.dispatch_provisioning(session, attempt, carrier)
    installation = session.exec(select(EsimInstallation)).one()
    with pytest.raises(ConnectivityServiceError) as caught:
        service.store_activation_credential(
            session, installation, ActivationCredential(secret="LPA:1$x$y")
        )
    assert caught.value.code == "no_credential_vault"
