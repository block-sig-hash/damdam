"""The account area on real PostgreSQL — US-38, chunk 21.

Two strict-TDD categories apply here at once: **sessions** (a revocation that
does not revoke is an account somebody else still has) and **object-level
authorization** (`AGENTS.md` calls a cross-tenant read a breach, not a bug). Both
are database behaviours — the partial unique index on live exports, the
`ON DELETE` rules, the token that revocation actually writes — so none of it is
provable on SQLite.

The deletion tests are the ones to read first. They are written from the
customer's side: what does the product *tell* somebody who cannot delete their
account yet, and does it still refuse when the reason is somebody else's service.
"""

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app import model_registry  # noqa: F401
from app.account.deletion import (
    LIABILITY_PROBES,
    BlockerKind,
    DeletionBlocker,
    register_liability_probe,
)
from app.account.models import (
    AccountExportJob,
    ExportState,
    NotificationCategory,
    NotificationChannel,
    SessionPlatform,
    SupportCategory,
)
from app.account.service import AccountError, AccountService
from app.auth.models import (
    Locale,
    Organization,
    OrganizationType,
    Platform,
    RefreshToken,
    User,
)
from app.catalog.models import LegalEntity, Product, ProductKind
from app.connectivity.models import Entitlement
from app.orders.models import Order, OrderItem, PaymentState
from app.organizations.models import (
    MembershipStatus,
    OrganizationMember,
    OrganizationRole,
)

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="session revocation and ownership are database guarantees",
)

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: float) -> None:
        self.value += timedelta(**kwargs)


@pytest.fixture(scope="module")
def engine():
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    try:
        with Session(
            bind=connection, join_transaction_mode="create_savepoint"
        ) as session:
            yield session
            session.rollback()
    finally:
        transaction.rollback()
        connection.close()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def service(clock):
    return AccountService(clock=clock)


@pytest.fixture(autouse=True)
def no_registered_probes():
    """Each test decides which liability probes exist.

    The registry is global by design — a chunk registers its probe at import —
    so a test that adds one has to put the list back, or the next test inherits
    a blocker it never asked for.
    """
    original = list(LIABILITY_PROBES)
    yield
    LIABILITY_PROBES[:] = original


def _user(session: Session, label: str = "holder") -> User:
    user = User(
        phone_number=f"+23480{uuid4().int % 10**8:08d}",
        first_name=label,
        last_name="Person",
        platform=Platform.ANDROID,
        locale=Locale.EN,
    )
    session.add(user)
    session.flush()
    return user


def _token(session: Session, user: User, clock: Clock) -> RefreshToken:
    token = RefreshToken(
        user_id=user.id,
        token_hash=uuid4().hex + uuid4().hex[:0],
        expires_at=clock() + timedelta(days=30),
        created_at=clock(),
        updated_at=clock(),
    )
    session.add(token)
    session.flush()
    return token


def _order(session: Session, user: User, clock: Clock, amount="5000.00") -> Order:
    entity = LegalEntity(code=f"E{uuid4().hex[:6]}", name="Seller", country="NG")
    session.add(entity)
    session.flush()
    product = Product(
        sku=f"sku-{uuid4().hex[:8]}", name="Nigeria 5GB", kind=ProductKind.DATA
    )
    session.add(product)
    session.flush()
    order = Order(
        reference=f"ORD-{uuid4().hex[:8].upper()}",
        seller_legal_entity_id=entity.id,
        payer_user_id=user.id,
        currency="NGN",
        total_amount=Decimal(amount),
        payment_state=PaymentState.PAID,
        placed_at=clock(),
    )
    session.add(order)
    session.flush()
    session.add(
        OrderItem(
            order_id=order.id,
            product_id=product.id,
            recipient_user_id=user.id,
            quantity=1,
            unit_currency="NGN",
            unit_amount=Decimal(amount),
            description_snapshot=product.name,
        )
    )
    session.flush()
    return order


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


def _member(session, organization, user, role=OrganizationRole.MEMBER):
    membership = OrganizationMember(
        organization_id=organization.id,
        user_id=user.id,
        role=role,
        status=MembershipStatus.ACTIVE,
    )
    session.add(membership)
    session.flush()
    return membership


class TestSessionsAreRecognisableAndRevocable:
    def test_a_session_describes_a_token_without_replacing_it(
        self, session, service, clock
    ):
        user = _user(session)
        token = _token(session, user, clock)

        record = service.record_session(
            session,
            user,
            token,
            platform=SessionPlatform.ANDROID,
            device_label="Pixel 7",
            city="Lagos",
            country="NG",
        )

        assert record.device_label == "Pixel 7"
        assert record.last_seen_country == "NG"
        assert session.get(RefreshToken, token.id).revoked_at is None

    def test_signing_in_again_on_one_device_does_not_add_a_second_row(
        self, session, service, clock
    ):
        """A list with two identical phones is a list nobody dares act on."""
        user = _user(session)
        token = _token(session, user, clock)
        service.record_session(session, user, token, device_label="Pixel 7")
        clock.advance(hours=2)
        service.record_session(session, user, token, device_label="Pixel 7")

        assert len(service.sessions(session, user)) == 1

    def test_revoking_a_session_revokes_the_token_that_authenticates(
        self, session, service, clock
    ):
        """The point of the whole screen. The row is description; this is the act."""
        user = _user(session)
        token = _token(session, user, clock)
        record = service.record_session(session, user, token, device_label="Old phone")

        service.revoke_session(session, user, record.id)

        assert session.get(RefreshToken, token.id).revoked_at == clock()
        assert record.revoked_at == clock()

    def test_one_account_cannot_revoke_another_accounts_session(
        self, session, service, clock
    ):
        """And is told the same thing as if the id did not exist."""
        owner = _user(session, "owner")
        stranger = _user(session, "stranger")
        record = service.record_session(
            session, owner, _token(session, owner, clock), device_label="Owner phone"
        )

        with pytest.raises(AccountError) as excinfo:
            service.revoke_session(session, stranger, record.id)
        assert excinfo.value.code == "session_not_found"
        assert session.get(RefreshToken, record.refresh_token_id).revoked_at is None

    def test_revoking_twice_is_not_an_error_and_does_not_move_the_time(
        self, session, service, clock
    ):
        user = _user(session)
        record = service.record_session(
            session, user, _token(session, user, clock), device_label="Phone"
        )
        service.revoke_session(session, user, record.id)
        first = record.revoked_at
        clock.advance(hours=1)
        service.revoke_session(session, user, record.id)
        assert record.revoked_at == first

    def test_an_expired_token_is_not_shown_as_an_active_session(
        self, session, service, clock
    ):
        user = _user(session)
        token = _token(session, user, clock)
        record = service.record_session(session, user, token, device_label="Old phone")
        token.expires_at = clock() - timedelta(seconds=1)
        session.add(token)
        session.flush()

        listed = service.sessions(session, user)

        assert listed == [record]
        assert record.revoked_at == token.expires_at
        assert record.revoked_reason == "expired"

    def test_signing_out_everywhere_can_keep_the_phone_in_your_hand(
        self, session, service, clock
    ):
        user = _user(session)
        keep = service.record_session(
            session, user, _token(session, user, clock), device_label="This phone"
        )
        gone = service.record_session(
            session, user, _token(session, user, clock), device_label="Lost phone"
        )

        revoked = service.revoke_all_sessions(session, user, except_session_id=keep.id)

        assert revoked == 1
        assert keep.revoked_at is None
        assert gone.revoked_at == clock()


class TestReceiptsComeFromHistory:
    def test_a_receipt_reports_the_order_as_it_was_recorded(
        self, session, service, clock
    ):
        user = _user(session)
        order = _order(session, user, clock, amount="5000.00")

        receipt = service.receipt(session, user, order.id)

        assert receipt.reference == order.reference
        assert receipt.total_amount == Decimal("5000.00")
        assert receipt.currency == "NGN"
        assert len(receipt.lines) == 1
        assert receipt.lines[0].total_amount == Decimal("5000.00")

    def test_catalog_renaming_does_not_rewrite_an_old_receipt(
        self, session, service, clock
    ):
        user = _user(session)
        order = _order(session, user, clock)
        item = session.exec(
            select(OrderItem).where(OrderItem.order_id == order.id)
        ).one()
        product = session.get(Product, item.product_id)
        assert product is not None
        product.name = "Renamed later"
        session.add(product)
        session.flush()

        receipt = service.receipt(session, user, order.id)
        assert receipt.lines[0].description == "Nigeria 5GB"

    def test_another_customers_receipt_is_not_found(self, session, service, clock):
        owner = _user(session, "owner")
        stranger = _user(session, "stranger")
        order = _order(session, owner, clock)

        with pytest.raises(AccountError) as excinfo:
            service.receipt(session, stranger, order.id)
        assert excinfo.value.code == "receipt_not_found"

    def test_the_list_is_this_customers_orders_only(self, session, service, clock):
        owner = _user(session, "owner")
        stranger = _user(session, "stranger")
        _order(session, owner, clock)
        _order(session, owner, clock)
        _order(session, stranger, clock)

        assert len(service.receipts(session, owner)) == 2


class TestSupportCarriesItsReference:
    def test_a_request_about_an_order_records_which_order(
        self, session, service, clock
    ):
        user = _user(session)
        order = _order(session, user, clock)

        request = service.open_support_request(
            session,
            user,
            category=SupportCategory.BILLING,
            subject="Charged twice",
            body="I think I paid for this twice.",
            locale=Locale.EN,
            order_id=order.id,
        )

        assert request.order_id == order.id
        assert order.reference in (request.subject_summary or "")
        assert request.reference.startswith("S-")

    def test_a_request_cannot_be_attached_to_somebody_elses_order(
        self, session, service, clock
    ):
        """Otherwise an agent opens another customer's order in good faith."""
        owner = _user(session, "owner")
        stranger = _user(session, "stranger")
        order = _order(session, owner, clock)

        with pytest.raises(AccountError) as excinfo:
            service.open_support_request(
                session,
                stranger,
                category=SupportCategory.BILLING,
                subject="About this order",
                body="...",
                locale=Locale.EN,
                order_id=order.id,
            )
        assert excinfo.value.code == "order_not_found"

    def test_references_are_unique_across_requests(self, session, service, clock):
        user = _user(session)
        references = {
            service.open_support_request(
                session,
                user,
                category=SupportCategory.OTHER,
                subject=f"Question {index}",
                body="...",
                locale=Locale.EN,
            ).reference
            for index in range(5)
        }
        assert len(references) == 5

    def test_the_customers_locale_is_recorded_with_the_request(
        self, session, service, clock
    ):
        """An agent answering in the wrong language is a second problem."""
        user = _user(session)
        request = service.open_support_request(
            session,
            user,
            category=SupportCategory.ACCOUNT,
            subject="Aide",
            body="...",
            locale=Locale.FR,
        )
        assert request.locale == "fr"

    def test_a_current_holder_can_reference_a_line_bought_by_somebody_else(
        self, session, service, clock
    ):
        buyer = _user(session, "buyer")
        holder = _user(session, "holder")
        order = _order(session, buyer, clock)
        item = session.exec(
            select(OrderItem).where(OrderItem.order_id == order.id)
        ).one()
        entitlement = Entitlement(
            order_item_id=item.id,
            holder_user_id=holder.id,
            product_id=item.product_id,
            data_bytes_total=1024,
            voice_seconds_total=0,
        )
        session.add(entitlement)
        session.flush()

        request = service.open_support_request(
            session,
            holder,
            category=SupportCategory.CONNECTIVITY,
            subject="My work line",
            body="It is not attaching.",
            locale=Locale.EN,
            entitlement_id=entitlement.id,
        )

        assert request.entitlement_id == entitlement.id


class TestNotificationPreferences:
    def test_absence_means_the_default_not_a_decision(self, session, service):
        user = _user(session)
        assert (
            service.may_notify(
                session,
                user,
                NotificationCategory.LOW_BALANCE,
                NotificationChannel.PUSH,
            )
            is True
        )

    def test_an_explicit_no_is_honoured(self, session, service):
        user = _user(session)
        service.set_preference(
            session,
            user,
            category=NotificationCategory.LOW_BALANCE,
            channel=NotificationChannel.PUSH,
            enabled=False,
        )
        assert (
            service.may_notify(
                session,
                user,
                NotificationCategory.LOW_BALANCE,
                NotificationChannel.PUSH,
            )
            is False
        )

    def test_turning_one_channel_off_leaves_the_others_alone(
        self, session, service
    ):
        user = _user(session)
        service.set_preference(
            session,
            user,
            category=NotificationCategory.EXPIRY,
            channel=NotificationChannel.SMS,
            enabled=False,
        )
        assert (
            service.may_notify(
                session, user, NotificationCategory.EXPIRY, NotificationChannel.PUSH
            )
            is True
        )

    def test_setting_the_same_preference_twice_updates_one_row(
        self, session, service, clock
    ):
        user = _user(session)
        first = service.set_preference(
            session,
            user,
            category=NotificationCategory.ORDER_STATUS,
            channel=NotificationChannel.EMAIL,
            enabled=False,
        )
        second = service.set_preference(
            session,
            user,
            category=NotificationCategory.ORDER_STATUS,
            channel=NotificationChannel.EMAIL,
            enabled=True,
        )
        assert first.id == second.id
        assert len(service.preferences(session, user)) == 1

    def test_one_persons_preferences_do_not_reach_another(self, session, service):
        first = _user(session, "first")
        second = _user(session, "second")
        service.set_preference(
            session,
            first,
            category=NotificationCategory.EXPIRY,
            channel=NotificationChannel.PUSH,
            enabled=False,
        )
        assert (
            service.may_notify(
                session, second, NotificationCategory.EXPIRY, NotificationChannel.PUSH
            )
            is True
        )


class TestExport:
    def test_pressing_the_button_twice_returns_one_job(self, session, service):
        user = _user(session)
        first = service.request_export(session, user)
        second = service.request_export(session, user)
        assert first.id == second.id

    def test_a_finished_export_does_not_block_the_next_one(
        self, session, service, clock
    ):
        user = _user(session)
        first = service.request_export(session, user)
        service.complete_export(session, first, "exports/whatever.json")
        second = service.request_export(session, user)
        assert second.id != first.id
        assert first.expires_at == clock() + timedelta(hours=24)

    def test_two_live_exports_are_refused_by_the_database(
        self, session, service, clock
    ):
        """The service returns the existing job; the index is what makes that true."""
        user = _user(session)
        service.request_export(session, user)
        session.add(
            AccountExportJob(
                user_id=user.id,
                state=ExportState.REQUESTED,
                requested_at=clock(),
            )
        )
        with pytest.raises(Exception):  # noqa: B017 - the constraint is the assertion
            session.flush()
        session.rollback()

    def test_the_export_contains_the_customers_own_history(
        self, session, service, clock
    ):
        user = _user(session)
        _order(session, user, clock)
        service.open_support_request(
            session,
            user,
            category=SupportCategory.OTHER,
            subject="A question",
            body="...",
            locale=Locale.EN,
        )
        service.record_session(
            session, user, _token(session, user, clock), device_label="Pixel 7"
        )

        payload = service.build_export(session, user)

        assert payload["account"]["id"] == str(user.id)
        assert len(payload["orders"]) == 1
        assert len(payload["support_requests"]) == 1
        assert payload["devices"][0]["label"] == "Pixel 7"

    def test_the_export_is_only_this_customers_data(self, session, service, clock):
        user = _user(session)
        stranger = _user(session, "stranger")
        _order(session, stranger, clock)

        payload = service.build_export(session, user)
        assert payload["orders"] == []


class TestDeletionAnswersWithReasons:
    def test_an_ordinary_account_may_be_deleted(self, session, service, clock):
        user = _user(session)
        _order(session, user, clock)
        assessment = service.assess_deletion(session, user)
        assert assessment.may_delete is True
        assert assessment.blockers == ()

    def test_an_active_personal_service_blocks_deletion(
        self, session, service, clock
    ):
        user = _user(session)
        order = _order(session, user, clock)
        item = session.exec(
            select(OrderItem).where(OrderItem.order_id == order.id)
        ).one()
        session.add(
            Entitlement(
                order_item_id=item.id,
                holder_user_id=user.id,
                product_id=item.product_id,
                data_bytes_total=1024,
                voice_seconds_total=0,
                expires_at=clock() + timedelta(days=1),
            )
        )
        session.flush()

        assessment = service.assess_deletion(session, user)

        assert assessment.may_delete is False
        assert [blocker.code for blocker in assessment.blockers] == ["active_service"]

    def test_owning_an_organization_with_other_members_blocks_deletion(
        self, session, service
    ):
        """*Do not erase other members' services* — the assignment's words."""
        owner = _user(session, "owner")
        colleague = _user(session, "colleague")
        organization = _organization(session)
        _member(session, organization, owner, OrganizationRole.OWNER)
        _member(session, organization, colleague)

        assessment = service.assess_deletion(session, owner)

        assert assessment.may_delete is False
        assert [blocker.code for blocker in assessment.blockers] == [
            "organization_has_other_members"
        ]
        assert (
            assessment.blockers[0].kind
            is BlockerKind.OTHERS_DEPEND_ON_THIS_ACCOUNT
        )

    def test_a_sole_owner_of_an_empty_organization_is_not_blocked(
        self, session, service
    ):
        """Being an owner is not the reason. Stranding somebody is."""
        owner = _user(session, "owner")
        organization = _organization(session)
        _member(session, organization, owner, OrganizationRole.OWNER)

        assert service.assess_deletion(session, owner).may_delete is True

    def test_a_revoked_colleague_does_not_block_deletion(self, session, service):
        owner = _user(session, "owner")
        former = _user(session, "former")
        organization = _organization(session)
        _member(session, organization, owner, OrganizationRole.OWNER)
        membership = _member(session, organization, former)
        membership.status = MembershipStatus.REVOKED
        # The schema requires a revocation to say when: a membership that is
        # revoked with no time is one nobody can audit.
        membership.revoked_at = NOW
        session.add(membership)
        session.flush()

        assert service.assess_deletion(session, owner).may_delete is True

    def test_a_registered_liability_probe_can_block_deletion(
        self, session, service
    ):
        """The seam V02/V03 plug an active call into once they merge."""

        def probe(_session, _user):
            return (
                DeletionBlocker(
                    BlockerKind.ACTIVE_LIABILITY,
                    "call_in_progress",
                    "one call is still connected",
                ),
            )

        register_liability_probe(probe)
        user = _user(session)

        assessment = service.assess_deletion(session, user)

        assert assessment.may_delete is False
        assert assessment.blockers[0].code == "call_in_progress"

    def test_registering_the_same_probe_twice_reports_one_blocker(
        self, session, service
    ):
        """Import a module twice and a customer should not see two identical reasons."""

        def probe(_session, _user):
            return (
                DeletionBlocker(
                    BlockerKind.ACTIVE_LIABILITY, "call_in_progress", "still connected"
                ),
            )

        register_liability_probe(probe)
        register_liability_probe(probe)
        user = _user(session)

        assert len(service.assess_deletion(session, user).blockers) == 1

    def test_deletion_never_removes_the_order_history_it_is_blocked_on(
        self, session, service, clock
    ):
        """Whatever deletion does, the books survive it."""
        user = _user(session)
        order = _order(session, user, clock)
        session.commit()

        service.assess_deletion(session, user)

        assert session.get(Order, order.id) is not None
        assert (
            session.exec(
                select(OrderItem).where(OrderItem.order_id == order.id)
            ).first()
            is not None
        )
