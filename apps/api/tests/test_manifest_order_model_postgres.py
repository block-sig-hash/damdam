import os
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.models import (
    DailyPriceCache,
    Manifest,
    ManifestOrder,
    ManifestPilgrim,
    ManifestStatus,
    ManifestValidationStatus,
    Organization,
    OrganizationType,
    PricingTier,
)


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL constraint test runs in CI",
)
def test_manifest_supports_multiple_orders_and_restricts_ordered_pilgrim() -> None:
    """AC-06.6: one manifest has many durable, pilgrim-linked orders."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    suffix = uuid4().hex
    with Session(engine) as session:
        organization = Organization(
            org_type=OrganizationType.HTO_OPERATOR,
            name="Bulk Purchase HTO",
            primary_contact_name="Amina Yusuf",
            email=f"bulk-{suffix}@example.com",
            password_hash="hash",
            phone_number="+2348012345678",
            nahcon_licence_number=f"NAHCON-{suffix}",
        )
        session.add(organization)
        session.flush()
        manifest = Manifest(
            organization_id=organization.id,
            name="Two-order manifest",
            status=ManifestStatus.VALIDATED,
            total_rows=1,
            valid_rows=1,
        )
        tier = PricingTier(
            name=f"Basic-{suffix}",
            usd_reference_price=Decimal("100.00"),
            data_gb=5,
            pstn_minutes=30,
            wholesale_usd_price=Decimal("80.00"),
        )
        session.add_all([manifest, tier])
        session.flush()
        session.add(
            DailyPriceCache(
                pricing_tier_id=tier.id,
                date=date(2026, 7, 14),
                ngn_price=Decimal("160000.00"),
                fx_rate_used=Decimal("1600.0000"),
            )
        )
        first_order = ManifestOrder(
            manifest_id=manifest.id,
            pricing_tier_id=tier.id,
            pilgrim_count=1,
            wholesale_price_ngn=Decimal("128000.00"),
            total_ngn=Decimal("128000.00"),
        )
        second_order = ManifestOrder(
            manifest_id=manifest.id,
            pricing_tier_id=tier.id,
            pilgrim_count=1,
            wholesale_price_ngn=Decimal("128000.00"),
            total_ngn=Decimal("128000.00"),
        )
        session.add_all([first_order, second_order])
        session.flush()
        pilgrim = ManifestPilgrim(
            manifest_id=manifest.id,
            first_name="Aisha",
            last_name="Bello",
            phone_number="+2348012345678",
            row_number=2,
            validation_status=ManifestValidationStatus.VALID,
            manifest_order_id=first_order.id,
        )
        session.add(pilgrim)
        session.commit()

        assert len(
            session.exec(
                select(ManifestOrder).where(
                    ManifestOrder.manifest_id == manifest.id
                )
            ).all()
        ) == 2

        first_order_id = first_order.id
        session.delete(first_order)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        assert session.get(ManifestOrder, first_order_id) is not None


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL constraint test runs in CI",
)
def test_manifest_order_rejects_non_positive_amounts() -> None:
    """Invoice snapshots cannot persist empty or negative purchases."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    suffix = uuid4().hex
    with Session(engine) as session:
        organization = Organization(
            org_type=OrganizationType.HTO_OPERATOR,
            name="Invalid Order HTO",
            primary_contact_name="Amina Yusuf",
            email=f"invalid-order-{suffix}@example.com",
            password_hash="hash",
            phone_number="+2348012345678",
            nahcon_licence_number=f"NAHCON-{suffix}",
        )
        session.add(organization)
        session.flush()
        manifest = Manifest(organization_id=organization.id)
        tier = PricingTier(
            name=f"Invalid-{suffix}",
            usd_reference_price=Decimal("100.00"),
            data_gb=1,
            pstn_minutes=0,
            wholesale_usd_price=Decimal("80.00"),
        )
        session.add_all([manifest, tier])
        session.flush()
        session.add(
            ManifestOrder(
                manifest_id=manifest.id,
                pricing_tier_id=tier.id,
                pilgrim_count=0,
                wholesale_price_ngn=Decimal("0.00"),
                total_ngn=Decimal("0.00"),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
