from datetime import timedelta, timezone
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from app.account.service import AccountError, AccountService
from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.calling.sessions import ClientSessionService
from app.profile.device_tokens import DeviceTokenService
from app.profile.schemas import (
    AccountDeletionResponse,
    DeviceTokenResponse,
    DeviceTokenUpsert,
)
from app.retention.service import RetentionService
from app.retirement import (
    EMERGENCY_CONTACT,
    FAMILY_CONTACTS,
    RETIRED_RESPONSES,
    RetiredFeatureError,
)

router = APIRouter(prefix="/me", tags=["pilgrim-profile"])


def _device_token_service(request: Request) -> DeviceTokenService:
    return cast(DeviceTokenService, request.app.state.device_token_service)


def _retention_service(request: Request) -> RetentionService:
    return cast(RetentionService, request.app.state.retention_service)


def _account_service(request: Request) -> AccountService:
    return cast(AccountService, request.app.state.account_service)


def _calling_sessions(request: Request) -> ClientSessionService:
    return cast(ClientSessionService, request.app.state.client_session_service)


@router.delete("/account", response_model=AccountDeletionResponse, status_code=202)
def request_account_deletion(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> AccountDeletionResponse:
    with request.app.state.session_factory() as session:
        account = session.get(User, user.id)
        if account is None:  # pragma: no cover - a valid token implies a row
            raise AccountError("account_not_found")
        if not _account_service(request).assess_deletion(session, account).may_delete:
            raise AccountError("account_deletion_blocked")
        _calling_sessions(request).revoke(
            session, account, reason="account_deletion"
        )
        deleted_user = _retention_service(request).request_account_deletion(
            session, user.id
        )
    assert deleted_user.deletion_requested_at is not None
    requested_at = deleted_user.deletion_requested_at
    if requested_at.tzinfo is None:
        requested_at = requested_at.replace(tzinfo=timezone.utc)
    return AccountDeletionResponse(
        deletion_scheduled_for=requested_at + timedelta(days=30)
    )


@router.put("/device-token", response_model=DeviceTokenResponse)
def register_device_token(
    payload: DeviceTokenUpsert,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> DeviceTokenResponse:
    with request.app.state.session_factory() as session:
        _device_token_service(request).upsert(session, user.id, payload)
    return DeviceTokenResponse()


# Family and emergency contacts are retired with the SOS and check-in workflow
# (US-30, chunk 04B). The routes stay registered so an old client is told the
# nomination flow is gone rather than silently failing to enrol anyone who would
# be notified in an emergency. Existing `family_contacts` rows are untouched.


@router.post("/family-contact", status_code=410, responses=RETIRED_RESPONSES)
def create_family_contact() -> None:
    raise RetiredFeatureError(FAMILY_CONTACTS)


@router.patch("/family-contact", status_code=410, responses=RETIRED_RESPONSES)
def update_family_contact() -> None:
    raise RetiredFeatureError(FAMILY_CONTACTS)


@router.get("/emergency-contact", status_code=410, responses=RETIRED_RESPONSES)
def get_emergency_contact() -> None:
    raise RetiredFeatureError(EMERGENCY_CONTACT)
