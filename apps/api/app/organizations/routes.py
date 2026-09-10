"""Organization membership, invitation and second-factor endpoints (US-29).

Every organization-scoped handler takes its authority from `require(...)`, and
none of them re-derives it. A handler that re-checked a role locally would be a
second copy of the matrix, and the second copy is the one that drifts.
"""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from sqlmodel import Session, select

from app.auth.dependencies import get_current_user
from app.auth.models import Organization, User
from app.mfa.service import MfaError, MfaService
from app.organizations.dependencies import TenantContext, require
from app.organizations.invitations import InvitationError, InvitationService
from app.organizations.models import MembershipStatus, OrganizationMember
from app.organizations.permissions import Permission
from app.organizations.schemas import (
    InvitationAcceptRequest,
    InvitationCreatedResponse,
    InvitationListResponse,
    InvitationRequest,
    InvitationSummary,
    MemberListResponse,
    MembershipResponse,
    MemberSummary,
    MfaCodeRequest,
    MfaConfirmedResponse,
    MfaEnrollmentResponse,
    OrganizationListResponse,
    OrganizationSummary,
    RoleChangeRequest,
    StepUpRequest,
    StepUpResponse,
)
from app.organizations.service import MembershipError, MembershipService

router = APIRouter(prefix="/organizations", tags=["Organizations"])
invitation_router = APIRouter(prefix="/invitations", tags=["Organizations"])
mfa_router = APIRouter(prefix="/auth/mfa", tags=["Organizations"])


def _memberships(request: Request) -> MembershipService:
    return cast(MembershipService, request.app.state.membership_service)


def _invitations(request: Request) -> InvitationService:
    return cast(InvitationService, request.app.state.invitation_service)


def _mfa(request: Request) -> MfaService:
    return cast(MfaService, request.app.state.mfa_service)


def _acting_membership(
    request: Request, session: Session, context: TenantContext
) -> OrganizationMember:
    """The actor row, re-read in this request's own transaction.

    `require(...)` already proved the membership exists; this loads it into the
    session the handler is about to write through, so the service's own
    re-resolution and row locks operate on live objects rather than on a copy
    fetched by the dependency.
    """
    if context.user is None:
        raise MembershipError("shared_credential_forbidden")
    return _memberships(request).require_membership(
        session, context.organization_id, context.user.id
    )


# --- the caller's own organizations ---------------------------------------


@router.get("", response_model=OrganizationListResponse)
def list_my_organizations(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> OrganizationListResponse:
    """Driven from memberships, so it can only ever list the caller's own."""
    summaries: list[OrganizationSummary] = []
    with request.app.state.session_factory() as session:
        rows = session.exec(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.status == MembershipStatus.ACTIVE,
            )
        ).all()
        for row in rows:
            organization = session.get(Organization, row.organization_id)
            if organization is None:  # pragma: no cover - the FK guarantees this
                continue
            summaries.append(
                OrganizationSummary(
                    id=organization.id, name=organization.name, role=row.role
                )
            )
    return OrganizationListResponse(organizations=summaries)


# --- members ---------------------------------------------------------------


@router.get("/{organization_id}/members", response_model=MemberListResponse)
def list_members(
    organization_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.MEMBER_READ)],
) -> MemberListResponse:
    del organization_id
    with request.app.state.session_factory() as session:
        members = _memberships(request).list_members(
            session, context.organization_id
        )
        return MemberListResponse(
            members=[
                MemberSummary.model_validate(member, from_attributes=True)
                for member in members
            ]
        )


@router.patch(
    "/{organization_id}/members/{user_id}", response_model=MembershipResponse
)
def change_member_role(
    organization_id: UUID,
    user_id: UUID,
    payload: RoleChangeRequest,
    request: Request,
    context: Annotated[TenantContext, require(Permission.MEMBER_ROLE_CHANGE)],
) -> MembershipResponse:
    del organization_id
    with request.app.state.session_factory() as session:
        actor = _acting_membership(request, session, context)
        membership = _memberships(request).change_role(
            session,
            actor=actor,
            target_user_id=user_id,
            new_role=payload.role,
            mfa=_mfa(request),
        )
        session.commit()
        session.refresh(membership)
        return MembershipResponse.model_validate(membership, from_attributes=True)


@router.delete(
    "/{organization_id}/members/{user_id}", response_model=MembershipResponse
)
def revoke_member(
    organization_id: UUID,
    user_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.MEMBER_REVOKE)],
) -> MembershipResponse:
    del organization_id
    with request.app.state.session_factory() as session:
        actor = _acting_membership(request, session, context)
        membership = _memberships(request).revoke(
            session,
            actor=actor,
            target_user_id=user_id,
            mfa=_mfa(request),
        )
        session.commit()
        session.refresh(membership)
        return MembershipResponse.model_validate(membership, from_attributes=True)


# --- invitations, from the organization's side -----------------------------


@router.post(
    "/{organization_id}/invitations",
    response_model=InvitationCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_invitation(
    organization_id: UUID,
    payload: InvitationRequest,
    request: Request,
    context: Annotated[TenantContext, require(Permission.MEMBER_INVITE)],
) -> InvitationCreatedResponse:
    del organization_id
    with request.app.state.session_factory() as session:
        actor = _acting_membership(request, session, context)
        issued = _invitations(request).invite(
            session, actor=actor, email=payload.email, role=payload.role
        )
        session.commit()
        session.refresh(issued.invitation)
        return InvitationCreatedResponse(
            invitation=InvitationSummary.model_validate(
                issued.invitation, from_attributes=True
            ),
            token=issued.token,
        )


@router.get(
    "/{organization_id}/invitations", response_model=InvitationListResponse
)
def list_invitations(
    organization_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.MEMBER_READ)],
) -> InvitationListResponse:
    del organization_id
    with request.app.state.session_factory() as session:
        pending = _invitations(request).list_pending(
            session, context.organization_id
        )
        return InvitationListResponse(
            invitations=[
                InvitationSummary.model_validate(item, from_attributes=True)
                for item in pending
            ]
        )


@router.delete(
    "/{organization_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_invitation(
    organization_id: UUID,
    invitation_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.MEMBER_INVITE)],
) -> Response:
    del organization_id
    with request.app.state.session_factory() as session:
        actor = _acting_membership(request, session, context)
        _invitations(request).revoke(
            session, actor=actor, invitation_id=invitation_id
        )
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- invitations, from the recipient's side --------------------------------


@invitation_router.get("", response_model=InvitationListResponse)
def list_my_invitations(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> InvitationListResponse:
    """Only invitations addressed to identifiers this account has *proved*."""
    with request.app.state.session_factory() as session:
        pending = _invitations(request).list_for_user(session, user)
        return InvitationListResponse(
            invitations=[
                InvitationSummary.model_validate(item, from_attributes=True)
                for item in pending
            ]
        )


@invitation_router.post("/accept", response_model=MembershipResponse)
def accept_invitation(
    payload: InvitationAcceptRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> MembershipResponse:
    if (payload.token is None) == (payload.invitation_id is None):
        # Exactly one. Accepting "whichever was supplied" would let a caller
        # send both and depend on an ordering that is not part of the contract.
        raise InvitationError("invitation_invalid")
    with request.app.state.session_factory() as session:
        service = _invitations(request)
        if payload.token is not None:
            membership = service.accept_by_token(
                session, user=user, token=payload.token
            )
        else:
            assert payload.invitation_id is not None
            membership = service.accept(
                session, user=user, invitation_id=payload.invitation_id
            )
        session.commit()
        session.refresh(membership)
        return MembershipResponse.model_validate(membership, from_attributes=True)


# --- second factor ---------------------------------------------------------


@mfa_router.post("/enroll", response_model=MfaEnrollmentResponse)
def begin_mfa_enrollment(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> MfaEnrollmentResponse:
    with request.app.state.session_factory() as session:
        try:
            enrollment = _mfa(request).begin_enrollment(session, user)
        except MfaError:
            session.commit()
            raise
        response = MfaEnrollmentResponse(
            secret=enrollment.secret_base32,
            otpauth_uri=enrollment.otpauth_uri,
        )
        session.commit()
    return response


@mfa_router.post("/enroll/confirm", response_model=MfaConfirmedResponse)
def confirm_mfa_enrollment(
    payload: MfaCodeRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> MfaConfirmedResponse:
    with request.app.state.session_factory() as session:
        try:
            confirmed = _mfa(request).confirm_enrollment(session, user, payload.code)
        except MfaError:
            # Invalid guesses update the durable attempt budget. Letting the
            # context manager roll this transaction back would make the HTTP
            # lockout disappear even though direct service tests pass.
            session.commit()
            raise
        response = MfaConfirmedResponse(recovery_codes=confirmed.recovery_codes)
        session.commit()
    return response


@mfa_router.post("/disable", status_code=status.HTTP_204_NO_CONTENT)
def disable_mfa(
    payload: StepUpRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    if (payload.code is None) == (payload.recovery_code is None):
        raise MfaError("mfa_code_invalid")
    with request.app.state.session_factory() as session:
        try:
            if payload.code is not None:
                _mfa(request).disable(session, user, payload.code)
            else:
                assert payload.recovery_code is not None
                _mfa(request).disable_with_recovery_code(
                    session, user, payload.recovery_code
                )
        except MfaError:
            session.commit()
            raise
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{organization_id}/step-up", response_model=StepUpResponse)
def step_up(
    organization_id: UUID,
    payload: StepUpRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> StepUpResponse:
    """Prove the second factor for one organization.

    Gated on `ORG_READ` rather than on the privileged permission being sought:
    the caller must already be a member to step up at all, but requiring the
    target permission here would turn this endpoint into a way to ask whether
    they hold it.
    """
    if (payload.code is None) == (payload.recovery_code is None):
        raise MfaError("mfa_code_invalid")
    with request.app.state.session_factory() as session:
        memberships = _memberships(request)
        memberships.require_permission(
            session, organization_id, user.id, Permission.ORG_READ
        )
        service = _mfa(request)
        try:
            if payload.code is not None:
                elevation = service.elevate(
                    session,
                    user,
                    organization_id,
                    payload.code,
                    memberships=memberships,
                )
            else:
                assert payload.recovery_code is not None
                elevation = service.elevate_with_recovery_code(
                    session, user, organization_id, payload.recovery_code
                )
        except MfaError:
            session.commit()
            raise
        session.commit()
        session.refresh(elevation)
        return StepUpResponse(expires_at=elevation.expires_at)
