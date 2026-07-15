from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.profile.device_tokens import DeviceTokenService
from app.profile.family_contacts import FamilyContactService
from app.profile.schemas import (
    DeviceTokenResponse,
    DeviceTokenUpsert,
    FamilyContactCreate,
    FamilyContactResponse,
    FamilyContactUpdate,
)

router = APIRouter(prefix="/me", tags=["pilgrim-profile"])


def _service(request: Request) -> FamilyContactService:
    return cast(FamilyContactService, request.app.state.family_contact_service)


def _device_token_service(request: Request) -> DeviceTokenService:
    return cast(DeviceTokenService, request.app.state.device_token_service)


@router.put("/device-token", response_model=DeviceTokenResponse)
def register_device_token(
    payload: DeviceTokenUpsert,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> DeviceTokenResponse:
    with request.app.state.session_factory() as session:
        _device_token_service(request).upsert(session, user.id, payload)
    return DeviceTokenResponse()


@router.post(
    "/family-contact",
    response_model=FamilyContactResponse,
    status_code=201,
)
def create_family_contact(
    payload: FamilyContactCreate,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> FamilyContactResponse:
    with request.app.state.session_factory() as session:
        contact = _service(request).create(session, user.id, payload)
        return FamilyContactResponse.model_validate(contact)


@router.patch("/family-contact", response_model=FamilyContactResponse)
def update_family_contact(
    payload: FamilyContactUpdate,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> FamilyContactResponse:
    with request.app.state.session_factory() as session:
        contact = _service(request).update(session, user.id, payload)
        return FamilyContactResponse.model_validate(contact)
