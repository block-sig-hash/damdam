"""US-36 chunk 17 — top-ups, spending controls and suspension, on PostgreSQL.

Two invariants, and the first one is a refusal.

**A prepaid guarantee may not be promised on delayed app-side accounting.**
`prd.md` AC-36.4 forbids it and the Telnyx capability record says why: the data
limit's enforcement latency is undocumented and no voice cap is documented at
all. So the assertion that matters most in this file is that
`prepaid_guarantee` says **no** for Telnyx as configured today, with a reason
attached.

**A top-up never gives away allowance and never loses paid credit.** Consumption
already recorded stays recorded, so topping up after an overshoot adds to a
deficit rather than resetting it; and a top-up that fails releases its hold
rather than keeping the customer's money.

PostgreSQL, not SQLite: the idempotency guard is a unique constraint, the
reservation race is a `SELECT … FOR UPDATE`, and the suspension guard is a
partial unique index.
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
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app import model_registry  # noqa: F401  -- completes SQLModel.metadata
from app.auth.models import (
    Locale,
    Organization,
    OrganizationType,
    Platform,
    User,
)
from app.catalog.models import LegalEntity, Product, ProductAllowance, ProductKind
from app.connectivity.contract import (
    AdapterCapabilities,
    AdapterChannel,
    Capability,
    ConnectivityError,
    ConnectivityOutcomeUnknown,
    ProviderAction,
    ProviderLine,
    ProviderLineState,
)
from app.connectivity.models import (
    ActivationState,
    CarrierLine,
    CarrierLineAction,
    Entitlement,
    LineActionState,
)
from app.connectivity.service import ConnectivityService
from app.controls.models import (
    AllowanceNotice,
    ControlState,
    Enforcement,
    EntitlementTopUp,
    OrganizationSpendingPolicy,
    SpendingControl,
    TopUpState,
)
from app.controls.service import ControlError, ControlService, TopUpQuote
from app.fulfilment.service import FulfilmentService
from app.ledger.models import AccountKind, JournalEntry, OwnerKind
from app.ledger.service import LedgerService
from app.orders.models import Order, OrderItem
from app.usage.contract import CounterSnapshot
from app.usage.service import Freshness, UsageService

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="top-up races and the suspension guard require PostgreSQL",
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
TABLES = (
    "allowance_notices, organization_spending_policies, spending_controls, "
    "entitlement_top_ups, usage_records, usage_counter_readings, usage_cursors, "
    "exception_items, ledger_reservations, journal_lines, journal_entries, "
    "ledger_accounts, carrier_line_actions, carrier_lines, esim_installations, "
    "entitlements, order_items, orders, product_allowances, products, "
    "legal_entities, organizations, users"
)


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: float) -> None:
        self.value += timedelta(**kwargs)


class FakeCarrier:
    """A carrier that can and cannot enforce spending, on request.

    The capability set is the whole point: `prepaid_guarantee` reads it, and the
    difference between a supplier that stops traffic and one that does not is
    the difference between a promise we can make and one we cannot.
    """

    name = "fakecarrier"

    def __init__(
        self,
        capabilities: frozenset[Capability] | None = None,
        limit_latency_documented: bool = False,
    ) -> None:
        self.capability_set = capabilities or frozenset(
            {Capability.DATA, Capability.SUSPENSION}
        )
        self.limit_latency_documented = limit_latency_documented
        self.limits: dict[str, int] = {}
        self.lose_limit_response = False
        self.refuse_limit: str | None = None
        self.confirm_limit = True
        self.actions: dict[str, ProviderAction] = {}
        self.action_calls: list[str] = []

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supported=self.capability_set,
            channel=AdapterChannel.CARRIER,
            undocumented={
                capability.value: "not verified for this fake"
                for capability in Capability
                if capability not in self.capability_set
            },
        )

    # lifecycle -----------------------------------------------------------
    def set_state(
        self, provider_reference: str, target: ProviderLineState
    ) -> ProviderAction:
        self.capabilities().require(Capability.SUSPENSION)
        self.action_calls.append(target.value)
        reference = f"action-{target.value}-{len(self.actions) + 1}"
        action = ProviderAction(
            provider_reference=reference,
            succeeded=None,
            settled=False,
            provider_status="in-progress",
        )
        self.actions[reference] = action
        return action

    def fetch_action(self, provider_action_reference: str) -> ProviderAction | None:
        return self.actions.get(provider_action_reference)

    def settle(self, reference: str, succeeded: bool = True) -> None:
        self.actions[reference] = ProviderAction(
            provider_reference=reference,
            succeeded=succeeded,
            settled=True,
            provider_status="completed" if succeeded else "failed",
        )

    # spending ------------------------------------------------------------
    def set_data_limit(self, provider_reference: str, limit_bytes: int) -> ProviderLine:
        self.capabilities().require(Capability.SPENDING_ENFORCEMENT)
        if self.lose_limit_response:
            raise ConnectivityOutcomeUnknown("the response never arrived")
        if self.refuse_limit:
            raise ConnectivityError("limit_refused", self.refuse_limit)
        self.limits[provider_reference] = limit_bytes
        return ProviderLine(
            provider_reference=provider_reference,
            state=ProviderLineState.ACTIVE,
            provider_status="enabled",
            data_limit_bytes=limit_bytes if self.confirm_limit else None,
            observed_at=NOW,
        )

    # unused by these tests, present so the Protocol is satisfied ----------
    def provision(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    def reconcile(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        return None

    def fetch_line(self, provider_reference: str) -> ProviderLine | None:
        return None

    def fetch_activation_credential(self, provider_reference: str) -> Any:
        raise ConnectivityError("not_implemented")

    def enable_voice(self, provider_reference: str) -> ProviderAction:
        self.capabilities().require(Capability.NATIVE_VOICE)
        raise NotImplementedError  # pragma: no cover

    def assigned_number(self, provider_reference: str) -> str | None:
        return None


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
def ledger(clock: Clock) -> LedgerService:
    return LedgerService(clock=clock)


@pytest.fixture
def usage(ledger: LedgerService, clock: Clock) -> UsageService:
    return UsageService(ledger, clock=clock)


@pytest.fixture
def service(
    usage: UsageService, ledger: LedgerService, clock: Clock
) -> ControlService:
    return ControlService(
        usage,
        ConnectivityService(FulfilmentService(clock=clock), clock=clock),
        ledger,
        clock=clock,
    )


@pytest.fixture
def carrier() -> FakeCarrier:
    return FakeCarrier()


def _line(
    session: Session,
    data_bytes: int = 1_000_000_000,
    voice_seconds: int = 600,
    validity_days: int | None = 30,
    organization: Organization | None = None,
) -> CarrierLine:
    entity = LegalEntity(code=f"E{uuid4().hex[:6]}", name="Seller", country="NG")
    product = Product(
        sku=f"sku-{uuid4().hex[:8]}", name="Plan", kind=ProductKind.BUNDLE
    )
    payer = User(
        phone_number=f"+23488{uuid4().int % 10**8:08d}",
        first_name="payer",
        platform=Platform.ANDROID,
    )
    session.add_all([entity, product, payer])
    session.flush()
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
        payer_user_id=None if organization else payer.id,
        payer_organization_id=organization.id if organization else None,
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
    entitlement = Entitlement(
        order_item_id=item.id,
        holder_user_id=payer.id,
        product_id=product.id,
        data_bytes_total=data_bytes,
        voice_seconds_total=voice_seconds,
        granted_at=NOW,
        expires_at=(
            None if validity_days is None else NOW + timedelta(days=validity_days)
        ),
    )
    session.add(entitlement)
    session.flush()
    line = CarrierLine(
        entitlement_id=entitlement.id,
        carrier="fakecarrier",
        carrier_line_reference=f"sim-{uuid4().hex[:10]}",
        activation_state=ActivationState.ACTIVE,
        authoritative_data_source="counter",
        created_at=NOW,
    )
    session.add(line)
    session.flush()
    return line


def _entitlement(session: Session, line: CarrierLine) -> Entitlement:
    entitlement = session.get(Entitlement, line.entitlement_id)
    assert entitlement is not None
    return entitlement


def _top_up_item(session: Session, line: CarrierLine) -> OrderItem:
    """A second purchase against the same order, for the same recipient."""
    entitlement = _entitlement(session, line)
    original = session.get(OrderItem, entitlement.order_item_id)
    assert original is not None
    item = OrderItem(
        order_id=original.order_id,
        product_id=original.product_id,
        recipient_user_id=original.recipient_user_id,
        unit_currency="NGN",
        unit_amount=Decimal("1500.00"),
    )
    session.add(item)
    session.flush()
    return item


def _funded_account(
    session: Session, ledger: LedgerService, line: CarrierLine, amount: str = "5000.00"
):
    entitlement = _entitlement(session, line)
    holder = entitlement.holder_user_id
    assert holder is not None
    account = ledger.account(
        session, "NGN", AccountKind.SERVICE_CREDIT, OwnerKind.USER, owner_user_id=holder
    )
    funding = ledger.account(session, "NGN", AccountKind.ADJUSTMENT)
    from app.ledger.models import Direction
    from app.ledger.service import Posting

    ledger.post(
        session,
        f"fund:{uuid4()}",
        [
            Posting(funding, Direction.DEBIT, Decimal(amount)),
            Posting(account, Direction.CREDIT, Decimal(amount)),
        ],
    )
    return account


QUOTE = TopUpQuote(
    data_bytes=500_000_000,
    voice_seconds=0,
    extends_days=0,
    currency="NGN",
    amount=Decimal("1500.00"),
)


# --- the refusal -------------------------------------------------------------


def test_a_hard_cap_is_not_promised_on_delayed_accounting(
    session: Session, service: ControlService, carrier: FakeCarrier
) -> None:
    """The assertion this chunk exists for.

    A supplier that does not advertise verified spending enforcement cannot back
    a prepaid guarantee, and adding up delayed usage records does not change
    that — the app is not running when a native call is placed.
    """
    line = _line(session)
    assessment = service.prepaid_guarantee(carrier, service.control_for(session, line))
    assert assessment.can_promise is False
    assert assessment.enforcement is Enforcement.NONE
    assert assessment.reason


def test_an_enforceable_limit_with_unquantified_latency_still_cannot_promise(
    session: Session, service: ControlService
) -> None:
    """The Telnyx case exactly, one step further in.

    Even with the capability switched on and a limit confirmed, an undocumented
    enforcement latency means an unbounded overshoot — and an unbounded
    overshoot is not a cap.
    """
    carrier = FakeCarrier(
        frozenset(
            {Capability.DATA, Capability.SUSPENSION, Capability.SPENDING_ENFORCEMENT}
        )
    )
    line = _line(session)
    control = service.apply_provider_limit(session, line, carrier, 1_000_000_000)
    session.commit()

    assert control.state is ControlState.ACTIVE
    assert control.confirmed_limit_bytes == 1_000_000_000
    assessment = service.prepaid_guarantee(carrier, control)
    assert assessment.can_promise is False
    assert "overshoot is unquantified" in assessment.reason


def test_a_documented_bound_can_promise(
    session: Session, service: ControlService
) -> None:
    carrier = FakeCarrier(
        frozenset(
            {Capability.DATA, Capability.SUSPENSION, Capability.SPENDING_ENFORCEMENT}
        )
    )
    line = _line(session)
    control = service.apply_provider_limit(
        session, line, carrier, 1_000_000_000, max_overshoot_bytes=10_000_000
    )
    session.commit()
    assessment = service.prepaid_guarantee(carrier, control)
    assert assessment.can_promise is True
    assert assessment.enforcement is Enforcement.PROVIDER_HARD_LIMIT
    assert assessment.max_overshoot_bytes == 10_000_000


def test_an_approved_bounded_exposure_policy_can_promise(
    session: Session, service: ControlService, carrier: FakeCarrier
) -> None:
    """The honest alternative: somebody decided how much exposure is acceptable."""
    line = _line(session)
    control = service.approve_bounded_exposure(
        session, line, "DECISIONS.md D5 bounded exposure 2026-09-10", 50_000_000
    )
    session.commit()
    assessment = service.prepaid_guarantee(carrier, control)
    assert assessment.can_promise is True
    assert assessment.enforcement is Enforcement.APPROVED_BOUNDED_EXPOSURE
    assert assessment.max_overshoot_bytes == 50_000_000


def test_a_bounded_exposure_policy_must_name_its_approval(
    session: Session, service: ControlService
) -> None:
    line = _line(session)
    with pytest.raises(ControlError) as caught:
        service.approve_bounded_exposure(session, line, "", 1)
    assert caught.value.code == "policy_reference_required"


def test_a_control_cannot_claim_enforcement_without_a_confirmed_limit(
    session: Session,
) -> None:
    """`ck_spending_controls_hard_limit_needs_confirmation`, at the database."""
    line = _line(session)
    session.add(
        SpendingControl(
            carrier_line_id=line.id,
            enforcement=Enforcement.PROVIDER_HARD_LIMIT,
            state=ControlState.ACTIVE,
            confirmed_limit_bytes=None,
            requested_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_shared_carrier_and_internet_credit_needs_a_bounded_carrier(
    session: Session, service: ControlService, carrier: FakeCarrier
) -> None:
    """The calling amendment's own requirement.

    *"A unified displayed balance is insufficient: allocate bounded carrier
    exposure separately before native use."* Without it a native call could
    spend internet-calling credit with nothing able to stop it.
    """
    line = _line(session)
    allowed, reason = service.shared_credit_allowed(
        carrier, service.control_for(session, line)
    )
    assert allowed is False
    assert "while the app is closed" in reason

    control = service.approve_bounded_exposure(session, line, "approval-1", 1_000)
    allowed, _ = service.shared_credit_allowed(carrier, control)
    assert allowed is True


def test_a_supplier_that_cannot_set_a_limit_records_that_rather_than_claiming_one(
    session: Session, service: ControlService
) -> None:
    class NoLimitCarrier(FakeCarrier):
        set_data_limit = None  # type: ignore[assignment]

    line = _line(session)
    control = service.apply_provider_limit(session, line, NoLimitCarrier(), 1_000)
    session.commit()
    assert control.state is ControlState.FAILED
    assert control.enforcement is Enforcement.NONE
    assert control.detail is not None and "no way to set" in control.detail


def test_a_supplier_that_reports_no_limit_after_the_change_is_not_a_confirmation(
    session: Session, service: ControlService
) -> None:
    """Accepting the call is not applying the cap.

    Recording it as active would put a limit in our database that does not exist
    at the carrier — the worst kind of wrong, because everything downstream then
    believes there is a bound.
    """
    carrier = FakeCarrier(
        frozenset(
            {Capability.DATA, Capability.SUSPENSION, Capability.SPENDING_ENFORCEMENT}
        )
    )
    carrier.confirm_limit = False
    line = _line(session)
    control = service.apply_provider_limit(session, line, carrier, 1_000_000)
    session.commit()
    assert control.state is ControlState.FAILED
    assert control.enforcement is Enforcement.NONE


def test_a_lost_limit_response_is_unknown_and_not_re_sent(
    session: Session, service: ControlService
) -> None:
    """Re-sending races a change that may already have applied."""
    carrier = FakeCarrier(
        frozenset(
            {Capability.DATA, Capability.SUSPENSION, Capability.SPENDING_ENFORCEMENT}
        )
    )
    carrier.lose_limit_response = True
    line = _line(session)
    control = service.apply_provider_limit(session, line, carrier, 1_000_000)
    session.commit()
    assert control.state is ControlState.OUTCOME_UNKNOWN
    assert control.enforcement is Enforcement.NONE
    assert control.confirmed_limit_bytes is None


# --- top-ups -----------------------------------------------------------------


def test_a_top_up_is_idempotent_on_its_order_item(
    session: Session, service: ControlService
) -> None:
    line = _line(session)
    entitlement = _entitlement(session, line)
    item = _top_up_item(session, line)
    first = service.request_top_up(session, entitlement, item, QUOTE)
    second = service.request_top_up(session, entitlement, item, QUOTE)
    session.commit()
    assert first.id == second.id
    assert len(session.exec(select(EntitlementTopUp)).all()) == 1


def test_a_second_top_up_row_for_one_purchase_is_refused(
    session: Session, service: ControlService
) -> None:
    """`uq_entitlement_top_ups_order_item`, at the database."""
    line = _line(session)
    entitlement = _entitlement(session, line)
    item = _top_up_item(session, line)
    service.request_top_up(session, entitlement, item, QUOTE)
    session.add(
        EntitlementTopUp(
            entitlement_id=entitlement.id,
            order_item_id=item.id,
            business_event_id=f"topup:{uuid4()}",
            data_bytes=1,
            currency="NGN",
            amount=Decimal("1.00"),
            requested_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_a_top_up_grants_nothing_until_it_is_applied(
    session: Session, service: ControlService, ledger: LedgerService
) -> None:
    """Paid is not granted.

    A customer told they have data while the cap has not moved gets a session
    that fails and an app insisting it should work.
    """
    line = _line(session)
    entitlement = _entitlement(session, line)
    item = _top_up_item(session, line)
    account = _funded_account(session, ledger, line)
    revenue = ledger.account(session, "NGN", AccountKind.REVENUE)

    top_up = service.request_top_up(session, entitlement, item, QUOTE)
    before = service.allowance(session, entitlement)
    assert before.data_bytes_total == 1_000_000_000

    reservation = service.reserve_top_up(session, top_up, account)
    assert service.allowance(session, entitlement).data_bytes_total == 1_000_000_000

    service.settle_top_up(session, top_up, reservation, revenue)
    assert top_up.state is TopUpState.PAID
    assert service.allowance(session, entitlement).data_bytes_total == 1_000_000_000

    service.apply_top_up(session, top_up, line)
    session.commit()
    assert top_up.state is TopUpState.APPLIED
    assert (
        service.allowance(session, entitlement).data_bytes_total == 1_500_000_000
    )


def test_a_top_up_after_an_overshoot_does_not_give_away_the_overshoot(
    session: Session, service: ControlService, ledger: LedgerService
) -> None:
    """The assignment's "without giving away allowance", in one assertion.

    Usage already recorded stays recorded. Topping up after exhaustion adds to
    a deficit rather than resetting it, so a customer who overshot by 200 MB
    gets 300 MB of a 500 MB top-up, not 500.
    """
    line = _line(session, data_bytes=1_000_000_000)
    entitlement = _entitlement(session, line)
    service.usage.ingest_counter(
        session,
        line,
        CounterSnapshot(line.carrier_line_reference, 1_200_000_000, NOW),
    )
    session.commit()
    assert service.allowance(session, entitlement).data_bytes_remaining == 0

    item = _top_up_item(session, line)
    account = _funded_account(session, ledger, line)
    revenue = ledger.account(session, "NGN", AccountKind.REVENUE)
    top_up = service.request_top_up(session, entitlement, item, QUOTE)
    reservation = service.reserve_top_up(session, top_up, account)
    service.settle_top_up(session, top_up, reservation, revenue)
    service.apply_top_up(session, top_up, line)
    session.commit()

    view = service.allowance(session, entitlement)
    assert view.data_bytes_total == 1_500_000_000
    assert view.data_bytes_used == 1_200_000_000
    assert view.data_bytes_remaining == 300_000_000


def test_a_failed_top_up_returns_the_hold_and_keeps_no_credit(
    session: Session, service: ControlService, ledger: LedgerService
) -> None:
    line = _line(session)
    entitlement = _entitlement(session, line)
    item = _top_up_item(session, line)
    account = _funded_account(session, ledger, line, "2000.00")
    top_up = service.request_top_up(session, entitlement, item, QUOTE)
    reservation = service.reserve_top_up(session, top_up, account)
    session.commit()
    assert ledger.available(session, account) == Decimal("500.00")

    service.fail_top_up(session, top_up, "supplier refused", reservation)
    session.commit()

    assert top_up.state is TopUpState.FAILED
    assert ledger.available(session, account) == Decimal("2000.00")
    # Nothing was posted: releasing a hold moves no money.
    assert len(session.exec(select(JournalEntry)).all()) == 1  # only the funding


def test_reversing_an_applied_top_up_is_a_refund_decision_not_a_failure(
    session: Session, service: ControlService, ledger: LedgerService
) -> None:
    line = _line(session)
    entitlement = _entitlement(session, line)
    item = _top_up_item(session, line)
    account = _funded_account(session, ledger, line)
    revenue = ledger.account(session, "NGN", AccountKind.REVENUE)
    top_up = service.request_top_up(session, entitlement, item, QUOTE)
    reservation = service.reserve_top_up(session, top_up, account)
    service.settle_top_up(session, top_up, reservation, revenue)
    service.apply_top_up(session, top_up, line)
    with pytest.raises(ControlError) as caught:
        service.fail_top_up(session, top_up, "changed our mind")
    assert caught.value.code == "top_up_already_applied"


def test_two_concurrent_top_ups_cannot_both_spend_the_same_credit(
    engine, session: Session, service: ControlService, ledger: LedgerService
) -> None:
    """The classic overspend, arbitrated by the account row lock in chunk 10."""
    line = _line(session)
    entitlement = _entitlement(session, line)
    account = _funded_account(session, ledger, line, "2000.00")
    items = [_top_up_item(session, line), _top_up_item(session, line)]
    session.commit()

    entitlement_id = entitlement.id
    account_id = account.id
    item_ids = [item.id for item in items]
    barrier = Barrier(2)

    def buy(item_id: UUID) -> str:
        with Session(engine) as worker:
            worker_service = ControlService(
                UsageService(LedgerService(clock=Clock()), clock=Clock()),
                ConnectivityService(FulfilmentService(clock=Clock()), clock=Clock()),
                LedgerService(clock=Clock()),
                clock=Clock(),
            )
            held_entitlement = worker.get(Entitlement, entitlement_id)
            held_item = worker.get(OrderItem, item_id)
            held_account = worker.get(type(account), account_id)
            assert held_entitlement and held_item and held_account
            top_up = worker_service.request_top_up(
                worker, held_entitlement, held_item, QUOTE
            )
            barrier.wait(timeout=10)
            try:
                worker_service.reserve_top_up(worker, top_up, held_account)
                worker.commit()
            except Exception:
                worker.rollback()
                return "refused"
            return "accepted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(buy, item_id) for item_id in item_ids]
        outcomes = sorted(future.result() for future in futures)

    # 2,000 available and two 1,500 top-ups: exactly one can win.
    assert outcomes == ["accepted", "refused"]


def test_applying_a_top_up_raises_an_enforced_cap_first(
    session: Session, service: ControlService, ledger: LedgerService
) -> None:
    """Otherwise the app says there is data while the carrier still blocks it."""
    carrier = FakeCarrier(
        frozenset(
            {Capability.DATA, Capability.SUSPENSION, Capability.SPENDING_ENFORCEMENT}
        )
    )
    line = _line(session)
    entitlement = _entitlement(session, line)
    service.apply_provider_limit(
        session, line, carrier, 1_000_000_000, max_overshoot_bytes=1_000
    )
    item = _top_up_item(session, line)
    account = _funded_account(session, ledger, line)
    revenue = ledger.account(session, "NGN", AccountKind.REVENUE)
    top_up = service.request_top_up(session, entitlement, item, QUOTE)
    reservation = service.reserve_top_up(session, top_up, account)
    service.settle_top_up(session, top_up, reservation, revenue)
    service.apply_top_up(session, top_up, line, carrier)
    session.commit()

    assert top_up.state is TopUpState.APPLIED
    assert carrier.limits[line.carrier_line_reference] == 1_500_000_000
    control = session.exec(select(SpendingControl)).one()
    assert control.confirmed_limit_bytes == 1_500_000_000


def test_a_top_up_whose_cap_raise_is_unknown_grants_nothing_and_keeps_the_money(
    session: Session, service: ControlService, ledger: LedgerService
) -> None:
    """Neither direction is known to be right, so neither is taken.

    Granting the allowance would give away data the carrier still blocks;
    refunding would return money for a cap that may well have been raised.
    """
    carrier = FakeCarrier(
        frozenset(
            {Capability.DATA, Capability.SUSPENSION, Capability.SPENDING_ENFORCEMENT}
        )
    )
    line = _line(session)
    entitlement = _entitlement(session, line)
    service.apply_provider_limit(
        session, line, carrier, 1_000_000_000, max_overshoot_bytes=1_000
    )
    item = _top_up_item(session, line)
    account = _funded_account(session, ledger, line)
    revenue = ledger.account(session, "NGN", AccountKind.REVENUE)
    top_up = service.request_top_up(session, entitlement, item, QUOTE)
    reservation = service.reserve_top_up(session, top_up, account)
    service.settle_top_up(session, top_up, reservation, revenue)

    carrier.lose_limit_response = True
    service.apply_top_up(session, top_up, line, carrier)
    session.commit()

    assert top_up.state is TopUpState.OUTCOME_UNKNOWN
    assert top_up.applied_at is None
    assert service.allowance(session, entitlement).data_bytes_total == 1_000_000_000


def test_applying_a_top_up_twice_grants_once(
    session: Session, service: ControlService, ledger: LedgerService
) -> None:
    line = _line(session)
    entitlement = _entitlement(session, line)
    item = _top_up_item(session, line)
    account = _funded_account(session, ledger, line)
    revenue = ledger.account(session, "NGN", AccountKind.REVENUE)
    top_up = service.request_top_up(session, entitlement, item, QUOTE)
    reservation = service.reserve_top_up(session, top_up, account)
    service.settle_top_up(session, top_up, reservation, revenue)
    service.apply_top_up(session, top_up, line)
    service.apply_top_up(session, top_up, line)
    session.commit()
    assert service.allowance(session, entitlement).data_bytes_total == 1_500_000_000


def test_settling_a_top_up_twice_posts_once(
    session: Session, service: ControlService, ledger: LedgerService
) -> None:
    line = _line(session)
    entitlement = _entitlement(session, line)
    item = _top_up_item(session, line)
    account = _funded_account(session, ledger, line)
    revenue = ledger.account(session, "NGN", AccountKind.REVENUE)
    top_up = service.request_top_up(session, entitlement, item, QUOTE)
    reservation = service.reserve_top_up(session, top_up, account)
    service.settle_top_up(session, top_up, reservation, revenue)
    service.settle_top_up(session, top_up, reservation, revenue)
    session.commit()
    # The funding entry plus exactly one settlement.
    assert len(session.exec(select(JournalEntry)).all()) == 2


def test_an_empty_top_up_is_refused(
    session: Session, service: ControlService
) -> None:
    line = _line(session)
    entitlement = _entitlement(session, line)
    item = _top_up_item(session, line)
    with pytest.raises(ControlError) as caught:
        service.request_top_up(
            session,
            entitlement,
            item,
            TopUpQuote(0, 0, 0, "NGN", Decimal("100.00")),
        )
    assert caught.value.code == "empty_top_up"


# --- expiry ------------------------------------------------------------------


def test_a_top_up_can_extend_expiry(
    session: Session, service: ControlService, ledger: LedgerService, clock: Clock
) -> None:
    line = _line(session, validity_days=30)
    entitlement = _entitlement(session, line)
    clock.advance(days=31)
    assert service.is_expired(session, entitlement) is True

    item = _top_up_item(session, line)
    account = _funded_account(session, ledger, line)
    revenue = ledger.account(session, "NGN", AccountKind.REVENUE)
    top_up = service.request_top_up(
        session,
        entitlement,
        item,
        TopUpQuote(0, 0, 30, "NGN", Decimal("500.00")),
    )
    reservation = service.reserve_top_up(session, top_up, account)
    service.settle_top_up(session, top_up, reservation, revenue)
    service.apply_top_up(session, top_up, line)
    session.commit()

    assert service.is_expired(session, entitlement) is False
    view = service.allowance(session, entitlement)
    assert view.expires_at == NOW + timedelta(days=60)


def test_a_plan_with_no_expiry_never_expires(
    session: Session, service: ControlService, clock: Clock
) -> None:
    line = _line(session, validity_days=None)
    entitlement = _entitlement(session, line)
    clock.advance(days=3650)
    assert service.is_expired(session, entitlement) is False


# --- notices -----------------------------------------------------------------


def test_a_threshold_is_announced_once(
    session: Session, service: ControlService
) -> None:
    """Re-announcing is how people learn to turn notifications off."""
    line = _line(session, data_bytes=1_000)
    entitlement = _entitlement(session, line)
    service.usage.ingest_counter(
        session, line, CounterSnapshot(line.carrier_line_reference, 850, NOW)
    )
    session.commit()

    first = service.low_balance_notices(session, entitlement)
    assert {notice.threshold_percent for notice in first} == {50, 80}
    assert service.low_balance_notices(session, entitlement) == []

    service.usage.ingest_counter(
        session,
        line,
        CounterSnapshot(line.carrier_line_reference, 990, NOW + timedelta(minutes=1)),
    )
    third = service.low_balance_notices(session, entitlement)
    assert {notice.threshold_percent for notice in third} == {95}
    assert len(session.exec(select(AllowanceNotice)).all()) == 3


def test_an_unobserved_balance_announces_nothing(
    session: Session, service: ControlService
) -> None:
    """A "you have used 80%" notice derived from a grant and no measurement is
    an invention."""
    line = _line(session)
    entitlement = _entitlement(session, line)
    assert service.allowance(session, entitlement).freshness is Freshness.UNKNOWN
    assert service.low_balance_notices(session, entitlement) == []


# --- suspension and resumption ----------------------------------------------


def test_an_exhausted_line_is_suspended_as_a_request_not_a_fact(
    session: Session, service: ControlService, carrier: FakeCarrier
) -> None:
    """Chunk 15's four states, driven by chunk 17's policy.

    The line moves when the carrier confirms, not when we ask — an app saying
    "suspended" while traffic still flows is the failure.
    """
    line = _line(session, data_bytes=1_000, voice_seconds=0)
    entitlement = _entitlement(session, line)
    service.usage.ingest_counter(
        session, line, CounterSnapshot(line.carrier_line_reference, 2_000, NOW)
    )
    session.commit()

    action = service.suspend_for_exhaustion(session, entitlement, line, carrier)
    session.commit()
    assert action is not None
    assert action.state is LineActionState.PENDING
    assert line.activation_state is ActivationState.ACTIVE

    reference = action.provider_action_reference
    assert reference is not None
    carrier.settle(reference, succeeded=True)
    service.connectivity.poll_action(session, action, line, carrier)
    session.commit()
    assert action.state is LineActionState.CONFIRMED
    assert line.activation_state is ActivationState.SUSPENDED


def test_an_unobserved_line_is_never_suspended(
    session: Session, service: ControlService, carrier: FakeCarrier
) -> None:
    """Cutting somebody off because a poller never ran is worse than an overshoot.

    The balance would be an invention anyway: nobody has measured it.
    """
    line = _line(session)
    entitlement = _entitlement(session, line)
    assert service.suspend_for_exhaustion(session, entitlement, line, carrier) is None
    assert session.exec(select(CarrierLineAction)).all() == []


def test_an_expired_line_is_suspended_even_with_allowance_left(
    session: Session, service: ControlService, carrier: FakeCarrier, clock: Clock
) -> None:
    line = _line(session, validity_days=30)
    entitlement = _entitlement(session, line)
    service.usage.ingest_counter(
        session, line, CounterSnapshot(line.carrier_line_reference, 1_000, NOW)
    )
    session.commit()
    clock.advance(days=31)

    action = service.suspend_for_exhaustion(session, entitlement, line, carrier)
    session.commit()
    assert action is not None


def test_resuming_while_still_exhausted_is_refused(
    session: Session, service: ControlService, carrier: FakeCarrier
) -> None:
    """Otherwise a customer spends credit they have not got, unstoppably."""
    line = _line(session, data_bytes=1_000, voice_seconds=0)
    line.activation_state = ActivationState.SUSPENDED
    session.add(line)
    entitlement = _entitlement(session, line)
    service.usage.ingest_counter(
        session, line, CounterSnapshot(line.carrier_line_reference, 2_000, NOW)
    )
    session.commit()
    with pytest.raises(ControlError) as caught:
        service.resume_after_top_up(session, entitlement, line, carrier)
    assert caught.value.code == "still_exhausted"


def test_resuming_after_a_top_up_works(
    session: Session, service: ControlService, carrier: FakeCarrier, ledger
) -> None:
    line = _line(session, data_bytes=1_000, voice_seconds=0)
    line.activation_state = ActivationState.SUSPENDED
    session.add(line)
    entitlement = _entitlement(session, line)
    service.usage.ingest_counter(
        session, line, CounterSnapshot(line.carrier_line_reference, 1_000, NOW)
    )
    item = _top_up_item(session, line)
    account = _funded_account(session, ledger, line)
    revenue = ledger.account(session, "NGN", AccountKind.REVENUE)
    top_up = service.request_top_up(session, entitlement, item, QUOTE)
    reservation = service.reserve_top_up(session, top_up, account)
    service.settle_top_up(session, top_up, reservation, revenue)
    service.apply_top_up(session, top_up, line)
    session.commit()

    action = service.resume_after_top_up(session, entitlement, line, carrier)
    session.commit()
    assert action is not None
    assert action.state is LineActionState.PENDING
    # Still suspended until the carrier says otherwise.
    assert line.activation_state is ActivationState.SUSPENDED

    reference = action.provider_action_reference
    assert reference is not None
    carrier.settle(reference, succeeded=True)
    service.connectivity.poll_action(session, action, line, carrier)
    session.commit()
    assert line.activation_state is ActivationState.ACTIVE


def test_a_carrier_imposed_restriction_is_not_ours_to_resume(
    session: Session, service: ControlService, carrier: FakeCarrier, ledger
) -> None:
    """Only raising the limit clears `data_limit_exceeded`.

    Sending a resume would be refused by the carrier, later and less clearly.
    """
    line = _line(session)
    line.activation_state = ActivationState.SUSPENDED
    line.provider_status = "data_limit_exceeded"
    session.add(line)
    entitlement = _entitlement(session, line)
    service.usage.ingest_counter(
        session, line, CounterSnapshot(line.carrier_line_reference, 1, NOW)
    )
    session.commit()

    with pytest.raises(ControlError) as caught:
        service.resume_after_top_up(session, entitlement, line, carrier)
    assert caught.value.code == "carrier_imposed_restriction"


def test_late_usage_after_a_suspension_is_still_counted(
    session: Session, service: ControlService, carrier: FakeCarrier
) -> None:
    """The delayed-CDR case the assignment names.

    Records arriving after a line is suspended describe traffic that really
    happened. Discarding them would give away the overshoot that caused the
    suspension in the first place.
    """
    line = _line(session, data_bytes=1_000, voice_seconds=0)
    entitlement = _entitlement(session, line)
    service.usage.ingest_counter(
        session, line, CounterSnapshot(line.carrier_line_reference, 1_000, NOW)
    )
    action = service.suspend_for_exhaustion(session, entitlement, line, carrier)
    assert action is not None
    reference = action.provider_action_reference
    assert reference is not None
    carrier.settle(reference, succeeded=True)
    service.connectivity.poll_action(session, action, line, carrier)
    session.commit()

    service.usage.ingest_counter(
        session,
        line,
        CounterSnapshot(
            line.carrier_line_reference, 1_400, NOW + timedelta(minutes=10)
        ),
    )
    session.commit()
    view = service.allowance(session, entitlement, now=NOW + timedelta(minutes=11))
    assert view.data_bytes_used == 1_400
    assert view.data_bytes_remaining == 0


def test_a_suspension_and_a_resume_cannot_both_be_open(
    session: Session, service: ControlService, carrier: FakeCarrier, ledger
) -> None:
    """Chunk 15's partial unique index, reached through chunk 17's policy."""
    line = _line(session, data_bytes=1_000, voice_seconds=0)
    entitlement = _entitlement(session, line)
    service.usage.ingest_counter(
        session, line, CounterSnapshot(line.carrier_line_reference, 2_000, NOW)
    )
    service.suspend_for_exhaustion(session, entitlement, line, carrier)
    session.commit()

    item = _top_up_item(session, line)
    account = _funded_account(session, ledger, line)
    revenue = ledger.account(session, "NGN", AccountKind.REVENUE)
    top_up = service.request_top_up(session, entitlement, item, QUOTE)
    reservation = service.reserve_top_up(session, top_up, account)
    service.settle_top_up(session, top_up, reservation, revenue)
    service.apply_top_up(session, top_up, line)
    line.activation_state = ActivationState.SUSPENDED
    session.add(line)
    session.flush()

    with pytest.raises(Exception, match="line_action_conflict|already has an open"):
        service.resume_after_top_up(session, entitlement, line, carrier)


# --- organization budgets ----------------------------------------------------


def _organization(session: Session) -> Organization:
    organization = Organization(
        org_type=OrganizationType.ENTERPRISE,
        name="Globex",
        primary_contact_name="Contact",
        email=f"globex-{uuid4().hex[:8]}@example.test",
        password_hash="unused",
        phone_number="+2348000000000",
        locale=Locale.EN,
    )
    session.add(organization)
    session.flush()
    return organization


def test_a_top_up_past_an_organization_cap_is_refused(
    session: Session, service: ControlService
) -> None:
    organization = _organization(session)
    session.add(
        OrganizationSpendingPolicy(
            organization_id=organization.id,
            currency="NGN",
            period_cap_amount=Decimal("2000.00"),
            enforced=True,
            created_at=NOW,
        )
    )
    line = _line(session, organization=organization)
    entitlement = _entitlement(session, line)
    first = _top_up_item(session, line)
    top_up = service.request_top_up(session, entitlement, first, QUOTE)
    assert top_up.amount == Decimal("1500.00")
    session.commit()

    second = _top_up_item(session, line)
    with pytest.raises(ControlError) as caught:
        service.check_budget(session, second, QUOTE, since=NOW - timedelta(days=1))
    assert caught.value.code == "budget_exceeded"


def test_committed_spend_counts_against_a_cap_before_it_is_applied(
    session: Session, service: ControlService
) -> None:
    """Excluding in-flight top-ups lets two purchases both fit under one cap."""
    organization = _organization(session)
    session.add(
        OrganizationSpendingPolicy(
            organization_id=organization.id,
            currency="NGN",
            period_cap_amount=Decimal("2000.00"),
            created_at=NOW,
        )
    )
    line = _line(session, organization=organization)
    entitlement = _entitlement(session, line)
    item = _top_up_item(session, line)
    service.request_top_up(session, entitlement, item, QUOTE)
    session.commit()

    headroom = service.budget_headroom(
        session, organization.id, "NGN", NOW - timedelta(days=1)
    )
    assert headroom == Decimal("500.00")


def test_no_recorded_policy_is_not_a_cap_of_zero(
    session: Session, service: ControlService
) -> None:
    """`None` means nobody decided, which is not the same as forbidding it."""
    organization = _organization(session)
    line = _line(session, organization=organization)
    item = _top_up_item(session, line)
    assert (
        service.budget_headroom(
            session, organization.id, "NGN", NOW - timedelta(days=1)
        )
        is None
    )
    service.check_budget(session, item, QUOTE, since=NOW - timedelta(days=1))


def test_an_advisory_policy_does_not_block(
    session: Session, service: ControlService
) -> None:
    """A cap that silently blocks while marked advisory is worse than no cap."""
    organization = _organization(session)
    session.add(
        OrganizationSpendingPolicy(
            organization_id=organization.id,
            currency="NGN",
            period_cap_amount=Decimal("1.00"),
            enforced=False,
            created_at=NOW,
        )
    )
    line = _line(session, organization=organization)
    item = _top_up_item(session, line)
    session.flush()
    service.check_budget(session, item, QUOTE, since=NOW - timedelta(days=1))


def test_a_consumer_order_is_not_subject_to_an_organization_cap(
    session: Session, service: ControlService
) -> None:
    line = _line(session)
    item = _top_up_item(session, line)
    service.check_budget(session, item, QUOTE, since=NOW - timedelta(days=1))


def test_one_policy_per_organization_and_currency(session: Session) -> None:
    organization = _organization(session)
    for _ in range(2):
        session.add(
            OrganizationSpendingPolicy(
                organization_id=organization.id,
                currency="NGN",
                period_cap_amount=Decimal("100.00"),
                created_at=NOW,
            )
        )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
