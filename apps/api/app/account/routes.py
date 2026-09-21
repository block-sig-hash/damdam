"""Account, receipts, support and deletion (US-38, chunk 21).

Eleven endpoints under `/v1/me`, and one decision shapes most of them: **a customer
is told why**, never just no. The deletion preflight returns a list of reasons
with codes the app localizes; revoking a stranger's session returns 404 rather
than 403 because a different answer confirms the id is real.

Deletion itself keeps chunk 23's existing `DELETE /v1/me/account` contract — it
still answers 202 and still soft-deletes — and gains the preflight in front of
it. A destructive call whose refusal conditions can only be discovered by making
it is one customers make twice.
"""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlmodel import Session

from app.account.models import SupportRequest
from app.account.schemas import (
    DeletionBlockerView,
    DeletionPreflightResponse,
    ExportJobView,
    PreferenceListResponse,
    PreferenceUpdate,
    PreferenceView,
    ReceiptLineView,
    ReceiptListResponse,
    ReceiptView,
    RevokeAllRequest,
    RevokeAllResponse,
    SessionListResponse,
    SessionView,
    SupportRequestCreate,
    SupportRequestListResponse,
    SupportRequestView,
)
from app.account.service import AccountError, AccountService, Receipt
from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.db import SessionFactory

router = APIRouter(prefix="/me", tags=["Account"])


def _session(request: Request) -> Session:
    factory = cast(SessionFactory, request.app.state.session_factory)
    return factory()


def _service(request: Request) -> AccountService:
    return cast(AccountService, request.app.state.account_service)


def _receipt_view(receipt: Receipt) -> ReceiptView:
    return ReceiptView(
        order_id=receipt.order_id,
        reference=receipt.reference,
        placed_at=receipt.placed_at,
        currency=receipt.currency,
        total_amount=receipt.total_amount,
        payment_state=receipt.payment_state,
        organization_id=receipt.organization_id,
        lines=[
            ReceiptLineView(
                description=line.description,
                quantity=line.quantity,
                unit_amount=line.unit_amount,
                total_amount=line.total_amount,
            )
            for line in receipt.lines
        ],
    )


def _support_view(request: SupportRequest) -> SupportRequestView:
    return SupportRequestView(
        request_id=request.id,
        reference=request.reference,
        category=request.category,
        state=request.state.value,
        subject=request.subject,
        created_at=request.created_at,
        order_id=request.order_id,
        entitlement_id=request.entitlement_id,
        subject_summary=request.subject_summary,
    )


@router.get("/sessions", response_model=SessionListResponse)
def list_sessions(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> SessionListResponse:
    """Every device signed in to this account, recognisable enough to act on."""
    service = _service(request)
    with _session(request) as session:
        current_refresh_token_id = getattr(
            request.state, "current_refresh_token_id", None
        )
        return SessionListResponse(
            sessions=[
                SessionView(
                    session_id=record.id,
                    platform=record.platform,
                    device_label=record.device_label,
                    app_version=record.app_version,
                    last_seen_city=record.last_seen_city,
                    last_seen_country=record.last_seen_country,
                    last_seen_at=record.last_seen_at,
                    revoked_at=record.revoked_at,
                    is_current=(
                        current_refresh_token_id is not None
                        and record.refresh_token_id == current_refresh_token_id
                    ),
                )
                for record in service.sessions(session, user)
            ]
        )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session(
    session_id: UUID,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    """Sign one device out. The refresh token is revoked, not just the row."""
    service = _service(request)
    with _session(request) as session:
        service.revoke_session(session, user, session_id)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/revoke-all", response_model=RevokeAllResponse)
def revoke_all_sessions(
    payload: RevokeAllRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> RevokeAllResponse:
    """Sign every device out, sparing at most the one named.

    `keep_session_id` is verified against this caller's own device list before
    it spares anything, so naming another customer's session revokes everything
    and protects nothing — there is no id a client can send that reaches outside
    its own account.
    """
    service = _service(request)
    with _session(request) as session:
        revoked = service.revoke_all_sessions(
            session, user, except_session_id=payload.keep_session_id
        )
        session.commit()
    return RevokeAllResponse(revoked=revoked)


@router.get("/receipts", response_model=ReceiptListResponse)
def list_receipts(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ReceiptListResponse:
    service = _service(request)
    with _session(request) as session:
        return ReceiptListResponse(
            receipts=[
                _receipt_view(receipt)
                for receipt in service.receipts(session, user, limit=limit)
            ]
        )


@router.get("/receipts/{order_id}", response_model=ReceiptView)
def get_receipt(
    order_id: UUID,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> ReceiptView:
    """Rendered from what was recorded.

    Last year's receipt therefore says last year's price, in last year's
    currency, however much the catalog has moved on since.
    """
    service = _service(request)
    with _session(request) as session:
        return _receipt_view(service.receipt(session, user, order_id))


@router.post(
    "/support-requests",
    response_model=SupportRequestView,
    status_code=status.HTTP_201_CREATED,
)
def open_support_request(
    payload: SupportRequestCreate,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> SupportRequestView:
    """Ask a question with the order or line it is about attached."""
    service = _service(request)
    with _session(request) as session:
        created = service.open_support_request(
            session,
            user,
            category=payload.category,
            subject=payload.subject,
            body=payload.body,
            locale=user.locale,
            order_id=payload.order_id,
            entitlement_id=payload.entitlement_id,
        )
        view = _support_view(created)
        session.commit()
        return view


@router.get("/support-requests", response_model=SupportRequestListResponse)
def list_support_requests(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SupportRequestListResponse:
    service = _service(request)
    with _session(request) as session:
        return SupportRequestListResponse(
            requests=[
                _support_view(row)
                for row in service.support_requests(session, user, limit=limit)
            ]
        )


@router.get("/notification-preferences", response_model=PreferenceListResponse)
def list_preferences(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> PreferenceListResponse:
    service = _service(request)
    with _session(request) as session:
        return PreferenceListResponse(
            preferences=[
                PreferenceView(
                    category=row.category, channel=row.channel, enabled=row.enabled
                )
                for row in service.preferences(session, user)
            ]
        )


@router.put("/notification-preferences", response_model=PreferenceView)
def set_preference(
    payload: PreferenceUpdate,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> PreferenceView:
    service = _service(request)
    with _session(request) as session:
        record = service.set_preference(
            session,
            user,
            category=payload.category,
            channel=payload.channel,
            enabled=payload.enabled,
        )
        view = PreferenceView(
            category=record.category, channel=record.channel, enabled=record.enabled
        )
        session.commit()
        return view


@router.get(
    "/account/deletion-preflight", response_model=DeletionPreflightResponse
)
def deletion_preflight(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> DeletionPreflightResponse:
    """Why this account cannot be deleted yet — before anybody presses anything.

    `detail` is deliberately **not** returned. It can name another member's
    line, and the person deleting their own account does not need to be told
    what somebody else is using; the code is what the app localizes.
    """
    service = _service(request)
    with _session(request) as session:
        assessment = service.assess_deletion(session, user)
        return DeletionPreflightResponse(
            may_delete=assessment.may_delete,
            blockers=[
                DeletionBlockerView(
                    kind=blocker.kind.value,
                    code=blocker.code,
                    amount=blocker.amount,
                    currency=blocker.currency,
                )
                for blocker in assessment.blockers
            ],
        )


@router.post(
    "/account/export",
    response_model=ExportJobView,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_export(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> ExportJobView:
    """Ask for a copy of your own data. One live request at a time."""
    service = _service(request)
    with _session(request) as session:
        job = service.request_export(session, user)
        view = ExportJobView(
            export_id=job.id,
            state=job.state.value,
            requested_at=job.requested_at,
            completed_at=job.completed_at,
            expires_at=job.expires_at,
        )
        session.commit()
        return view


__all__ = ["AccountError", "router"]
