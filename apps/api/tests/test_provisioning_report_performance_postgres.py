"""AC-20.4: "Generated within 30 seconds for manifests up to 500 rows" is a
real performance requirement, not an assumption -- this measures actual
wall-clock time against a real Postgres database, mirroring the rigor
already applied to other timing-sensitive paths in this codebase (e.g.
the SOS/check-in Postgres concurrency suites)."""

import csv
import io
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.auth.models import (
    HTOApprovalStatus,
    Manifest,
    ManifestOrder,
    ManifestOrderStatus,
    ManifestPilgrim,
    ManifestStatus,
    ManifestValidationStatus,
    Organization,
    OrganizationType,
    PricingTier,
    User,
)
from app.checkins.models import CheckIn
from app.esim.models import EsimAggregator, EsimProfile, EsimProfileStatus
from app.packages.models import Package, PackageSource, PackageStatus
from app.reports.service import ProvisioningReportService
from app.sos.models import SOSAlert

PILGRIM_COUNT = 500


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL AC-20.4 timing test runs in CI",
)
def test_500_row_report_generates_within_30_seconds() -> None:
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    suffix = uuid4().hex[:8]

    with Session(engine) as session:
        organization = Organization(
            org_type=OrganizationType.HTO_OPERATOR,
            name=f"Barakah Hajj Services {suffix}",
            primary_contact_name="Amina Yusuf",
            email=f"operator-{suffix}@example.com",
            password_hash="unused",
            phone_number=f"+23480{suffix}",
            nahcon_licence_number=f"NAHCON-{suffix}",
            email_verified=True,
            approval_status=HTOApprovalStatus.APPROVED,
        )
        session.add(organization)
        session.flush()

        manifest = Manifest(
            organization_id=organization.id,
            name="Hajj Season Flight Batch",
            status=ManifestStatus.PROVISIONED,
            total_rows=PILGRIM_COUNT,
            valid_rows=PILGRIM_COUNT,
        )
        session.add(manifest)
        session.flush()

        tier = PricingTier(
            name=f"Standard-{suffix}",
            usd_reference_price=Decimal("100.00"),
            data_gb=10,
            pstn_minutes=90,
            wholesale_usd_price=Decimal("80.00"),
            ngn_price=Decimal("145000.00"),
        )
        session.add(tier)
        session.flush()

        order = ManifestOrder(
            manifest_id=manifest.id,
            pricing_tier_id=tier.id,
            pilgrim_count=PILGRIM_COUNT,
            wholesale_price_ngn=Decimal("100000.00"),
            total_ngn=Decimal("72500000.00"),
            status=ManifestOrderStatus.PROVISIONED,
            payment_confirmed_at=now - timedelta(days=10),
        )
        session.add(order)
        session.flush()

        # Half the pilgrims are fully activated (user + package + eSIM +
        # check-ins + SOS history) to exercise every join/aggregation this
        # report performs at realistic scale, not just a bulk INSERT of
        # otherwise-empty rows.
        pilgrims = []
        for index in range(PILGRIM_COUNT):
            pilgrims.append(
                ManifestPilgrim(
                    manifest_id=manifest.id,
                    manifest_order_id=order.id,
                    first_name=f"Pilgrim{index}",
                    last_name=f"Perf-{suffix}",
                    phone_number=f"+2349{suffix[:4]}{index:04d}",
                    row_number=index + 2,
                    validation_status=ManifestValidationStatus.VALID,
                )
            )
        session.add_all(pilgrims)
        session.flush()

        users = []
        for index, pilgrim in enumerate(pilgrims):
            if index % 2 == 0:
                user = User(phone_number=pilgrim.phone_number, platform="android")
                session.add(user)
                users.append((pilgrim, user))
        session.flush()
        for pilgrim, user in users:
            pilgrim.user_id = user.id
        session.add_all([pilgrim for pilgrim, _ in users])
        session.flush()

        packages = []
        for _pilgrim, user in users:
            package = Package(
                user_id=user.id,
                pricing_tier_id=tier.id,
                source=PackageSource.HTO_MANIFEST,
                status=PackageStatus.ACTIVE,
                data_gb_total=10,
                data_gb_remaining=Decimal("6.00"),
                pstn_minutes_total=90,
                pstn_minutes_remaining=Decimal("40.00"),
                purchased_at=now - timedelta(days=10),
            )
            packages.append((user, package))
        session.add_all([package for _, package in packages])
        session.flush()

        profiles = [
            EsimProfile(
                package_id=package.id,
                aggregator=EsimAggregator.MONTY_MOBILE,
                iccid=f"890000000000{index:07d}",
                activation_code_lpa="LPA:1$example$code",
                qr_code_url="https://example.com/qr.png",
                status=EsimProfileStatus.ACTIVATED,
            )
            for index, (_, package) in enumerate(packages)
        ]
        session.add_all(profiles)

        checkins = []
        sos_alerts = []
        for user, _ in packages:
            for day in range(3):
                checkins.append(
                    CheckIn(
                        user_id=user.id,
                        client_generated_id=uuid4(),
                        timestamp=now - timedelta(days=9 - day),
                    )
                )
            sos_alerts.append(
                SOSAlert(
                    user_id=user.id,
                    client_generated_id=uuid4(),
                    timestamp=now - timedelta(days=8),
                )
            )
        session.add_all(checkins)
        session.add_all(sos_alerts)
        session.commit()
        organization_id = organization.id

    service = ProvisioningReportService(lambda: now)
    with Session(engine) as session:
        organization = session.get(Organization, organization_id)
        assert organization is not None

        started = time.perf_counter()
        csv_text = service.generate_csv(session, organization, None, None, None)
        elapsed = time.perf_counter() - started

    rows = list(csv.reader(io.StringIO(csv_text)))
    assert len(rows) == PILGRIM_COUNT + 1  # header + every pilgrim
    assert elapsed < 30.0, (
        f"AC-20.4 requires under 30s for 500 rows; took {elapsed:.2f}s"
    )
    print(f"\nAC-20.4: generated a {PILGRIM_COUNT}-row report in {elapsed:.3f}s")
