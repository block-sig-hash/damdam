from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from app.auth.models import PricingTier
from app.auth.routes import request_otp, verify_otp
from app.auth.schemas import OTPRequest, OTPVerifyRequest
from app.main import create_app
from app.packages.models import Package, PackageSource, PackageStatus
from app.voice.models import VerifiedCallerIdentity
from app.voice.verified_numbers import (
    PhoneVerificationAttempt,
    PhoneVerificationProviderError,
)


@dataclass
class FakePhoneVerificationProvider:
    valid_code: str = "000000"

    def __post_init__(self) -> None:
        self.started: list[str] = []
        self.confirmed: list[tuple[str, str]] = []
        self.fail_start = False

    def start_verification(self, phone_number: str) -> PhoneVerificationAttempt:
        if self.fail_start:
            raise PhoneVerificationProviderError("Telnyx unavailable")
        self.started.append(phone_number)
        return PhoneVerificationAttempt(reference=f"ref-{len(self.started)}")

    def confirm_verification(self, reference: str, code: str) -> bool:
        self.confirmed.append((reference, code))
        return code == self.valid_code


def _api(settings, redis_client, providers, scheduler, session_factory, clock):
    phone_provider = FakePhoneVerificationProvider()
    api = create_app(
        settings=settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
        phone_verification_provider=phone_provider,
    )
    return api, phone_provider


def _authenticated(api, phone_number: str = "08012345678") -> tuple[TestClient, UUID]:
    request = SimpleNamespace(app=api)
    request_otp(OTPRequest(phone_number=phone_number), request)
    auth = verify_otp(
        OTPVerifyRequest(phone_number=phone_number, otp="123456", platform="android"),
        request,
    )
    return (
        TestClient(
            api,
            headers={"Authorization": f"Bearer {auth.access_token}"},
            raise_server_exceptions=False,
        ),
        auth.user.id,
    )


def _active_package(session_factory, user_id: UUID, minutes: str) -> None:
    with session_factory() as session:
        tier = PricingTier(
            name=f"CLI-{user_id}",
            usd_reference_price=Decimal("100"),
            data_gb=5,
            pstn_minutes=10,
            wholesale_usd_price=Decimal("80"),
            ngn_price=Decimal("100000"),
        )
        session.add(tier)
        session.flush()
        session.add(
            Package(
                user_id=user_id,
                pricing_tier_id=tier.id,
                source=PackageSource.RETAIL,
                status=PackageStatus.ACTIVE,
                data_gb_total=5,
                data_gb_remaining=Decimal("5"),
                pstn_minutes_total=10,
                pstn_minutes_remaining=Decimal(minutes),
                purchased_at=datetime.now(timezone.utc),
            )
        )
        session.commit()


def test_start_verification_normalizes_number_decoupled_from_login_number(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-14.1/AC-14.10: CLI verification is a dedicated flow for any
    Nigerian number, independent of the account's login number."""
    api, phone_provider = _api(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, _ = _authenticated(api, "08012345678")

    response = client.post(
        "/v1/voice/cli/verify", json={"phone_number": "0803 999 8888"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["phone_number"] == "+2348039998888"
    assert body["status"] == "phone_verification_pending"
    assert phone_provider.started == ["+2348039998888"]


def test_start_verification_rejects_invalid_number(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    api, _ = _api(settings, redis_client, providers, scheduler, session_factory, clock)
    client, _ = _authenticated(api)

    response = client.post(
        "/v1/voice/cli/verify", json={"phone_number": "not-a-number"}
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_phone_number"


def test_start_verification_is_rate_limited(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    configured = settings.model_copy(
        update={"cli_verification_max_attempts_per_window": 2}
    )
    api, _ = _api(
        configured, redis_client, providers, scheduler, session_factory, clock
    )
    client, _ = _authenticated(api)

    for _ in range(2):
        assert (
            client.post(
                "/v1/voice/cli/verify", json={"phone_number": "08039998888"}
            ).status_code
            == 201
        )
    response = client.post("/v1/voice/cli/verify", json={"phone_number": "08039998888"})

    assert response.status_code == 429
    assert response.json()["error"] == "cli_verification_rate_limited"


def test_confirm_wrong_code_leaves_verification_pending(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    api, _ = _api(settings, redis_client, providers, scheduler, session_factory, clock)
    client, _ = _authenticated(api)
    identity_id = client.post(
        "/v1/voice/cli/verify", json={"phone_number": "08039998888"}
    ).json()["id"]

    response = client.post(
        f"/v1/voice/cli/{identity_id}/confirm", json={"code": "111111"}
    )

    assert response.status_code == 400
    assert response.json()["error"] == "verification_code_invalid"
    status = client.get("/v1/voice/cli/status").json()
    assert status["status"] == "phone_verification_pending"


def test_confirm_is_locked_out_after_repeated_wrong_codes(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """The SMS code itself must not be brute-forceable: repeated wrong
    codes against one identity_id lock out further confirm attempts,
    independent of the coarser per-user start_verification rate limit."""
    configured = settings.model_copy(
        update={"cli_verification_confirm_attempt_limit": 2}
    )
    api, _ = _api(
        configured, redis_client, providers, scheduler, session_factory, clock
    )
    client, _ = _authenticated(api)
    identity_id = client.post(
        "/v1/voice/cli/verify", json={"phone_number": "08039998888"}
    ).json()["id"]

    for _ in range(2):
        response = client.post(
            f"/v1/voice/cli/{identity_id}/confirm", json={"code": "111111"}
        )
        assert response.status_code == 400
        assert response.json()["error"] == "verification_code_invalid"

    locked = client.post(
        f"/v1/voice/cli/{identity_id}/confirm", json={"code": "111111"}
    )
    assert locked.status_code == 429
    assert locked.json()["error"] == "cli_verification_rate_limited"

    # Even the correct code is rejected while locked out -- the lockout is
    # a hard stop, not just a slower retry.
    still_locked = client.post(
        f"/v1/voice/cli/{identity_id}/confirm", json={"code": "000000"}
    )
    assert still_locked.status_code == 429


def test_full_flow_confirm_then_consent_activates_pstn_calling(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-14.1: phone possession proof plus explicit consent is required
    before PSTN eligibility opens up."""
    api, _ = _api(settings, redis_client, providers, scheduler, session_factory, clock)
    client, user_id = _authenticated(api)
    _active_package(session_factory, user_id, "2.00")

    assert (
        client.get(
            "/v1/voice/eligibility", params={"phone_number": "08099999999"}
        ).json()["reason"]
        == "cli_not_verified"
    )

    identity_id = client.post(
        "/v1/voice/cli/verify", json={"phone_number": "08039998888"}
    ).json()["id"]
    confirmed = client.post(
        f"/v1/voice/cli/{identity_id}/confirm", json={"code": "000000"}
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "consent_required"

    consented = client.post(
        f"/v1/voice/cli/{identity_id}/consent",
        json={"consent_version": "v1", "device_session_id": "device-1"},
    )
    assert consented.status_code == 200
    assert consented.json()["status"] == "active"

    eligibility = client.get(
        "/v1/voice/eligibility", params={"phone_number": "08099999999"}
    ).json()
    assert eligibility["reason"] is None
    assert eligibility["allowed"] is True


def test_consent_before_confirmation_is_rejected(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    api, _ = _api(settings, redis_client, providers, scheduler, session_factory, clock)
    client, _ = _authenticated(api)
    identity_id = client.post(
        "/v1/voice/cli/verify", json={"phone_number": "08039998888"}
    ).json()["id"]

    response = client.post(
        f"/v1/voice/cli/{identity_id}/consent",
        json={"consent_version": "v1"},
    )

    assert response.status_code == 409
    assert response.json()["error"] == "invalid_state"


def _activate(client: TestClient, phone_provider, phone_number: str) -> str:
    r1 = client.post("/v1/voice/cli/verify", json={"phone_number": phone_number})
    assert r1.status_code == 201, r1.text
    identity_id = r1.json()["id"]
    r2 = client.post(f"/v1/voice/cli/{identity_id}/confirm", json={"code": "000000"})
    assert r2.status_code == 200, r2.text
    r3 = client.post(
        f"/v1/voice/cli/{identity_id}/consent", json={"consent_version": "v1"}
    )
    assert r3.status_code == 200, r3.text
    return identity_id


def test_revoke_immediately_blocks_new_pstn_calls(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """AC-14.11: revocation blocks new calls immediately."""
    api, phone_provider = _api(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, _ = _authenticated(api)
    _activate(client, phone_provider, "08039998888")

    revoke = client.post("/v1/voice/cli/revoke")
    assert revoke.status_code == 204

    eligibility = client.get(
        "/v1/voice/eligibility", params={"phone_number": "08099999999"}
    ).json()
    assert eligibility["reason"] == "cli_not_verified"


def test_lost_sim_report_also_revokes(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    api, phone_provider = _api(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, _ = _authenticated(api)
    _activate(client, phone_provider, "08039998888")

    response = client.post("/v1/voice/cli/lost-sim")
    assert response.status_code == 204
    assert (
        client.get(
            "/v1/voice/eligibility", params={"phone_number": "08099999999"}
        ).json()["reason"]
        == "cli_not_verified"
    )


def test_reverifying_a_new_number_revokes_the_previous_active_identity(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """A user may only hold one active CLI at a time (data-model.md §6.40)."""
    api, phone_provider = _api(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    client, user_id = _authenticated(api)
    first_id = _activate(client, phone_provider, "08039998888")

    second_id = _activate(client, phone_provider, "08037778888")

    with session_factory() as session:
        first = session.get(VerifiedCallerIdentity, UUID(first_id))
        second = session.get(VerifiedCallerIdentity, UUID(second_id))
        assert first is not None and second is not None
        assert first.status == "revoked"
        assert second.status == "active"


def test_number_already_active_on_another_account_is_rejected(
    settings, redis_client, providers, scheduler, session_factory, clock
) -> None:
    """A second partial unique index prevents the same number being active
    on two unrelated accounts (SIM-swap/number-recycling risk)."""
    api, phone_provider = _api(
        settings, redis_client, providers, scheduler, session_factory, clock
    )
    first_client, _ = _authenticated(api, "08012345678")
    _activate(first_client, phone_provider, "08039998888")

    second_client, _ = _authenticated(api, "08098765432")
    identity_id = second_client.post(
        "/v1/voice/cli/verify", json={"phone_number": "08039998888"}
    ).json()["id"]
    second_client.post(f"/v1/voice/cli/{identity_id}/confirm", json={"code": "000000"})
    response = second_client.post(
        f"/v1/voice/cli/{identity_id}/consent", json={"consent_version": "v1"}
    )

    assert response.status_code == 409
    assert response.json()["error"] == "number_already_verified_elsewhere"
