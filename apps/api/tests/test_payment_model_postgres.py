import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.models import (
    Manifest,
    ManifestOrder,
    Organization,
    OrganizationType,
    PricingTier,
    User,
)
from app.config import Settings
from app.packages.models import (
    Package,
    PackageSource,
    PackageStatus,
    PaymentMethod,
    PaymentProcessor,
    Transaction,
    TransactionStatus,
)
from app.payments.providers import PaymentCheckout, PaymentInitialization
from app.payments.service import PaymentService


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL idempotency constraint test runs in CI",
)
def test_processor_reference_is_globally_unique_across_processors() -> None:
    """AC-09.7: the same reference cannot be recorded twice by either gateway."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    suffix = uuid4().hex
    with Session(engine) as session:
        user = User(phone_number=f"+23480{suffix[:8]}", platform="android")
        tier = PricingTier(
            name=f"Retail-{suffix}",
            usd_reference_price=Decimal("100.00"),
            data_gb=10,
            pstn_minutes=90,
            wholesale_usd_price=Decimal("80.00"),
            ngn_price=Decimal("145000.00"),
        )
        session.add_all([user, tier])
        session.flush()
        package = Package(
            user_id=user.id,
            pricing_tier_id=tier.id,
            source=PackageSource.RETAIL,
            status=PackageStatus.PENDING,
            data_gb_total=10,
            data_gb_remaining=Decimal("0.00"),
            pstn_minutes_total=90,
            pstn_minutes_remaining=Decimal("0.00"),
            purchased_at=datetime.now(timezone.utc),
        )
        session.add(package)
        session.flush()
        session.add(
            Transaction(
                package_id=package.id,
                processor=PaymentProcessor.PAYSTACK,
                processor_reference=f"shared-{suffix}",
                amount_ngn=Decimal("145000.00"),
                status=TransactionStatus.PENDING,
            )
        )
        session.commit()
        session.add(
            Transaction(
                package_id=package.id,
                processor=PaymentProcessor.FLUTTERWAVE,
                processor_reference=f"shared-{suffix}",
                amount_ngn=Decimal("145000.00"),
                status=TransactionStatus.PENDING,
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL manual-processor constraint test runs in CI",
)
def test_null_processor_is_reserved_for_internal_hto_invoice_references() -> None:
    """Processor-neutral evidence cannot be created for an unrelated payment."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            Transaction(
                processor=None,
                processor_reference=f"not-an-hto-{uuid4().hex}",
                amount_ngn=Decimal("160000.00"),
                payment_method=PaymentMethod.INVOICE,
                status=TransactionStatus.SUCCESS,
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL HTO transaction constraint test runs in CI",
)
def test_manifest_order_has_at_most_one_processor_neutral_transaction() -> None:
    """AC-06.5: retries cannot duplicate retained manual-payment evidence."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    suffix = uuid4().hex
    with Session(engine) as session:
        organization = Organization(
            org_type=OrganizationType.HTO_OPERATOR,
            name=f"Retention HTO {suffix}",
            primary_contact_name="Amina Yusuf",
            email=f"retention-{suffix}@example.com",
            password_hash="unused",
            phone_number=f"+23480{suffix[:8]}",
            nahcon_licence_number=f"NAHCON-{suffix}",
        )
        session.add(organization)
        session.commit()
        session.refresh(organization)
        manifest = Manifest(organization_id=organization.id)
        tier = PricingTier(
            name=f"HTO-{suffix}",
            usd_reference_price=Decimal("100.00"),
            data_gb=5,
            pstn_minutes=30,
            wholesale_usd_price=Decimal("80.00"),
            ngn_price=Decimal("160000.00"),
        )
        session.add_all([manifest, tier])
        session.commit()
        session.refresh(manifest)
        session.refresh(tier)
        order = ManifestOrder(
            manifest_id=manifest.id,
            pricing_tier_id=tier.id,
            pilgrim_count=1,
            wholesale_price_ngn=Decimal("128000.00"),
            total_ngn=Decimal("160000.00"),
        )
        session.add(order)
        session.commit()
        session.refresh(order)
        session.add(
            Transaction(
                manifest_order_id=order.id,
                processor=None,
                processor_reference=f"hto-first-{suffix}",
                amount_ngn=order.total_ngn,
                payment_method=PaymentMethod.INVOICE,
                status=TransactionStatus.SUCCESS,
            )
        )
        session.commit()
        session.add(
            Transaction(
                manifest_order_id=order.id,
                processor=None,
                processor_reference=f"hto-second-{suffix}",
                amount_ngn=order.total_ngn,
                payment_method=PaymentMethod.INVOICE,
                status=TransactionStatus.SUCCESS,
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()


@dataclass
class _FakePaymentProvider:
    name: str

    def initialize(self, payment: PaymentInitialization) -> PaymentCheckout:
        return PaymentCheckout(
            processor=self.name,
            processor_reference=payment.reference,
            checkout_url=f"https://checkout.example/{self.name}/{payment.reference}",
        )


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL FK-ordering check runs in CI",
)
def test_initialize_purchase_against_real_postgres_does_not_violate_fk() -> None:
    """Package and Transaction have no ORM relationship() between them, so
    SQLAlchemy's flush ordering can't infer that packages must insert
    before transactions -- the same class of bug found and fixed in
    ActivationService.redeem() (US-25). PaymentService.initialize() adds
    both in the same flush; this guards that real Postgres (which enforces
    the FK, unlike SQLite) never sees the child row before its parent."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    suffix = uuid4().hex
    with Session(engine) as session:
        user = User(phone_number=f"+23481{suffix[:8]}", platform="android")
        tier = PricingTier(
            name=f"Retail-{suffix}",
            usd_reference_price=Decimal("100.00"),
            data_gb=10,
            pstn_minutes=90,
            wholesale_usd_price=Decimal("80.00"),
            ngn_price=Decimal("145000.00"),
            active=True,
        )
        session.add_all([user, tier])
        session.commit()
        session.refresh(user)
        session.refresh(tier)
        user_id, tier_id = user.id, tier.id

    now = datetime.now(timezone.utc)
    service = PaymentService(
        settings=Settings(),
        providers={"paystack": _FakePaymentProvider("paystack")},
        notifications=None,
        clock=lambda: now,
        esim_scheduler=None,
        chaining=None,
        audit=None,
    )

    with Session(engine) as session:
        user = session.get(User, user_id)
        result = service.initialize(session, user, tier_id, None)

    with Session(engine) as session:
        package = session.get(Package, result.package_id)
        assert package is not None
        transaction = session.exec(
            select(Transaction).where(Transaction.package_id == result.package_id)
        ).one()
        assert transaction.processor_reference == result.checkout.processor_reference
