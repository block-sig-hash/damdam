from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.profile.family_contacts import FamilyContactService
from app.profile.schemas import (
    FamilyContactCreate,
    FamilyContactResponse,
    FamilyContactUpdate,
)

router = APIRouter(prefix="/me", tags=["pilgrim-profile"])


def _service(request: Request) -> FamilyContactService:
    return cast(FamilyContactService, request.app.state.family_contact_service)


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
