import json
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlmodel import select

from app.auth.models import PricingTier
from app.auth.routes import request_otp, verify_otp
from app.auth.schemas import OTPRequest, OTPVerifyRequest
from app.main import create_app
from app.packages.models import Package, PackageStatus, Transaction, TransactionStatus
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
        self, email: str, tier_name: str, amount_ngn: Decimal, reference: str
    ) -> None:
        self.receipts.append((email, tier_name, amount_ngn, reference))


class RecordingWhatsAppSender:
    def __init__(self) -> None:
        self.receipts: list[tuple[str, str, Decimal, str]] = []

    def send_receipt(
        self, phone_number: str, tier_name: str, amount_ngn: Decimal, reference: str
    ) -> None:
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
    return TestClient(api, headers={"Authorization": f"Bearer {auth.access_token}"})


def _payment_api(
    settings,
    redis_client,
    providers,
    scheduler,
    session_factory,
    clock,
    payment_providers,
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
    )
    return api, email, whatsapp


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
        package = session.get(Package, response.json()["package_id"])
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
    assert response.json()["processor_reference"] == primary.initializations[0].reference


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
        user = session.exec(select(Package).where(False)).first()  # keep type inference local
        del user
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
    assert status.json()["status"] == "active"
    with session_factory() as session:
        package = session.get(Package, purchase["package_id"])
        transaction = session.exec(select(Transaction)).one()
        assert package is not None
        assert package.data_gb_remaining == Decimal("10.00")
        assert transaction.status == TransactionStatus.SUCCESS
    assert len(whatsapp.receipts) == 1
    assert len(email.receipts) <= 1


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

