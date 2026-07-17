import csv
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import jwt
from fastapi.testclient import TestClient

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
from app.sos.models import SOSAlert


def operator_headers(settings, clock, organization_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": str(organization_id),
            "aud": "hto_dashboard",
            "type": "access",
            "iat": clock(),
            "exp": clock() + timedelta(minutes=15),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _organization(session_factory, name: str) -> Organization:
    org = Organization(
        org_type=OrganizationType.HTO_OPERATOR,
        name=name,
        primary_contact_name="Amina Yusuf",
        email=f"{name.lower().replace(' ', '-')}@example.com",
        password_hash="unused",
        phone_number=f"+2348{uuid4().hex[:9]}",
        nahcon_licence_number=f"NAHCON-{uuid4().hex[:8]}",
        email_verified=True,
        approval_status=HTOApprovalStatus.APPROVED,
    )
    with session_factory() as session:
        session.add(org)
        session.commit()
        session.refresh(org)
        session.expunge(org)
    return org


def _tier(session_factory, name: str = "Standard") -> PricingTier:
    tier = PricingTier(
        name=name,
        usd_reference_price=Decimal("100.00"),
        data_gb=10,
        pstn_minutes=90,
        wholesale_usd_price=Decimal("80.00"),
        ngn_price=Decimal("145000.00"),
    )
    with session_factory() as session:
        session.add(tier)
        session.commit()
        session.refresh(tier)
        session.expunge(tier)
    return tier


def _provisioned_pilgrim(
    session_factory,
    organization_id: UUID,
    tier_id: UUID,
    *,
    payment_confirmed_at: datetime,
    manifest_name: str = "Flight NAF203",
    with_activity: bool = False,
    check_in_count: int = 0,
    sos_event_count: int = 0,
    esim_status: EsimProfileStatus | None = None,
    first_name: str = "Aisha",
) -> tuple[UUID, ManifestPilgrim]:
    """Builds one fully-provisioned pilgrim (manifest -> order[PROVISIONED]
    -> pilgrim), optionally with a linked user/package/activity so the
    report's aggregation fields can be exercised. Returns (manifest_id,
    the persisted-then-expunged pilgrim)."""
    suffix = uuid4().hex[:10]
    with session_factory() as session:
        manifest = Manifest(
            organization_id=organization_id,
            name=manifest_name,
            status=ManifestStatus.PROVISIONED,
            total_rows=1,
            valid_rows=1,
        )
        session.add(manifest)
        session.flush()
        order = ManifestOrder(
            manifest_id=manifest.id,
            pricing_tier_id=tier_id,
            pilgrim_count=1,
            wholesale_price_ngn=Decimal("100000.00"),
            total_ngn=Decimal("145000.00"),
            status=ManifestOrderStatus.PROVISIONED,
            payment_confirmed_at=payment_confirmed_at,
        )
        session.add(order)
        session.flush()
        pilgrim = ManifestPilgrim(
            manifest_id=manifest.id,
            manifest_order_id=order.id,
            first_name=first_name,
            last_name=f"Bello-{suffix}",
            phone_number=f"+2348{suffix}",
            row_number=2,
            validation_status=ManifestValidationStatus.VALID,
        )
        if with_activity:
            user = User(phone_number=pilgrim.phone_number, platform="android")
            session.add(user)
            session.flush()
            pilgrim.user_id = user.id
            package = Package(
                user_id=user.id,
                pricing_tier_id=tier_id,
                source=PackageSource.HTO_MANIFEST,
                status=PackageStatus.ACTIVE,
                data_gb_total=10,
                data_gb_remaining=Decimal("10.00"),
                pstn_minutes_total=90,
                pstn_minutes_remaining=Decimal("90.00"),
                purchased_at=payment_confirmed_at,
            )
            session.add(package)
            session.flush()
            if esim_status is not None:
                session.add(
                    EsimProfile(
                        package_id=package.id,
                        aggregator=EsimAggregator.MONTY_MOBILE,
                        iccid="8900000000000000001",
                        activation_code_lpa="LPA:1$example$code",
                        qr_code_url="https://example.com/qr.png",
                        status=esim_status,
                    )
                )
            for i in range(check_in_count):
                session.add(
                    CheckIn(
                        user_id=user.id,
                        client_generated_id=uuid4(),
                        timestamp=payment_confirmed_at + timedelta(days=i + 1),
                    )
                )
            for _ in range(sos_event_count):
                session.add(
                    SOSAlert(
                        user_id=user.id,
                        client_generated_id=uuid4(),
                        timestamp=payment_confirmed_at + timedelta(days=1),
                    )
                )
        session.add(pilgrim)
        session.commit()
        session.refresh(pilgrim)
        session.refresh(manifest)
        manifest_id = manifest.id
        session.expunge(pilgrim)
        session.expunge(manifest)
    return manifest_id, pilgrim


def _download(
    client: TestClient, headers: dict[str, str], **params: str
) -> list[list[str]]:
    response = client.get(
        "/v1/hto/reports/provisioning.csv", headers=headers, params=params
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(response.text)))
    return rows


def test_csv_header_and_field_list_matches_ac_20_2(
    api, session_factory, settings, clock
) -> None:
    """AC-20.1/20.2: CSV download with exactly the specified per-pilgrim
    fields, in order."""
    org = _organization(session_factory, "Barakah Hajj Services")
    tier = _tier(session_factory)
    purchased = datetime(2026, 6, 1, tzinfo=timezone.utc)
    _provisioned_pilgrim(
        session_factory,
        org.id,
        tier.id,
        payment_confirmed_at=purchased,
        with_activity=True,
        check_in_count=3,
        sos_event_count=1,
        esim_status=EsimProfileStatus.ACTIVATED,
    )
    client = TestClient(api)

    rows = _download(client, operator_headers(settings, clock, org.id))

    assert rows[0] == [
        "name",
        "phone",
        "tier",
        "purchase_date",
        "esim_status",
        "check_in_count",
        "sos_events",
    ]
    assert len(rows) == 2
    name, phone, tier_name, purchase_date, esim_status, check_ins, sos_events = rows[1]
    assert name.startswith("Aisha Bello-")
    assert phone.startswith("+2348")
    assert tier_name == "Standard"
    assert purchase_date == "2026-06-01"
    assert esim_status == "activated"
    assert check_ins == "3"
    assert sos_events == "1"


def test_pilgrim_without_activity_reports_zero_counts_and_not_checked(
    api, session_factory, settings, clock
) -> None:
    org = _organization(session_factory, "Barakah Hajj Services")
    tier = _tier(session_factory)
    _provisioned_pilgrim(
        session_factory,
        org.id,
        tier.id,
        payment_confirmed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        with_activity=False,
    )
    client = TestClient(api)

    rows = _download(client, operator_headers(settings, clock, org.id))

    _, _, _, _, esim_status, check_ins, sos_events = rows[1]
    assert esim_status == "not_checked"
    assert check_ins == "0"
    assert sos_events == "0"


def test_unprovisioned_orders_and_unrelated_manifests_are_excluded(
    api, session_factory, settings, clock
) -> None:
    """Only manifest_orders that have actually reached PROVISIONED belong
    in a *provisioning* report -- data-model.md §6.14 defines that status
    as every selected pilgrim having a delivered activation link."""
    org = _organization(session_factory, "Barakah Hajj Services")
    tier = _tier(session_factory)
    _provisioned_pilgrim(
        session_factory,
        org.id,
        tier.id,
        payment_confirmed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    with session_factory() as session:
        manifest = Manifest(
            organization_id=org.id,
            name="Still Awaiting Payment",
            status=ManifestStatus.VALIDATED,
        )
        session.add(manifest)
        session.flush()
        order = ManifestOrder(
            manifest_id=manifest.id,
            pricing_tier_id=tier.id,
            pilgrim_count=1,
            wholesale_price_ngn=Decimal("100000.00"),
            total_ngn=Decimal("145000.00"),
            status=ManifestOrderStatus.AWAITING_PAYMENT,
        )
        session.add(order)
        session.flush()
        session.add(
            ManifestPilgrim(
                manifest_id=manifest.id,
                manifest_order_id=order.id,
                first_name="Not",
                last_name="Provisioned",
                phone_number="+2348099999999",
                row_number=2,
                validation_status=ManifestValidationStatus.VALID,
            )
        )
        session.commit()
    client = TestClient(api)

    rows = _download(client, operator_headers(settings, clock, org.id))

    assert len(rows) == 2  # header + the one PROVISIONED pilgrim only
    assert "Not Provisioned" not in rows[1][0]


def test_filter_by_manifest_id(api, session_factory, settings, clock) -> None:
    org = _organization(session_factory, "Barakah Hajj Services")
    tier = _tier(session_factory)
    manifest_a, _ = _provisioned_pilgrim(
        session_factory,
        org.id,
        tier.id,
        payment_confirmed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        manifest_name="Flight A",
    )
    manifest_b, _ = _provisioned_pilgrim(
        session_factory,
        org.id,
        tier.id,
        payment_confirmed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        manifest_name="Flight B",
    )
    client = TestClient(api)

    rows = _download(
        client,
        operator_headers(settings, clock, org.id),
        manifest_id=str(manifest_a),
    )

    assert len(rows) == 2
    all_rows = _download(client, operator_headers(settings, clock, org.id))
    assert len(all_rows) == 3  # header + both manifests' pilgrims


def test_filter_by_date_range(api, session_factory, settings, clock) -> None:
    org = _organization(session_factory, "Barakah Hajj Services")
    tier = _tier(session_factory)
    _provisioned_pilgrim(
        session_factory,
        org.id,
        tier.id,
        payment_confirmed_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        manifest_name="May batch",
    )
    _provisioned_pilgrim(
        session_factory,
        org.id,
        tier.id,
        payment_confirmed_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
        manifest_name="June batch",
    )
    client = TestClient(api)
    headers = operator_headers(settings, clock, org.id)

    june_only = _download(
        client,
        headers,
        date_from=date(2026, 6, 1).isoformat(),
        date_to=date(2026, 6, 30).isoformat(),
    )
    assert len(june_only) == 2
    assert june_only[1][3] == "2026-06-15"

    both = _download(client, headers, date_from=date(2026, 1, 1).isoformat())
    assert len(both) == 3


def test_cross_tenant_isolation_one_hto_cannot_see_another_hto_report_data(
    api, session_factory, settings, clock
) -> None:
    """Negative test: this is the actual security property AC-20.3's
    filtering must guarantee, mirroring GET /hto/pilgrims's org-scoping
    pattern -- filtered at the query level (Manifest.organization_id),
    not just hidden in a UI."""
    org_a = _organization(session_factory, "Barakah Hajj Services")
    org_b = _organization(session_factory, "Al-Noor Travels")
    tier = _tier(session_factory)
    _provisioned_pilgrim(
        session_factory,
        org_a.id,
        tier.id,
        payment_confirmed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        manifest_name="Org A Flight",
        with_activity=True,
    )
    manifest_b, _ = _provisioned_pilgrim(
        session_factory,
        org_b.id,
        tier.id,
        payment_confirmed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        manifest_name="Org B Flight",
        with_activity=True,
    )
    client = TestClient(api)

    # Org A's own report only contains its own pilgrim.
    org_a_rows = _download(client, operator_headers(settings, clock, org_a.id))
    assert len(org_a_rows) == 2
    assert "Org A" not in org_a_rows[1][0]  # sanity: not literally the manifest name
    assert org_a_rows[1][1] not in ("",)

    # Org A cannot pull Org B's data even by guessing Org B's manifest_id
    # directly in the query string.
    org_a_targeting_b = _download(
        client,
        operator_headers(settings, clock, org_a.id),
        manifest_id=str(manifest_b),
    )
    assert org_a_targeting_b == [org_a_rows[0]]  # header only, no rows

    # Org B's own report, for contrast, does see its own pilgrim.
    org_b_rows = _download(client, operator_headers(settings, clock, org_b.id))
    assert len(org_b_rows) == 2


def test_requires_hto_auth(api) -> None:
    client = TestClient(api)
    response = client.get("/v1/hto/reports/provisioning.csv")
    assert response.status_code == 401


def test_names_that_look_like_spreadsheet_formulas_are_defused(
    api, session_factory, settings, clock
) -> None:
    """Pilgrim names come from an HTO-uploaded manifest CSV -- untrusted
    input -- and this report is meant to be opened in Excel/Sheets. A name
    starting with =, +, -, or @ would otherwise be interpreted as a
    formula (CSV/formula injection, OWASP) once opened."""
    org = _organization(session_factory, "Barakah Hajj Services")
    tier = _tier(session_factory)
    _provisioned_pilgrim(
        session_factory,
        org.id,
        tier.id,
        payment_confirmed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        first_name='=HYPERLINK("http://evil.example","click")',
    )
    client = TestClient(api)

    rows = _download(client, operator_headers(settings, clock, org.id))

    assert rows[1][0].startswith("'=HYPERLINK")
