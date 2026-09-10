"""Consumer session, service and invitation-preview endpoints (US-37).

Three reads. They exist because the mobile app cannot decide what to draw
without them: whether to show a signed-out stack, a "you have no service yet"
Home, or a Home with a line on it; and whether an invitation link the app was
opened with belongs to the account that is currently signed in.
"""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.consumer.schemas import (
    InvitationPreviewRequest,
    InvitationPreviewResponse,
    ServicesResponse,
    SessionResponse,
)
from app.consumer.service import ConsumerService
from app.db import SessionFactory
from app.organizations.invitations import InvitationService

router = APIRouter(prefix="/me", tags=["Consumer"])
invitation_preview_router = APIRouter(prefix="/invitations", tags=["Consumer"])


def _consumer(request: Request) -> ConsumerService:
    return cast(ConsumerService, request.app.state.consumer_service)


def _invitations(request: Request) -> InvitationService:
    return cast(InvitationService, request.app.state.invitation_service)


def _session(request: Request) -> Session:
    factory = cast(SessionFactory, request.app.state.session_factory)
    return factory()


@router.get("/session", response_model=SessionResponse)
def read_session(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> SessionResponse:
    """One round trip to the first authenticated frame.

    Splitting this into "who am I" and "what do I have" would make every cold
    start render a tab bar against an unknown service state and then correct
    itself, which is the flicker the old Home screen had.
    """
    consumer = _consumer(request)
    with _session(request) as session:
        emails, phones = consumer.verified_identifiers(session, user)
        view = consumer.services(session, user)
        return SessionResponse(
            user_id=user.id,
            locale=user.locale,
            verified_emails=emails,
            verified_phone_numbers=phones,
            service_state=view.state,
            organizations=consumer.memberships(session, user),
            pending_invitations=consumer.pending_invitation_count(
                session, user, _invitations(request)
            ),
        )


@router.get("/services", response_model=ServicesResponse)
def read_services(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> ServicesResponse:
    consumer = _consumer(request)
    with _session(request) as session:
        view = consumer.services(session, user)
        return ServicesResponse(
            service_state=view.state, services=list(view.services)
        )


@invitation_preview_router.post("/preview", response_model=InvitationPreviewResponse)
def preview_invitation(
    payload: InvitationPreviewRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> InvitationPreviewResponse:
    """Read an invitation link without accepting it (AC-37.3, AC-37.4).

    POST rather than GET, and the token in the body rather than the path,
    because an invitation token is a bearer credential for a membership and a
    URL is the one part of a request that gets written down everywhere.
    """
    consumer = _consumer(request)
    with _session(request) as session:
        return consumer.preview_invitation(
            session, user, payload.token, _invitations(request)
        )
