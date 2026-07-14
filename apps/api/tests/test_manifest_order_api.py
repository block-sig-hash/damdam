from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.auth.models import (
    AdminUser,
    DailyPriceCache,
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
)
from app.main import create_app
from app.manifests.invoices import InvoiceStorage
from app.manifests.orders import ManifestOrderService, ProvisioningScheduler
from app.notifications.service import NotificationError


class MemoryInvoiceStorage(InvoiceStorage):
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, contents: bytes) -> None:
        self.objects[key] = contents

    def get(self, key: str) -> bytes:
        return self.objects[key]


class FakeProvisioningScheduler(ProvisioningScheduler):
    def __init__(self) -> None:
        self.calls: list[UUID] = []
        self.fail = False

    def schedule(self, order_id: UUID) -> None:
        if self.fail:
            raise RuntimeError("queue unavailable")
        self.calls.append(order_id)


class OrderEmailSender:
    def __init__(self) -> None:
        self.invoices: list[tuple[str, str, str, Decimal, bytes]] = []
        self.fail_invoice = False

    def send_verification(self, email: str, name: str, url: str) -> None:
        del email, name, url

    def send_approval(self, email: str, name: str) -> None:
        del email, name

    def send_invoice(
        self,
        email: str,
        operator_name: str,
        order_id: str,
        total_ngn: Decimal,
        pdf: bytes,
    ) -> None:
        if self.fail_invoice:
            raise NotificationError("email unavailable")
        self.invoices.append((email, operator_name, order_id, total_ngn, pdf))


class OrderWhatsAppSender:
    def __init__(self) -> None:
        self.activations: list[tuple[str, str, str, str]] = []
        self.fail_numbers: set[str] = set()

    def send_approval(self, phone_number: str, name: str) -> None:
        del phone_number, name

    def send_family_nomination(self, phone_number: str) -> None:
        del phone_number

    def send_activation(
        self, phone_number: str, pilgrim_name: str, tier_name: str, url: str
    ) -> None:
        if phone_number in self.fail_numbers:
            raise NotificationError("WhatsApp unavailable")
        self.activations.append((phone_number, pilgrim_name, tier_name, url))


@pytest.fixture
def order_dependencies():
    return (
        MemoryInvoiceStorage(),
        FakeProvisioningScheduler(),
        OrderEmailSender(),
        OrderWhatsAppSender(),
    )


@pytest.fixture
def order_api(
    settings,
    redis_client,
    providers,
    scheduler,
    clock,
    session_factory,
    order_dependencies,
):
    storage, provisioning, email, whatsapp = order_dependencies
    return create_app(
        settings=settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
        email_sender=email,
        whatsapp_sender=whatsapp,
        invoice_storage=storage,
        provisioning_scheduler=provisioning,
    )


def create_operator(session_factory, email: str) -> Organization:
    organization = Organization(
        org_type=OrganizationType.HTO_OPERATOR,
        name=f"{email} HTO",
        primary_contact_name="Amina Yusuf",
        email=email,
        password_hash="unused",
        phone_number="+2348012345678",
        nahcon_licence_number=f"NAHCON-{uuid4()}",
        email_verified=True,
        approval_status=HTOApprovalStatus.APPROVED,
    )
    with session_factory() as session:
        session.add(organization)
        session.commit()
        session.refresh(organization)
        session.expunge(organization)
    return organization


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


def admin_headers(settings, clock, admin_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": str(admin_id),
            "aud": "admin",
            "type": "access",
            "iat": clock(),
            "exp": clock() + timedelta(minutes=15),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def create_manifest_data(
    session_factory, organization_id: UUID, count: int = 5
) -> tuple[Manifest, list[ManifestPilgrim]]:
    manifest = Manifest(
        organization_id=organization_id,
        name="Flight NAF203",
        status=ManifestStatus.VALIDATED,
        total_rows=count,
        valid_rows=count,
    )
    with session_factory() as session:
        session.add(manifest)
        session.flush()
        rows = [
            ManifestPilgrim(
                manifest_id=manifest.id,
                first_name=f"Pilgrim{index}",
                last_name="Test",
                phone_number=f"+2348012345{index:02d}",
                row_number=index + 2,
                validation_status=ManifestValidationStatus.VALID,
            )
            for index in range(count)
        ]
        session.add_all(rows)
        session.commit()
        session.refresh(manifest)
        for row in rows:
            session.refresh(row)
            session.expunge(row)
        session.expunge(manifest)
    return manifest, rows


def create_pricing(session_factory, today) -> tuple[PricingTier, PricingTier]:
    basic = PricingTier(
        name="Basic",
        usd_reference_price=Decimal("100.00"),
        data_gb=5,
        pstn_minutes=30,
        wholesale_usd_price=Decimal("80.00"),
    )
    family = PricingTier(
        name="Family",
        usd_reference_price=Decimal("150.00"),
        data_gb=10,
        pstn_minutes=60,
        is_group_tier=True,
        min_group_size=2,
        max_group_size=8,
        wholesale_usd_price=Decimal("110.00"),
    )
    with session_factory() as session:
        session.add_all([basic, family])
        session.flush()
        session.add_all(
            [
                DailyPriceCache(
                    pricing_tier_id=basic.id,
                    date=today,
                    ngn_price=Decimal("160000.00"),
                    fx_rate_used=Decimal("1600.0000"),
                ),
                DailyPriceCache(
                    pricing_tier_id=family.id,
                    date=today,
                    ngn_price=Decimal("240000.00"),
                    fx_rate_used=Decimal("1600.0000"),
                ),
            ]
        )
        session.commit()
        session.refresh(basic)
        session.refresh(family)
        session.expunge(basic)
        session.expunge(family)
    return basic, family


def test_family_and_individual_orders_preserve_unordered_pool_and_prices(
    order_api,
    session_factory,
    settings,
    clock,
    order_dependencies,
) -> None:
    """AC-06.1/2/3/4/6: group, price, invoice, and repeat subsets."""
    storage, _, email, _ = order_dependencies
    operator = create_operator(session_factory, "orders@example.com")
    manifest, rows = create_manifest_data(session_factory, operator.id)
    basic, family = create_pricing(session_factory, clock().date())
    headers = operator_headers(settings, clock, operator.id)
    client = TestClient(order_api)

    pricing = client.get("/v1/hto/pricing-tiers", headers=headers)
    assert pricing.status_code == 200
    assert client.get("/v1/hto/pricing-tiers").status_code == 401
    basic_price = next(
        tier for tier in pricing.json()["tiers"] if tier["name"] == "Basic"
    )
    assert basic_price["retail_price_ngn"] == 160000
    assert basic_price["wholesale_price_ngn"] == 128000
    assert basic_price["estimated_margin_ngn"] == 32000

    family_ids = [str(row.id) for row in rows[:3]]
    grouped = client.post(
        f"/v1/hto/manifests/{manifest.id}/group",
        headers=headers,
        json={"manifest_pilgrim_ids": family_ids, "group_size": 3},
    )
    assert grouped.status_code == 200
    group_id = grouped.json()["family_group_id"]

    family_order = client.post(
        f"/v1/hto/manifests/{manifest.id}/order",
        headers=headers,
        json={"pricing_tier_id": str(family.id), "manifest_pilgrim_ids": family_ids},
    )
    assert family_order.status_code == 200
    assert family_order.json()["total_ngn"] == 528000
    order_id = family_order.json()["manifest_order_id"]
    assert len(email.invoices) == 1
    assert email.invoices[0][4].startswith(b"%PDF-1.4")
    assert len(storage.objects) == 1

    detail = client.get(
        f"/v1/hto/manifests/{manifest.id}/order/{order_id}", headers=headers
    )
    assert detail.status_code == 200
    assert detail.json()["wholesale_price_ngn"] == 176000

    repeated = client.post(
        f"/v1/hto/manifests/{manifest.id}/order",
        headers=headers,
        json={"pricing_tier_id": str(family.id), "manifest_pilgrim_ids": family_ids},
    )
    assert repeated.status_code == 200
    assert repeated.json()["manifest_order_id"] == order_id
    assert len(email.invoices) == 1

    conflicting = client.post(
        f"/v1/hto/manifests/{manifest.id}/order",
        headers=headers,
        json={"pricing_tier_id": str(basic.id), "manifest_pilgrim_ids": family_ids},
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["details"]["pilgrim_ids"] == family_ids

    invoice = client.get(
        f"/v1/hto/manifests/{manifest.id}/order/{order_id}/invoice",
        headers=headers,
    )
    assert invoice.status_code == 200
    assert invoice.headers["content-type"] == "application/pdf"
    assert client.get(
        f"/v1/hto/manifests/{manifest.id}/order/{uuid4()}/invoice",
        headers=headers,
    ).status_code == 404

    remaining = client.get(
        f"/v1/hto/manifests/{manifest.id}/unordered-pilgrims", headers=headers
    )
    assert [item["id"] for item in remaining.json()["pilgrims"]] == [
        str(rows[3].id), str(rows[4].id)
    ]

    for row in rows[3:]:
        placed = client.post(
            f"/v1/hto/manifests/{manifest.id}/order",
            headers=headers,
            json={
                "pricing_tier_id": str(basic.id),
                "manifest_pilgrim_ids": [str(row.id)],
            },
        )
        assert placed.status_code == 200

    listing = client.get(
        f"/v1/hto/manifests/{manifest.id}/orders", headers=headers
    )
    assert listing.status_code == 200
    assert len(listing.json()["orders"]) == 3
    with session_factory() as session:
        stored_manifest = session.get(Manifest, manifest.id)
        assert stored_manifest is not None
        assert stored_manifest.status == ManifestStatus.PROVISIONED
        stored_group = session.exec(
            select(ManifestPilgrim).where(
                ManifestPilgrim.family_group_id == UUID(group_id)
            )
        ).all()
        assert len(stored_group) == 3


def test_family_group_rules_and_cross_tenant_isolation(
    order_api, session_factory, settings, clock
) -> None:
    """§6.4 and tenant isolation: complete 2–8 member groups only."""
    owner = create_operator(session_factory, "owner-groups@example.com")
    attacker = create_operator(session_factory, "attacker-groups@example.com")
    manifest, rows = create_manifest_data(session_factory, owner.id, 3)
    basic, family = create_pricing(session_factory, clock().date())
    owner_headers = operator_headers(settings, clock, owner.id)
    attacker_headers = operator_headers(settings, clock, attacker.id)
    client = TestClient(order_api)

    forbidden = client.get(
        f"/v1/hto/manifests/{manifest.id}/unordered-pilgrims",
        headers=attacker_headers,
    )
    assert forbidden.status_code == 404
    forbidden_group = client.post(
        f"/v1/hto/manifests/{manifest.id}/group",
        headers=attacker_headers,
        json={
            "manifest_pilgrim_ids": [str(rows[0].id), str(rows[1].id)],
            "group_size": 2,
        },
    )
    assert forbidden_group.status_code == 404
    wrong_size = client.post(
        f"/v1/hto/manifests/{manifest.id}/group",
        headers=owner_headers,
        json={
            "manifest_pilgrim_ids": [str(rows[0].id), str(rows[1].id)],
            "group_size": 3,
        },
    )
    assert wrong_size.status_code == 400

    grouped = client.post(
        f"/v1/hto/manifests/{manifest.id}/group",
        headers=owner_headers,
        json={
            "manifest_pilgrim_ids": [str(rows[0].id), str(rows[1].id)],
            "group_size": 2,
        },
    )
    group_id = grouped.json()["family_group_id"]
    incomplete = client.post(
        f"/v1/hto/manifests/{manifest.id}/order",
        headers=owner_headers,
        json={
            "pricing_tier_id": str(family.id),
            "manifest_pilgrim_ids": [str(rows[0].id)],
        },
    )
    assert incomplete.status_code == 400
    wrong_tier = client.post(
        f"/v1/hto/manifests/{manifest.id}/order",
        headers=owner_headers,
        json={
            "pricing_tier_id": str(basic.id),
            "manifest_pilgrim_ids": [str(rows[0].id), str(rows[1].id)],
        },
    )
    assert wrong_tier.status_code == 400

    missing_update = client.put(
        f"/v1/hto/manifests/{manifest.id}/group/{uuid4()}",
        headers=owner_headers,
        json={
            "manifest_pilgrim_ids": [str(rows[0].id), str(rows[1].id)],
            "group_size": 2,
        },
    )
    assert missing_update.status_code == 404

    updated = client.put(
        f"/v1/hto/manifests/{manifest.id}/group/{group_id}",
        headers=owner_headers,
        json={
            "manifest_pilgrim_ids": [str(row.id) for row in rows],
            "group_size": 3,
        },
    )
    assert updated.status_code == 200
    deleted = client.delete(
        f"/v1/hto/manifests/{manifest.id}/group/{group_id}",
        headers=owner_headers,
    )
    assert deleted.status_code == 204
    assert client.delete(
        f"/v1/hto/manifests/{manifest.id}/group/{group_id}",
        headers=owner_headers,
    ).status_code == 404

    placed = client.post(
        f"/v1/hto/manifests/{manifest.id}/order",
        headers=owner_headers,
        json={
            "pricing_tier_id": str(basic.id),
            "manifest_pilgrim_ids": [str(rows[0].id)],
        },
    )
    assert placed.status_code == 200
    order_id = placed.json()["manifest_order_id"]
    assert client.get(
        f"/v1/hto/manifests/{manifest.id}/orders", headers=attacker_headers
    ).status_code == 404
    assert client.get(
        f"/v1/hto/manifests/{manifest.id}/order/{order_id}",
        headers=attacker_headers,
    ).status_code == 404
    assert client.get(
        f"/v1/hto/manifests/{manifest.id}/order/{order_id}/invoice",
        headers=attacker_headers,
    ).status_code == 404


def test_invoice_email_failure_retries_without_duplicate_order(
    order_api, session_factory, settings, clock, order_dependencies
) -> None:
    """AC-06.4/payment idempotency: external email failure is resumable."""
    _, _, email, _ = order_dependencies
    operator = create_operator(session_factory, "retry@example.com")
    manifest, rows = create_manifest_data(session_factory, operator.id, 1)
    basic, _ = create_pricing(session_factory, clock().date())
    headers = operator_headers(settings, clock, operator.id)
    client = TestClient(order_api)
    payload = {
        "pricing_tier_id": str(basic.id),
        "manifest_pilgrim_ids": [str(rows[0].id)],
    }

    email.fail_invoice = True
    failed = client.post(
        f"/v1/hto/manifests/{manifest.id}/order", headers=headers, json=payload
    )
    assert failed.status_code == 503
    with session_factory() as session:
        order = session.exec(select(ManifestOrder)).one()
        order_id = order.id
        assert order.invoice_url is not None
        assert order.invoice_email_sent_at is None

    email.fail_invoice = False
    retried = client.post(
        f"/v1/hto/manifests/{manifest.id}/order", headers=headers, json=payload
    )
    assert retried.status_code == 200
    assert retried.json()["manifest_order_id"] == str(order_id)
    with session_factory() as session:
        assert len(session.exec(select(ManifestOrder)).all()) == 1


def test_admin_confirmation_is_idempotent_and_gates_activation_dispatch(
    order_api,
    session_factory,
    settings,
    clock,
    order_dependencies,
) -> None:
    """AC-06.5: no activation before manual confirmation; retries don't duplicate."""
    _, provisioning, _, whatsapp = order_dependencies
    operator = create_operator(session_factory, "payment@example.com")
    manifest, rows = create_manifest_data(session_factory, operator.id, 2)
    basic, _ = create_pricing(session_factory, clock().date())
    client = TestClient(order_api)
    placed = client.post(
        f"/v1/hto/manifests/{manifest.id}/order",
        headers=operator_headers(settings, clock, operator.id),
        json={
            "pricing_tier_id": str(basic.id),
            "manifest_pilgrim_ids": [str(row.id) for row in rows],
        },
    )
    order_id = UUID(placed.json()["manifest_order_id"])
    assert provisioning.calls == []
    assert whatsapp.activations == []

    admin = AdminUser(email="admin-orders@example.com", password_hash="unused")
    with session_factory() as session:
        session.add(admin)
        session.commit()
        session.refresh(admin)
        admin_id = admin.id
        assert all(
            row.activation_code is None
            for row in session.exec(select(ManifestPilgrim)).all()
        )
    headers = admin_headers(settings, clock, admin_id)
    pending = client.get("/v1/admin/manifest-orders", headers=headers)
    assert pending.status_code == 200
    assert pending.json()["orders"][0]["pilgrim_count"] == 2
    admin_invoice = client.get(
        f"/v1/admin/manifest-orders/{order_id}/invoice", headers=headers
    )
    assert admin_invoice.status_code == 200
    assert admin_invoice.headers["content-type"] == "application/pdf"
    assert client.get(
        f"/v1/admin/manifest-orders/{uuid4()}/invoice", headers=headers
    ).status_code == 404
    assert client.get("/v1/admin/manifest-orders").status_code == 401

    confirmed = client.post(
        f"/v1/admin/manifest-orders/{order_id}/confirm-payment", headers=headers
    )
    assert confirmed.status_code == 200
    assert confirmed.json() == {"status": "provisioning"}
    repeated = client.post(
        f"/v1/admin/manifest-orders/{order_id}/confirm-payment", headers=headers
    )
    assert repeated.status_code == 200
    assert provisioning.calls == [order_id]

    service: ManifestOrderService = order_api.state.manifest_order_service
    with session_factory() as session:
        service.provision(session, order_id)
    assert len(whatsapp.activations) == 2
    assert all("code=" in activation[3] for activation in whatsapp.activations)
    with session_factory() as session:
        order = session.get(ManifestOrder, order_id)
        assert order is not None
        assert order.status == ManifestOrderStatus.PROVISIONED
        provisioned_rows = session.exec(select(ManifestPilgrim)).all()
        assert all(row.activation_code for row in provisioned_rows)
        assert all(row.activation_link_sent_at for row in provisioned_rows)

    with session_factory() as session:
        same = service.provision(session, order_id)
    assert same.status == ManifestOrderStatus.PROVISIONED
    assert len(whatsapp.activations) == 2


def test_admin_confirmation_recovers_when_queue_is_temporarily_unavailable(
    order_api,
    session_factory,
    settings,
    clock,
    order_dependencies,
) -> None:
    """Payment stays recorded and a later confirmation retries dispatch."""
    _, provisioning, _, _ = order_dependencies
    operator = create_operator(session_factory, "queue-retry@example.com")
    manifest, rows = create_manifest_data(session_factory, operator.id, 1)
    basic, _ = create_pricing(session_factory, clock().date())
    client = TestClient(order_api)
    placed = client.post(
        f"/v1/hto/manifests/{manifest.id}/order",
        headers=operator_headers(settings, clock, operator.id),
        json={
            "pricing_tier_id": str(basic.id),
            "manifest_pilgrim_ids": [str(rows[0].id)],
        },
    )
    order_id = UUID(placed.json()["manifest_order_id"])
    admin = AdminUser(email="admin-queue@example.com", password_hash="unused")
    with session_factory() as session:
        session.add(admin)
        session.commit()
        session.refresh(admin)
        headers = admin_headers(settings, clock, admin.id)

    provisioning.fail = True
    failed = client.post(
        f"/v1/admin/manifest-orders/{order_id}/confirm-payment", headers=headers
    )
    assert failed.status_code == 503
    with session_factory() as session:
        stored = session.get(ManifestOrder, order_id)
        assert stored is not None
        assert stored.status == ManifestOrderStatus.PROVISIONING
        assert stored.payment_confirmed_at is not None
        assert stored.provisioning_enqueued_at is None
    pending = client.get("/v1/admin/manifest-orders", headers=headers)
    assert [item["id"] for item in pending.json()["orders"]] == [str(order_id)]

    provisioning.fail = False
    retried = client.post(
        f"/v1/admin/manifest-orders/{order_id}/confirm-payment", headers=headers
    )
    assert retried.status_code == 200
    assert provisioning.calls == [order_id]


def test_provisioning_retries_only_undelivered_activation_links(
    order_api,
    session_factory,
    settings,
    clock,
    order_dependencies,
) -> None:
    """A partial WhatsApp outage resumes without duplicating successful sends."""
    _, _, _, whatsapp = order_dependencies
    operator = create_operator(session_factory, "activation-retry@example.com")
    manifest, rows = create_manifest_data(session_factory, operator.id, 2)
    basic, _ = create_pricing(session_factory, clock().date())
    client = TestClient(order_api)
    placed = client.post(
        f"/v1/hto/manifests/{manifest.id}/order",
        headers=operator_headers(settings, clock, operator.id),
        json={
            "pricing_tier_id": str(basic.id),
            "manifest_pilgrim_ids": [str(row.id) for row in rows],
        },
    )
    order_id = UUID(placed.json()["manifest_order_id"])
    with session_factory() as session:
        order = session.get(ManifestOrder, order_id)
        assert order is not None
        order.status = ManifestOrderStatus.PROVISIONING
        session.add(order)
        session.commit()

    whatsapp.fail_numbers.add(rows[1].phone_number)
    service: ManifestOrderService = order_api.state.manifest_order_service
    with session_factory() as session, pytest.raises(NotificationError):
        service.provision(session, order_id)
    assert [call[0] for call in whatsapp.activations] == [rows[0].phone_number]

    whatsapp.fail_numbers.clear()
    with session_factory() as session:
        retried = service.provision(session, order_id)
    assert retried.status == ManifestOrderStatus.PROVISIONED
    assert [call[0] for call in whatsapp.activations] == [
        rows[0].phone_number,
        rows[1].phone_number,
    ]
