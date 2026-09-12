"""My Line and eSIM installation (US-38, chunk 20).

Five endpoints, and the interesting decision is the shape of the last three: a
profile is **never** returned by a read. Delivering installation material takes
two calls — issue a grant, then spend it — because the alternative makes the
profile as durable as the session, and a session lasts a month.

`GET /v1/me/lines/{id}` can therefore be re-read freely by a status screen, a
pull-to-refresh and a push handler without any of them putting an eSIM into a
response body, a proxy log or a crash report.
"""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from sqlmodel import Session

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.connectivity.credentials import CredentialError, CredentialVault
from app.db import SessionFactory
from app.line.schemas import (
    InstallationConfirmRequest,
    InstallationCredentialResponse,
    InstallationGrantResponse,
    InstallationRedeemRequest,
    LineDetailResponse,
    LineListResponse,
)
from app.line.service import LineError, LineViewService

router = APIRouter(prefix="/me", tags=["My Line"])


def _session(request: Request) -> Session:
    factory = cast(SessionFactory, request.app.state.session_factory)
    return factory()


def _lines(request: Request) -> LineViewService:
    return cast(LineViewService, request.app.state.line_service)


def _vault(request: Request) -> CredentialVault | None:
    return cast(
        "CredentialVault | None",
        getattr(request.app.state, "credential_vault", None),
    )


def _no_store(response: Response) -> None:
    """Keep installation material out of every cache between here and the phone.

    `no-store` rather than `no-cache`: the second permits storing a copy and
    revalidating it, which is exactly the copy that must not exist. A one-time
    eSIM profile cannot be rotated after a leak — there is nothing to rotate,
    only another purchase — so the margin for a cached response is zero.
    """
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.get("/lines", response_model=LineListResponse)
def list_lines(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> LineListResponse:
    """Every line this account **holds**, not every line it paid for.

    An organization buying for its staff is the payer; the holder is the person
    whose phone the profile goes on. My Line is the holder's screen.
    """
    with _session(request) as session:
        return LineListResponse(lines=_lines(request).lines(session, user))


@router.get("/lines/{entitlement_id}", response_model=LineDetailResponse)
def read_line(
    entitlement_id: UUID,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> LineDetailResponse:
    service = _lines(request)
    with _session(request) as session:
        context = service.context(session, entitlement_id, user)
        return service.detail(session, context)


@router.post(
    "/lines/{entitlement_id}/installation/grant",
    response_model=InstallationGrantResponse,
    status_code=status.HTTP_201_CREATED,
)
def issue_installation_grant(
    entitlement_id: UUID,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
) -> InstallationGrantResponse:
    """Authorize one delivery of this line's profile. Returns no profile.

    Two calls rather than one because this half is safe to retry and the next
    half is not. A customer who taps "show my eSIM" twice gets two grants and
    spends one; a single endpoint that returned the code would have spent the
    profile on the first tap, and on a one-time-use profile that is the whole
    purchase.
    """
    _no_store(response)
    service = _lines(request)
    vault = _vault(request)
    with _session(request) as session:
        context = service.context(session, entitlement_id, user)
        credential = service.credential_for(session, context)
        if vault is None:  # pragma: no cover - credential_for already refuses
            raise LineError("installation_material_unavailable")
        try:
            issued = vault.issue_grant(session, credential, user.id)
        except CredentialError as exc:
            # `grant_not_authorized` from the vault would mean the holder check
            # above and the vault's own disagreed. Surfaced as not-found for the
            # same reason as everywhere else here.
            raise LineError("line_not_found") from exc
        body = InstallationGrantResponse(
            grant_token=issued.token,
            expires_at=issued.grant.expires_at,
            one_time_use=credential.one_time_use,
            delivery_count=credential.delivery_count,
        )
        session.commit()
        return body


@router.post(
    "/lines/{entitlement_id}/installation/redeem",
    response_model=InstallationCredentialResponse,
)
def redeem_installation_grant(
    entitlement_id: UUID,
    payload: InstallationRedeemRequest,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
) -> InstallationCredentialResponse:
    """Spend a grant and return the profile, once.

    The path names the line and the token authorizes the delivery; both are
    checked, and they are not two ways of saying the same thing. The vault
    re-derives the holder from the credential itself, so a token cannot be
    replayed against a line it was not issued for even if the path says
    otherwise — the mismatch surfaces as the same unredeemable answer as an
    expired or already-spent grant.
    """
    _no_store(response)
    service = _lines(request)
    vault = _vault(request)
    if vault is None:
        raise LineError("installation_material_unavailable")
    with _session(request) as session:
        context = service.context(session, entitlement_id, user)
        credential = service.credential_for(session, context)
        try:
            lpa = vault.redeem(
                session, payload.grant_token, user.id,
                expected_credential_id=credential.id,
            )
        except CredentialError as exc:
            # One error for expired, spent, wrong-account and never-existed. An
            # attacker learning that a token *existed* learns something.
            raise LineError("grant_not_redeemable") from exc
        body = InstallationCredentialResponse(
            entitlement_id=context.entitlement.id,
            lpa=lpa,
            one_time_use=credential.one_time_use,
            delivery_count=credential.delivery_count,
            reinstall_available=False,
        )
        session.commit()
        return body


@router.post(
    "/lines/{entitlement_id}/installation/confirm",
    response_model=LineDetailResponse,
)
def confirm_installation(
    entitlement_id: UUID,
    payload: InstallationConfirmRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> LineDetailResponse:
    """The device reporting what it did — the only thing that may say so.

    Delivering a QR code is not an installation, and neither is the supplier
    releasing the profile for download. Returning the refreshed line detail
    rather than an empty 204 is deliberate: the screen that reports an install
    is the screen that must then show activation is a *separate* thing still
    pending.
    """
    service = _lines(request)
    with _session(request) as session:
        context = service.context(session, entitlement_id, user)
        service.record_installation_report(session, context, payload.installed)
        refreshed = service.context(session, entitlement_id, user)
        body = service.detail(session, refreshed)
        session.commit()
        return body
