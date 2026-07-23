import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient
from sqlmodel import select

from app.audit.models import AuditLog, AuditOutcome
from app.auth.models import PricingTier
from app.auth.routes import request_otp, verify_otp
from app.auth.schemas import OTPRequest, OTPVerifyRequest
from app.main import create_app
from app.packages.models import (
    Package,
    PackageStatus,
    PaymentProcessor,
    Transaction,
    TransactionStatus,
)
from app.payments.providers import (
    PaymentCheckout,
    PaymentInitialization,
    PaymentProviderError,
    PaymentWebhookEvent,
)


@dataclass
class FakePaymentProvider:
    name: str
    fail_initialization: bool = False

    def __post_init__(self) -> None:
        self.initializations: list[PaymentInitialization] = []

    def initialize(self, payment: PaymentInitialization) -> PaymentCheckout:
        self.initializations.append(payment)
        if self.fail_initialization:
            raise PaymentProviderError(f"{self.name} unavailable")
        return PaymentCheckout(
            processor=self.name,
            processor_reference=payment.reference,
            checkout_url=f"https://checkout.example/{self.name}/{payment.reference}",
        )

    def parse_webhook(
        self, body: bytes, headers: dict[str, str]
    ) -> PaymentWebhookEvent | None:
        if headers.get("x-test-signature") != f"valid-{self.name}":
            raise PaymentProviderError("invalid signature")
        payload = json.loads(body)
        if payload.get("status") != "success":
            return None
        return PaymentWebhookEvent(
            processor=self.name,
            processor_reference=payload["reference"],
            amount_ngn=Decimal(str(payload["amount_ngn"])),
            payment_method=payload["payment_method"],
            payload=payload,
        )


class RecordingEmailSender:
    def __init__(self) -> None:
        self.receipts: list[tuple[str, str, Decimal, str]] = []

    def send_receipt(
        self,
        email: str,
        tier_name: str,
        amount_ngn: Decimal,
        reference: str,
        locale: str = "en",
    ) -> None:
        del locale
        self.receipts.append((email, tier_name, amount_ngn, reference))


class RecordingWhatsAppSender:
    def __init__(self) -> None:
        self.receipts: list[tuple[str, str, Decimal, str]] = []

    def send_receipt(
        self,
        phone_number: str,
        tier_name: str,
        amount_ngn: Decimal,
        reference: str,
        locale: str = "en",
    ) -> None:
        del locale
        self.receipts.append((phone_number, tier_name, amount_ngn, reference))


def _tier(*, family: bool = False) -> PricingTier:
    return PricingTier(
        name="Family" if family else "Standard",
        usd_reference_price=Decimal("100.00"),
        data_gb=12 if family else 10,
        pstn_minutes=100 if family else 90,
        is_group_tier=family,
        min_group_size=2 if family else None,
        max_group_size=8 if family else None,
        wholesale_usd_price=Decimal("80.00"),
        active=True,
        ngn_price=Decimal("75000.00" if family else "145000.00"),
    )


def _authenticated_client(api: object, phone_number: str = "08012345678") -> TestClient:
    request = SimpleNamespace(app=api)
    request_otp(OTPRequest(phone_number=phone_number), request)
    auth = verify_otp(
        OTPVerifyRequest(phone_number=phone_number, otp="123456", platform="android"),
        request,
    )
    return TestClient(
        api,
        headers={"Authorization": f"Bearer {auth.access_token}"},
        raise_server_exceptions=False,
    )


def _payment_api(
    settings,
    redis_client,
    providers,
    scheduler,
    session_factory,
    clock,
    payment_providers,
    esim_scheduler=None,
):
    email = RecordingEmailSender()
    whatsapp = RecordingWhatsAppSender()
    api = create_app(
        settings=settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
        email_sender=email,
        whatsapp_sender=whatsapp,
        payment_providers=payment_providers,
        esim_scheduler=esim_scheduler,
    )
    return api, email, whatsapp


class RecordingEsimScheduler:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, int]] = []

    def schedule(self, package_id: UUID, countdown: int) -> None:
        self.calls.append((package_id, countdown))


def test_checkout_uses_configured_primary_and_current_stored_price(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-09.1/2: checkout is processor-neutral and offers all retail rails."""
    paystack = FakePaymentProvider("paystack")
    flutterwave = FakePaymentProvider("flutterwave")
    api, _, _ = _payment_api(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        {"paystack": paystack, "flutterwave": flutterwave},
    )
    with session_factory() as session:
        tier = _tier()
        session.add(tier)
        session.commit()
        session.refresh(tier)
        tier_id = str(tier.id)

    response = _authenticated_client(api).post(
        "/v1/packages/purchase", json={"pricing_tier_id": tier_id}
    )

    assert response.status_code == 200
    assert response.json()["processor"] == settings.payment_processor_primary
    assert "processor" not in paystack.initializations[0].metadata
    assert paystack.initializations[0].amount_ngn == Decimal("145000.00")
    assert paystack.initializations[0].channels == (
        "card",
        "bank_transfer",
        "ussd",
        "mobile_money",
    )
    assert flutterwave.initializations == []
    with session_factory() as session:
        package = session.get(Package, UUID(response.json()["package_id"]))
        transaction = session.exec(select(Transaction)).one()
        assert package is not None and package.status == PackageStatus.PENDING
        assert transaction.status == TransactionStatus.PENDING
        assert transaction.amount_ngn == Decimal("145000.00")


def test_checkout_falls_back_only_when_configured_primary_initialization_fails(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-09.1: secondary initialization is automatic and invisible."""
    primary = FakePaymentProvider(settings.payment_processor_primary, True)
    secondary = FakePaymentProvider(settings.payment_processor_secondary)
    api, _, _ = _payment_api(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        {primary.name: primary, secondary.name: secondary},
    )
    with session_factory() as session:
        tier = _tier(family=True)
        session.add(tier)
        session.commit()
        session.refresh(tier)
        tier_id = str(tier.id)

    response = _authenticated_client(api).post(
        "/v1/packages/purchase",
        json={"pricing_tier_id": tier_id, "group_size": 4},
    )

    assert response.status_code == 200
    assert response.json()["processor"] == secondary.name
    assert len(primary.initializations) == len(secondary.initializations) == 1
    assert secondary.initializations[0].amount_ngn == Decimal("300000.00")
    assert (
        response.json()["processor_reference"] == primary.initializations[0].reference
    )


def test_processor_order_comes_from_config_not_provider_names(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """§5.3: reversing configuration reverses initialization order."""
    configured = settings.model_copy(
        update={
            "payment_processor_primary": "flutterwave",
            "payment_processor_secondary": "paystack",
        }
    )
    paystack = FakePaymentProvider("paystack")
    flutterwave = FakePaymentProvider("flutterwave")
    api, _, _ = _payment_api(
        configured,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        {"paystack": paystack, "flutterwave": flutterwave},
    )
    with session_factory() as session:
        tier = _tier()
        session.add(tier)
        session.commit()
        session.refresh(tier)

    response = _authenticated_client(api).post(
        "/v1/packages/purchase", json={"pricing_tier_id": str(tier.id)}
    )

    assert response.status_code == 200
    assert response.json()["processor"] == "flutterwave"
    assert len(flutterwave.initializations) == 1
    assert paystack.initializations == []


def test_family_group_size_is_validated_server_side(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-09.1 + AC-08.4: checkout cannot bypass Family bounds."""
    payment_providers = {
        "paystack": FakePaymentProvider("paystack"),
        "flutterwave": FakePaymentProvider("flutterwave"),
    }
    api, _, _ = _payment_api(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        payment_providers,
    )
    with session_factory() as session:
        tier = _tier(family=True)
        session.add(tier)
        session.commit()
        session.refresh(tier)

    response = _authenticated_client(api).post(
        "/v1/packages/purchase",
        json={"pricing_tier_id": str(tier.id), "group_size": 9},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_group_size"
    assert all(not provider.initializations for provider in payment_providers.values())


def test_both_initializers_failing_returns_retryable_reason_without_rows(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-09.4: a dual outage is explicit and does not create a phantom purchase."""
    payment_providers = {
        "paystack": FakePaymentProvider("paystack", True),
        "flutterwave": FakePaymentProvider("flutterwave", True),
    }
    api, _, _ = _payment_api(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        payment_providers,
    )
    with session_factory() as session:
        tier = _tier()
        session.add(tier)
        session.commit()
        session.refresh(tier)
        tier_id = str(tier.id)

    response = _authenticated_client(api).post(
        "/v1/packages/purchase", json={"pricing_tier_id": tier_id}
    )

    assert response.status_code == 503
    assert response.json()["error"] == "payment_unavailable"
    with session_factory() as session:
        assert session.exec(select(Package)).all() == []
        assert session.exec(select(Transaction)).all() == []


def test_webhook_rejects_invalid_signature_without_mutating_purchase(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-09.7: unsigned callbacks cannot activate a package."""
    payment_providers = {
        "paystack": FakePaymentProvider("paystack"),
        "flutterwave": FakePaymentProvider("flutterwave"),
    }
    api, _, _ = _payment_api(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        payment_providers,
    )
    client = _authenticated_client(api)
    with session_factory() as session:
        tier = _tier()
        session.add(tier)
        session.commit()
        session.refresh(tier)
        tier_id = str(tier.id)
    purchase = client.post(
        "/v1/packages/purchase", json={"pricing_tier_id": tier_id}
    ).json()

    response = TestClient(api).post(
        "/v1/webhooks/paystack",
        content=json.dumps(
            {
                "status": "success",
                "reference": purchase["processor_reference"],
                "amount_ngn": 145000,
                "payment_method": "card",
            }
        ),
        headers={"x-test-signature": "wrong"},
    )

    assert response.status_code == 401
    with session_factory() as session:
        transaction = session.exec(select(Transaction)).one()
        assert transaction.status == TransactionStatus.PENDING


def test_package_status_is_private_to_its_pilgrim(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """Retail package polling cannot disclose another pilgrim's purchase."""
    payment_providers = {
        "paystack": FakePaymentProvider("paystack"),
        "flutterwave": FakePaymentProvider("flutterwave"),
    }
    api, _, _ = _payment_api(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        payment_providers,
    )
    with session_factory() as session:
        tier = _tier()
        session.add(tier)
        session.commit()
        session.refresh(tier)
        tier_id = str(tier.id)
    owner = _authenticated_client(api)
    other = _authenticated_client(api, "08100000000")
    purchase = owner.post(
        "/v1/packages/purchase", json={"pricing_tier_id": tier_id}
    ).json()

    response = other.get(f"/v1/packages/{purchase['package_id']}/status")

    assert response.status_code == 404
    assert response.json()["error"] == "package_not_found"


def test_duplicate_paystack_webhook_activates_and_sends_receipt_once(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-09.3/5/6/7: first valid webhook wins; duplicates are no-ops."""
    payment_providers = {
        "paystack": FakePaymentProvider("paystack"),
        "flutterwave": FakePaymentProvider("flutterwave"),
    }
    api, email, whatsapp = _payment_api(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        payment_providers,
    )
    client = _authenticated_client(api)
    with session_factory() as session:
        tier = _tier()
        session.add(tier)
        session.commit()
        session.refresh(tier)
    purchase = client.post(
        "/v1/packages/purchase", json={"pricing_tier_id": str(tier.id)}
    ).json()
    payload = {
        "status": "success",
        "reference": purchase["processor_reference"],
        "amount_ngn": 145000,
        "payment_method": "card",
    }

    first = TestClient(api).post(
        "/v1/webhooks/paystack",
        content=json.dumps(payload),
        headers={"x-test-signature": "valid-paystack"},
    )
    duplicate = TestClient(api).post(
        "/v1/webhooks/paystack",
        content=json.dumps(payload),
        headers={"x-test-signature": "valid-paystack"},
    )

    assert first.status_code == duplicate.status_code == 200
    assert first.json() == {"processed": True}
    assert duplicate.json() == {"processed": False}
    status = client.get(f"/v1/packages/{purchase['package_id']}/status")
    assert status.status_code == 200
    assert status.json() == {
        "status": "active",
        "data_gb_total": 10,
        "data_gb_remaining": 10.0,
        "pstn_minutes_total": 90,
        "pstn_minutes_remaining": 90.0,
    }
    with session_factory() as session:
        package = session.get(Package, UUID(purchase["package_id"]))
        transaction = session.exec(select(Transaction)).one()
        assert package is not None
        assert package.data_gb_remaining == Decimal("10.00")
        assert transaction.status == TransactionStatus.SUCCESS
    assert len(whatsapp.receipts) == 1
    assert len(email.receipts) <= 1


def test_successful_payment_enqueues_esim_issuance_once(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-11.1: first valid payment callback queues profile issuance once."""
    payment_providers = {
        "paystack": FakePaymentProvider("paystack"),
        "flutterwave": FakePaymentProvider("flutterwave"),
    }
    esim_scheduler = RecordingEsimScheduler()
    api, _, _ = _payment_api(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        payment_providers,
        esim_scheduler,
    )
    client = _authenticated_client(api)
    with session_factory() as session:
        tier = _tier()
        session.add(tier)
        session.commit()
        session.refresh(tier)
    purchase = client.post(
        "/v1/packages/purchase", json={"pricing_tier_id": str(tier.id)}
    ).json()
    payload = {
        "status": "success",
        "reference": purchase["processor_reference"],
        "amount_ngn": 145000,
        "payment_method": "card",
    }

    webhook = TestClient(api)
    for _ in range(2):
        response = webhook.post(
            "/v1/webhooks/paystack",
            content=json.dumps(payload),
            headers={"x-test-signature": "valid-paystack"},
        )
        assert response.status_code == 200

    assert esim_scheduler.calls == [(UUID(purchase["package_id"]), 0)]


def test_flutterwave_webhook_uses_same_idempotency_path_after_failover(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-09.7: idempotency is processor-reference based for either gateway."""
    payment_providers = {
        "paystack": FakePaymentProvider("paystack", True),
        "flutterwave": FakePaymentProvider("flutterwave"),
    }
    api, _, whatsapp = _payment_api(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        payment_providers,
    )
    client = _authenticated_client(api)
    with session_factory() as session:
        tier = _tier()
        session.add(tier)
        session.commit()
        session.refresh(tier)
    purchase = client.post(
        "/v1/packages/purchase", json={"pricing_tier_id": str(tier.id)}
    ).json()
    payload = json.dumps(
        {
            "status": "success",
            "reference": purchase["processor_reference"],
            "amount_ngn": 145000,
            "payment_method": "bank_transfer",
        }
    )

    responses = [
        TestClient(api).post(
            "/v1/webhooks/flutterwave",
            content=payload,
            headers={"x-test-signature": "valid-flutterwave"},
        )
        for _ in range(2)
    ]

    assert [response.json() for response in responses] == [
        {"processed": True},
        {"processed": False},
    ]
    assert len(whatsapp.receipts) == 1


def test_first_signed_webhook_wins_even_after_ambiguous_primary_timeout(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-09.7: one shared reference closes the cross-processor timeout race."""
    payment_providers = {
        "paystack": FakePaymentProvider("paystack", True),
        "flutterwave": FakePaymentProvider("flutterwave"),
    }
    api, _, _ = _payment_api(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        payment_providers,
    )
    client = _authenticated_client(api)
    with session_factory() as session:
        tier = _tier()
        session.add(tier)
        session.commit()
        session.refresh(tier)
        tier_id = str(tier.id)
    purchase = client.post(
        "/v1/packages/purchase", json={"pricing_tier_id": tier_id}
    ).json()
    event = json.dumps(
        {
            "status": "success",
            "reference": purchase["processor_reference"],
            "amount_ngn": 145000,
            "payment_method": "card",
        }
    )

    primary = TestClient(api).post(
        "/v1/webhooks/paystack",
        content=event,
        headers={"x-test-signature": "valid-paystack"},
    )
    secondary = TestClient(api).post(
        "/v1/webhooks/flutterwave",
        content=event,
        headers={"x-test-signature": "valid-flutterwave"},
    )

    assert primary.json() == {"processed": True}
    assert secondary.json() == {"processed": False}
    with session_factory() as session:
        transaction = session.exec(select(Transaction)).one()
        assert transaction.processor == PaymentProcessor.PAYSTACK
        assert transaction.status == TransactionStatus.SUCCESS


def test_second_purchase_while_first_still_active_chains_through_real_webhook_flow(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-25.3, end-to-end through the real HTTP/webhook path (not the
    isolated PackageChainingService unit tests in test_package_chaining.py):
    a pilgrim who buys a second package while the first is still valid does
    not end up with two concurrently-active packages. The second package
    activates with the first's unused balance rolled forward and a window
    chained from the first's expiry, and the first flips to SUPERSEDED."""
    payment_providers = {
        "paystack": FakePaymentProvider("paystack"),
        "flutterwave": FakePaymentProvider("flutterwave"),
    }
    api, _, _ = _payment_api(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        payment_providers,
    )
    client = _authenticated_client(api)
    with session_factory() as session:
        first_tier = _tier()
        first_tier.validity_days = 15
        second_tier = PricingTier(
            name="Premium",
            usd_reference_price=Decimal("150.00"),
            data_gb=12,
            pstn_minutes=100,
            wholesale_usd_price=Decimal("120.00"),
            active=True,
            ngn_price=Decimal("75000.00"),
            validity_days=30,
        )
        session.add(first_tier)
        session.add(second_tier)
        session.commit()
        session.refresh(first_tier)
        session.refresh(second_tier)
        first_tier_id, second_tier_id = str(first_tier.id), str(second_tier.id)

    first_purchase = client.post(
        "/v1/packages/purchase", json={"pricing_tier_id": first_tier_id}
    ).json()
    first_payload = json.dumps(
        {
            "status": "success",
            "reference": first_purchase["processor_reference"],
            "amount_ngn": 145000,
            "payment_method": "card",
        }
    )
    first_webhook = TestClient(api).post(
        "/v1/webhooks/paystack",
        content=first_payload,
        headers={"x-test-signature": "valid-paystack"},
    )
    assert first_webhook.json() == {"processed": True}

    with session_factory() as session:
        first_package = session.get(Package, UUID(first_purchase["package_id"]))
        assert first_package is not None
        # Simulate some usage before the rebuy, so the roll-forward is
        # actually exercised rather than trivially rolling forward a
        # still-full balance.
        first_package.data_gb_remaining = Decimal("4.00")
        first_package.pstn_minutes_remaining = Decimal("30.00")
        session.add(first_package)
        session.commit()
        first_expires_at = first_package.expires_at

    second_purchase = client.post(
        "/v1/packages/purchase", json={"pricing_tier_id": second_tier_id}
    ).json()
    second_payload = json.dumps(
        {
            "status": "success",
            "reference": second_purchase["processor_reference"],
            "amount_ngn": 75000,
            "payment_method": "card",
        }
    )
    second_webhook = TestClient(api).post(
        "/v1/webhooks/paystack",
        content=second_payload,
        headers={"x-test-signature": "valid-paystack"},
    )
    assert second_webhook.json() == {"processed": True}

    with session_factory() as session:
        first_package = session.get(Package, UUID(first_purchase["package_id"]))
        second_package = session.get(Package, UUID(second_purchase["package_id"]))
        assert first_package is not None and second_package is not None
        assert first_package.status == PackageStatus.SUPERSEDED
        assert second_package.status == PackageStatus.ACTIVE
        # Rolled forward from the first package's leftover balance, on top
        # of the second tier's own allowance (12 GB / 100 minutes).
        assert second_package.data_gb_remaining == Decimal("16.00")
        assert second_package.pstn_minutes_remaining == Decimal("130.00")
        # Chained from the first package's expiry, not from purchase time.
        assert second_package.expires_at == first_expires_at + timedelta(days=30)

        audit_entry = session.exec(
            select(AuditLog).where(
                AuditLog.outcome == AuditOutcome.PACKAGE_CHAINED_ONTO_ACTIVE_WINDOW
            )
        ).one()
        assert audit_entry.reference == str(second_package.id)
        assert str(first_package.id) in (audit_entry.details or "")


def test_duplicate_webhook_writes_audit_log_entry(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-25.4: a duplicate webhook retry is absorbed silently (no error
    surfaced to the caller, verified elsewhere) but leaves an audit trail
    for admin review."""
    payment_providers = {
        "paystack": FakePaymentProvider("paystack"),
        "flutterwave": FakePaymentProvider("flutterwave"),
    }
    api, _, _ = _payment_api(
        settings,
        redis_client,
        providers,
        scheduler,
        session_factory,
        clock,
        payment_providers,
    )
    client = _authenticated_client(api)
    with session_factory() as session:
        tier = _tier()
        session.add(tier)
        session.commit()
        session.refresh(tier)
    purchase = client.post(
        "/v1/packages/purchase", json={"pricing_tier_id": str(tier.id)}
    ).json()
    payload = json.dumps(
        {
            "status": "success",
            "reference": purchase["processor_reference"],
            "amount_ngn": 145000,
            "payment_method": "card",
        }
    )

    for _ in range(2):
        response = TestClient(api).post(
            "/v1/webhooks/paystack",
            content=payload,
            headers={"x-test-signature": "valid-paystack"},
        )
        assert response.status_code == 200

    with session_factory() as session:
        audit_entry = session.exec(
            select(AuditLog).where(
                AuditLog.outcome == AuditOutcome.DUPLICATE_WEBHOOK_ABSORBED
            )
        ).one()
        assert audit_entry.reference == purchase["processor_reference"]
        assert "paystack" in (audit_entry.details or "")
