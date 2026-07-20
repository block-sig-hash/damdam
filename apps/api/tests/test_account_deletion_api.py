from types import SimpleNamespace

from sqlmodel import select

from app.audit.models import AuditLog, AuditOutcome
from app.auth.models import RefreshToken, User, UserStatus
from app.auth.routes import request_otp, verify_otp
from app.auth.schemas import OTPRequest, OTPVerifyRequest
from app.profile.routes import request_account_deletion


def test_account_deletion_starts_grace_period_and_revokes_session(
    api, session_factory, clock
) -> None:
    request = SimpleNamespace(app=api)
    request_otp(OTPRequest(phone_number="08012345678"), request)
    auth = verify_otp(
        OTPVerifyRequest(
            phone_number="08012345678", otp="123456", platform="android"
        ),
        request,
    )
    response = request_account_deletion(request, auth.user)

    assert response.model_dump(mode="json") == {
        "status": "pending_deletion",
        "deletion_scheduled_for": "2026-08-12T00:00:00Z",
    }
    with session_factory() as session:
        user = session.get(User, auth.user.id)
        assert user is not None
        assert user.status == UserStatus.PENDING_DELETION
        assert user.deletion_requested_at == clock().replace(tzinfo=None)
        tokens = session.exec(
            select(RefreshToken).where(RefreshToken.user_id == user.id)
        ).all()
        assert tokens and all(
            token.revoked_at == clock().replace(tzinfo=None) for token in tokens
        )
        audits = session.exec(
            select(AuditLog).where(
                AuditLog.outcome == AuditOutcome.ACCOUNT_SOFT_DELETED.value
            )
        ).all()
        assert len(audits) == 1
