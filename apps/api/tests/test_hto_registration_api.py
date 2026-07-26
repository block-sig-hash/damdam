from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import bcrypt
import jwt
import pytest
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from sqlmodel import select

from app.admin.routes import (
    approve_hto_operator,
    current_admin,
    list_hto_operators,
    reject_hto_operator,
)
from app.auth.hto import HTOAuthError
from app.auth.models import (
    AdminUser,
    HTOApprovalStatus,
    Organization,
    OrganizationType,
)
from app.auth.routes import login_hto, register_hto, verify_hto_email
from app.auth.schemas import (
    HTOLoginRequest,
    HTORegistrationRequest,
    HTORejectionRequest,
    HTOVerifyEmailRequest,
)
from app.notifications.service import EmailSender, NotificationError, WhatsAppSender


class FakeEmailSender(EmailSender):
    def __init__(self) -> None:
        self.verifications: list[tuple[str, str, str]] = []
        self.approvals: list[tuple[str, str]] = []
        self.fail_approval = False

    def send_verification(
        self,
        email: str,
        operator_name: str,
        verification_url: str,
        locale: str = "en",
    ) -> None:
        del locale
        self.verifications.append((email, operator_name, verification_url))

    def send_approval(self, email: str, operator_name: str, locale: str = "en") -> None:
        del locale
        if self.fail_approval:
            raise NotificationError("email unavailable")
        self.approvals.append((email, operator_name))


class FakeWhatsAppSender(WhatsAppSender):
    def __init__(self) -> None:
        self.approvals: list[tuple[str, str]] = []
        self.fail_approval = False

    def send_approval(
        self, phone_number: str, operator_name: str, locale: str = "en"
    ) -> None:
        del locale
        if self.fail_approval:
            raise NotificationError("whatsapp unavailable")
        self.approvals.append((phone_number, operator_name))


@pytest.fixture
def email_sender() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture
def whatsapp_sender() -> FakeWhatsAppSender:
    return FakeWhatsAppSender()


@pytest.fixture
def hto_api(
    settings,
    redis_client,
    providers,
    scheduler,
    clock,
    session_factory,
    email_sender,
    whatsapp_sender,
):
    from app.main import create_app

    return create_app(
        settings=settings,
        redis_client=redis_client,
        providers=providers,
        scheduler=scheduler,
        session_factory=session_factory,
        clock=clock,
        email_sender=email_sender,
        whatsapp_sender=whatsapp_sender,
    )


@pytest.fixture
def registration_payload() -> dict[str, str]:
    return {
        "business_name": "Barakah Hajj Services",
        "operator_name": "Amina Yusuf",
        "email": "AMINA@EXAMPLE.COM",
        "password": "correct horse battery staple",
        "phone_number": "08012345678",
        "nahcon_licence_number": "LICENCE PENDING MANUAL REVIEW",
    }


def register_and_token(api, email_sender, payload) -> str:
    response = register_hto(HTORegistrationRequest(**payload), SimpleNamespace(app=api))
    assert response.message == "Verification email sent"
    verification_url = email_sender.verifications[0][2]
    return parse_qs(urlparse(verification_url).query)["token"][0]


@pytest.mark.parametrize(
    "missing_field",
    [
        "business_name",
        "operator_name",
        "email",
        "password",
        "phone_number",
        "nahcon_licence_number",
    ],
)
def test_registration_requires_every_business_field(
    hto_api, registration_payload, missing_field
) -> None:
    """AC-04.1: all six business registration fields are required."""
    payload = registration_payload.copy()
    payload.pop(missing_field)

    with pytest.raises(ValidationError):
        HTORegistrationRequest(**payload)


def test_registration_hashes_password_and_records_unvalidated_licence(
    hto_api, session_factory, email_sender, registration_payload
) -> None:
    """AC-04.1/04.2: credentials are safe and licence review stays manual."""
    response = register_hto(
        HTORegistrationRequest(**registration_payload), SimpleNamespace(app=hto_api)
    )

    assert response.model_dump() == {"message": "Verification email sent"}
    assert len(email_sender.verifications) == 1
    with session_factory() as session:
        organization = session.exec(select(Organization)).one()
        assert organization.org_type == OrganizationType.HTO_OPERATOR
        assert organization.name == registration_payload["business_name"]
        assert (
            organization.primary_contact_name == registration_payload["operator_name"]
        )
        assert organization.email == "amina@example.com"
        assert organization.phone_number == "+2348012345678"
        assert (
            organization.nahcon_licence_number
            == registration_payload["nahcon_licence_number"]
        )
        assert organization.password_hash != registration_payload["password"]
        assert bcrypt.checkpw(
            registration_payload["password"].encode(),
            organization.password_hash.encode(),
        )
        assert organization.password_hash.startswith("$2b$12$")


def test_email_verification_is_required_and_token_expires_after_24_hours(
    hto_api, email_sender, registration_payload, clock
) -> None:
    """AC-04.3: activation requires a valid 24-hour email link."""
    request = SimpleNamespace(app=hto_api)
    token = register_and_token(hto_api, email_sender, registration_payload)

    with pytest.raises(HTOAuthError, match="email_not_verified"):
        login_hto(
            HTOLoginRequest(
                email=registration_payload["email"],
                password=registration_payload["password"],
            ),
            request,
        )

    clock.advance(hours=24, seconds=1)
    with pytest.raises(HTOAuthError, match="invalid_verification_token"):
        verify_hto_email(HTOVerifyEmailRequest(token=token), request)


def test_verified_account_remains_pending_until_admin_approval(
    hto_api,
    session_factory,
    email_sender,
    whatsapp_sender,
    registration_payload,
    settings,
    clock,
) -> None:
    """AC-04.3/04.4/04.5: approval gates login and notifies both channels."""
    request = SimpleNamespace(app=hto_api)
    token = register_and_token(hto_api, email_sender, registration_payload)

    verified = verify_hto_email(HTOVerifyEmailRequest(token=token), request)
    assert verified.model_dump() == {
        "message": "Email verified, pending admin approval"
    }

    with pytest.raises(HTOAuthError, match="pending_approval"):
        login_hto(
            HTOLoginRequest(
                email=registration_payload["email"],
                password=registration_payload["password"],
            ),
            request,
        )

    with session_factory() as session:
        organization = session.exec(select(Organization)).one()
        assert organization.approval_status == HTOApprovalStatus.PENDING
        admin = AdminUser(
            id=uuid4(),
            email="admin@damdam.app",
            password_hash="not-used-in-this-test",
        )
        session.add(admin)
        session.commit()
        admin_id = admin.id
        operator_id = organization.id

    admin_token = jwt.encode(
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
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=admin_token)
    authenticated_admin = current_admin(request, credentials)

    pending_list = list_hto_operators(
        request, authenticated_admin, HTOApprovalStatus.PENDING
    )
    assert (
        pending_list.operators[0].nahcon_licence_number
        == (registration_payload["nahcon_licence_number"])
    )

    approved = approve_hto_operator(operator_id, request, authenticated_admin)
    assert approved.model_dump(mode="json") == {"approval_status": "approved"}
    assert email_sender.approvals == [("amina@example.com", "Amina Yusuf")]
    assert whatsapp_sender.approvals == [("+2348012345678", "Amina Yusuf")]

    with session_factory() as session:
        organization = session.get(Organization, operator_id)
        assert organization is not None
        assert organization.approval_email_sent_at is not None
        assert organization.approval_whatsapp_sent_at is not None

    login = login_hto(
        HTOLoginRequest(
            email=registration_payload["email"],
            password=registration_payload["password"],
        ),
        request,
    )
    assert login.operator.approval_status == HTOApprovalStatus.APPROVED
    assert jwt.decode(
        login.access_token,
        settings.jwt_secret,
        algorithms=["HS256"],
        audience="hto_dashboard",
        options={"verify_exp": False},
    )["sub"] == str(operator_id)


def test_partial_notification_failure_keeps_approval_and_retries_missing_channel(
    hto_api,
    session_factory,
    email_sender,
    whatsapp_sender,
    registration_payload,
) -> None:
    """AC-04.5: one delivered notification cannot be undone by another failing."""
    request = SimpleNamespace(app=hto_api)
    token = register_and_token(hto_api, email_sender, registration_payload)
    verify_hto_email(HTOVerifyEmailRequest(token=token), request)

    with session_factory() as session:
        organization = session.exec(select(Organization)).one()
        admin = AdminUser(
            id=uuid4(),
            email="admin@damdam.app",
            password_hash="not-used-in-this-test",
        )
        session.add(admin)
        session.commit()
        operator_id = organization.id
        admin_id = admin.id

    whatsapp_sender.fail_approval = True
    with (
        session_factory() as session,
        pytest.raises(HTOAuthError, match="notification_unavailable"),
    ):
        hto_api.state.hto_service.approve(session, operator_id, admin_id)

    with session_factory() as session:
        organization = session.get(Organization, operator_id)
        assert organization is not None
        assert organization.approval_status == HTOApprovalStatus.APPROVED
        assert organization.approval_email_sent_at is not None
        assert organization.approval_whatsapp_sent_at is None
    assert email_sender.approvals == [("amina@example.com", "Amina Yusuf")]
    assert whatsapp_sender.approvals == []

    whatsapp_sender.fail_approval = False
    with session_factory() as session:
        approved = hto_api.state.hto_service.approve(session, operator_id, admin_id)
        assert approved.approval_status == HTOApprovalStatus.APPROVED

    with session_factory() as session:
        organization = session.get(Organization, operator_id)
        assert organization is not None
        assert organization.approval_email_sent_at is not None
        assert organization.approval_whatsapp_sent_at is not None
    assert email_sender.approvals == [("amina@example.com", "Amina Yusuf")]
    assert whatsapp_sender.approvals == [("+2348012345678", "Amina Yusuf")]


def test_duplicate_email_and_invalid_admin_access_are_rejected(
    hto_api, email_sender, registration_payload
) -> None:
    """AC-04.4: approval is admin-only and operator emails stay unique."""
    request = SimpleNamespace(app=hto_api)
    register_and_token(hto_api, email_sender, registration_payload)

    with pytest.raises(HTOAuthError, match="email_already_registered"):
        register_hto(HTORegistrationRequest(**registration_payload), request)

    with pytest.raises(HTOAuthError, match="invalid_admin_token"):
        current_admin(request, None)


def test_admin_rejection_records_reason_and_blocks_login(
    hto_api,
    session_factory,
    email_sender,
    registration_payload,
    settings,
    clock,
) -> None:
    """Rejection stores who/why and permanently blocks that operator's login."""
    request = SimpleNamespace(app=hto_api)
    token = register_and_token(hto_api, email_sender, registration_payload)
    verify_hto_email(HTOVerifyEmailRequest(token=token), request)

    with session_factory() as session:
        organization = session.exec(select(Organization)).one()
        admin = AdminUser(
            id=uuid4(),
            email="admin@damdam.app",
            password_hash="not-used-in-this-test",
        )
        session.add(admin)
        session.commit()
        admin_id = admin.id
        operator_id = organization.id

    admin_token = jwt.encode(
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
    authenticated_admin = current_admin(
        request, HTTPAuthorizationCredentials(scheme="Bearer", credentials=admin_token)
    )

    rejected = reject_hto_operator(
        operator_id,
        HTORejectionRequest(reason="NAHCON licence number could not be verified"),
        request,
        authenticated_admin,
    )
    assert rejected.model_dump(mode="json") == {"approval_status": "rejected"}

    with session_factory() as session:
        organization = session.get(Organization, operator_id)
        assert organization is not None
        assert organization.approval_status == HTOApprovalStatus.REJECTED
        assert organization.rejected_by == admin_id
        assert organization.rejected_at is not None
        assert (
            organization.rejection_reason
            == "NAHCON licence number could not be verified"
        )

    with pytest.raises(HTOAuthError, match="rejected"):
        login_hto(
            HTOLoginRequest(
                email=registration_payload["email"],
                password=registration_payload["password"],
            ),
            request,
        )

    # Rejecting an already-approved operator is an invalid transition —
    # flip the fixture to APPROVED directly to exercise reject()'s own
    # transition guard in isolation from approve()'s symmetric one.
    with session_factory() as session:
        organization = session.get(Organization, operator_id)
        assert organization is not None
        organization.approval_status = HTOApprovalStatus.APPROVED
        session.add(organization)
        session.commit()

    with (
        session_factory() as session,
        pytest.raises(HTOAuthError, match="invalid_approval_transition"),
    ):
        hto_api.state.hto_service.reject(session, operator_id, admin_id, "too late")


def test_second_rejection_errors_instead_of_discarding_new_reason(
    hto_api,
    session_factory,
    email_sender,
    registration_payload,
) -> None:
    """A second reject() call must not silently drop a different admin's
    reason behind a misleadingly successful response — it should error
    the same way rejecting an already-approved operator does."""
    request = SimpleNamespace(app=hto_api)
    token = register_and_token(hto_api, email_sender, registration_payload)
    verify_hto_email(HTOVerifyEmailRequest(token=token), request)

    with session_factory() as session:
        organization = session.exec(select(Organization)).one()
        first_admin = AdminUser(
            id=uuid4(), email="first-admin@damdam.app", password_hash="unused"
        )
        second_admin = AdminUser(
            id=uuid4(), email="second-admin@damdam.app", password_hash="unused"
        )
        session.add(first_admin)
        session.add(second_admin)
        session.commit()
        operator_id = organization.id
        first_admin_id = first_admin.id
        second_admin_id = second_admin.id

    with session_factory() as session:
        rejected = hto_api.state.hto_service.reject(
            session, operator_id, first_admin_id, "First reason: licence invalid"
        )
        assert rejected.approval_status == HTOApprovalStatus.REJECTED

    with (
        session_factory() as session,
        pytest.raises(HTOAuthError, match="invalid_approval_transition"),
    ):
        hto_api.state.hto_service.reject(
            session, operator_id, second_admin_id, "Second reason: duplicate account"
        )

    # The first rejection's reason/actor must be exactly what's on
    # record — the second (failed) call must not have touched it.
    with session_factory() as session:
        organization = session.get(Organization, operator_id)
        assert organization is not None
        assert organization.approval_status == HTOApprovalStatus.REJECTED
        assert organization.rejected_by == first_admin_id
        assert organization.rejection_reason == "First reason: licence invalid"
