"""Resolving *which tenant* a request is acting in, and whether it may (US-29).

Every organization-scoped route goes through `require(...)`. That is the point:
AC-29.4 fails when one endpoint's check drifts from the others, and the only
way to review "every endpoint" is for there to be one thing to review.

Two kinds of principal reach these routes during the transition:

- a **member session** -- an individual's access token plus the organization
  they are acting in, taken from the path or from `X-Organization-Id`. Authority
  is the membership row, read inside this request.
- the **legacy shared organization credential** -- the single email/password on
  `organizations`, which predates memberships. It still opens the manifest and
  reporting flows so the dashboard keeps working, and it is refused for every
  privileged action, because a credential several people share cannot be a
  second factor, cannot be attributed and cannot be revoked for one person.

That refusal is what makes "replace shared organization credentials" real
before the dashboard has migrated: the shared password can no longer add
people, change roles or touch billing settings, so the privileged surface is
individual-only from this chunk onward.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Annotated, cast
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from app.auth.dependencies import get_current_organization
from app.auth.hto import HTOAuthError
from app.auth.models import Organization, User, UserStatus
from app.auth.pin import PINError, PINService
from app.auth.tokens import InvalidRefreshTokenError, TokenService
from app.db import SessionFactory
from app.mfa.service import MfaService
from app.organizations.models import OrganizationMember
from app.organizations.permissions import Permission, requires_step_up
from app.organizations.service import MembershipError, MembershipService

bearer = HTTPBearer(auto_error=False)


class TenantPrincipal(str, Enum):
    MEMBER = "member"
    SHARED_CREDENTIAL = "shared_credential"


@dataclass(frozen=True)
class TenantContext:
    """Who is acting, in which organization, and on what authority."""

    organization: Organization
    principal: TenantPrincipal
    user: User | None = None
    membership: OrganizationMember | None = None

    @property
    def organization_id(self) -> UUID:
        return self.organization.id

    @property
    def actor_user_id(self) -> UUID | None:
        return None if self.user is None else self.user.id


def _memberships(request: Request) -> MembershipService:
    return cast(MembershipService, request.app.state.membership_service)


def _mfa(request: Request) -> MfaService:
    return cast(MfaService, request.app.state.mfa_service)


def _member_session(
    request: Request, credentials: HTTPAuthorizationCredentials
) -> User | None:
    """Decode a member's own access token, or report "not one of those"."""
    token_service = cast(TokenService, request.app.state.otp_service.tokens)
    pin_service = cast(PINService, request.app.state.pin_service)
    try:
        user_id = token_service.decode_access(
            credentials.credentials, pin_service.clock()
        )
    except (InvalidRefreshTokenError, ValueError):
        return None
    factory = cast(SessionFactory, request.app.state.session_factory)
    with factory() as session:
        user = session.get(User, user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            return None
        session.expunge(user)
        return user


def resolve_tenant(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    organization_id: UUID | None,
    header_organization_id: UUID | None = None,
) -> TenantContext:
    """Authenticate first, authorize second, and keep the two answers apart.

    A caller whose token is missing, malformed or expired gets 401 -- their own
    session is the problem and the client needs to refresh it. Only a caller
    who *is* authenticated and simply has no membership gets 403. Collapsing
    the two would leave a client unable to tell "sign in again" from "not your
    organization", and would report an expired session as a cross-tenant
    refusal.

    Neither answer says anything about the target organization: "not a member"
    is returned identically for an organization that does not exist and one
    that belongs to somebody else (AC-29.4).
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise PINError("invalid_access_token")

    user = _member_session(request, credentials)
    if user is not None:
        target = organization_id or header_organization_id
        if target is None:
            # A member session that does not say which tenant it is acting in
            # is refused rather than defaulted. Picking "their only
            # organization" would change meaning the day they join a second.
            raise MembershipError("organization_not_selected")
        factory = cast(SessionFactory, request.app.state.session_factory)
        with factory() as session:
            membership = _memberships(request).require_membership(
                session, target, user.id
            )
            organization = session.get(Organization, target)
            if organization is None:  # pragma: no cover - FK guarantees this
                raise MembershipError("not_a_member")
            session.expunge(membership)
            session.expunge(organization)
        return TenantContext(
            organization=organization,
            principal=TenantPrincipal.MEMBER,
            user=user,
            membership=membership,
        )

    # Fall back to the legacy shared credential.
    try:
        organization = get_current_organization(request, credentials)
    except HTOAuthError as exc:
        # Neither a member session nor an operator session: the credential
        # itself is the problem, so this is authentication, not authorization.
        raise PINError("invalid_access_token") from exc
    if organization_id is not None and organization.id != organization_id:
        # A shared credential for one organization asking about another reads
        # as "not a member", never as "forbidden": the distinction would
        # confirm that the other organization exists.
        raise MembershipError("not_a_member")
    return TenantContext(
        organization=organization, principal=TenantPrincipal.SHARED_CREDENTIAL
    )


def _authorize(
    request: Request,
    context: TenantContext,
    permission: Permission,
) -> TenantContext:
    if context.principal is TenantPrincipal.SHARED_CREDENTIAL:
        if requires_step_up(permission):
            # The whole reason this chunk exists. A password several people
            # know cannot be attributed to one of them, cannot carry a second
            # factor, and cannot be taken away from one of them.
            raise MembershipError("shared_credential_forbidden")
        return context

    assert context.membership is not None and context.user is not None
    factory = cast(SessionFactory, request.app.state.session_factory)
    with factory() as session:
        _memberships(request).require_permission(
            session,
            context.organization_id,
            context.user.id,
            permission,
            mfa=_mfa(request),
        )
    return context


def require(permission: Permission) -> object:
    """Build the dependency that guards one organization-scoped route.

    Used for routes that carry `{organization_id}` in the path.
    """

    def dependency(
        request: Request,
        organization_id: UUID,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None, Depends(bearer)
        ],
    ) -> TenantContext:
        context = resolve_tenant(request, credentials, organization_id)
        return _authorize(request, context, permission)

    return Depends(dependency)


def require_tenant(permission: Permission) -> object:
    """The same guard for the legacy routes that carry no organization in the path.

    A member session names its tenant with `X-Organization-Id`; the legacy
    shared credential names it by being that organization's credential.
    """

    def dependency(
        request: Request,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None, Depends(bearer)
        ],
        x_organization_id: Annotated[UUID | None, Header()] = None,
    ) -> TenantContext:
        context = resolve_tenant(request, credentials, None, x_organization_id)
        return _authorize(request, context, permission)

    return Depends(dependency)


def current_session(request: Request) -> Session:  # pragma: no cover - helper
    factory = cast(SessionFactory, request.app.state.session_factory)
    return factory()


__all__ = [
    "PINError",
    "TenantContext",
    "TenantPrincipal",
    "require",
    "require_tenant",
    "resolve_tenant",
]
