"""The internal operations surface (US-41, chunk 25).

**A separate surface, on a separate audience.** Every route here depends on
`current_admin`, which verifies a token minted for the `admin` audience. An
enterprise administrator — however senior inside their own organization, however
many tenant permissions chunk 07 grants them — holds a token for a different
audience entirely, and cannot reach any of these paths. That is the privilege
separation the assignment asks for, and it is structural: there is no operations
permission an organization could be granted, because operations privileges are
not expressed in the tenant permission matrix at all.

**What this surface deliberately cannot do.** There is no query endpoint, no
balance field, no exception delete and no unmasked read of a line. Money moves
only through `POST /operations/payment-discrepancies`, which posts a balanced
entry through chunk 10's ledger and refuses anything that does not balance. A
supplier attempt is resolved only after the caller asserts reconciliation, which
chunk 11 requires so that a lost response is asked about rather than guessed at.

**Reading is an action too.** The line lookup is a `POST` rather than a `GET`,
because it writes an audit row. A `GET` that records who looked is a `GET` that
lies about being safe to retry, and a caching layer would eventually make the
record wrong.
"""

from __future__ import annotations

import csv
import io
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.admin.routes import current_admin
from app.auth.models import AdminUser
from app.csv_export import csv_safe
from app.fulfilment.models import SupplierAttempt
from app.ledger.models import LedgerAccount
from app.operations.models import OperatorAction, OperatorSubjectKind
from app.operations.schemas import (
    ActionRequest,
    LineLookupRequest,
    LineSupportView,
    OperatorActionListResponse,
    OperatorActionView,
    PaymentDiscrepancyRequest,
    QueueEntryView,
    QueueResponse,
    SupplierResolutionRequest,
)
from app.operations.service import OperationsError, OperationsService
from app.operations.support import SupportDirectory
from app.refunds.models import ExceptionItem, ExceptionKind

router = APIRouter(prefix="/operations", tags=["Operations"])


def _operations(request: Request) -> OperationsService:
    return cast(OperationsService, request.app.state.operations_service)


def _support(request: Request) -> SupportDirectory:
    return cast(SupportDirectory, request.app.state.support_directory)


def _view(action: OperatorAction) -> OperatorActionView:
    return OperatorActionView(
        id=action.id,
        kind=action.kind,
        subject_kind=action.subject_kind,
        subject_reference=action.subject_reference,
        actor_admin_id=action.actor_admin_id,
        reason=action.reason,
        idempotency_key=action.idempotency_key,
        before_state=action.before_state,
        after_state=action.after_state,
        ledger_entry_id=action.ledger_entry_id,
        created_at=action.created_at,
    )


def _exception(session: Session, exception_id: UUID | None) -> ExceptionItem | None:
    if exception_id is None:
        return None
    item = session.get(ExceptionItem, exception_id)
    if item is None:
        raise OperationsError("exception_not_found")
    return item


@router.get("/exceptions", response_model=QueueResponse)
def exception_queue(
    request: Request,
    admin: Annotated[AdminUser, Depends(current_admin)],
    kind: ExceptionKind | None = None,
    reference: Annotated[str | None, Query(max_length=200)] = None,
    include_resolved: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> QueueResponse:
    """What is waiting for a human, searchable by support reference.

    `reference` is a prefix match because the references in this queue are
    structured — `refund:<id>`, `payment:<id>` — and an operator with a ticket
    in front of them holds the whole string, never the middle of it.
    """
    del admin
    with request.app.state.session_factory() as session:
        entries = _operations(request).queue(
            session,
            kind=kind,
            reference=reference,
            include_resolved=include_resolved,
            limit=limit,
        )
        return QueueResponse(
            entries=[
                QueueEntryView(
                    exception_id=entry.exception_id,
                    kind=entry.kind,
                    subject_reference=entry.subject_reference,
                    detail=entry.detail,
                    raised_at=entry.raised_at,
                    resolved_at=entry.resolved_at,
                    action_count=entry.action_count,
                )
                for entry in entries
            ]
        )


@router.get("/actions", response_model=OperatorActionListResponse)
def action_history(
    request: Request,
    admin: Annotated[AdminUser, Depends(current_admin)],
    subject_reference: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> OperatorActionListResponse:
    """Every decision taken on this surface, newest first.

    Append-only by database trigger, so this is the whole history rather than
    the history as of the last person who wanted to change it.
    """
    del admin
    with request.app.state.session_factory() as session:
        actions = _operations(request).history(
            session, subject_reference=subject_reference, limit=limit
        )
        return OperatorActionListResponse(actions=[_view(item) for item in actions])


@router.post(
    "/supplier-attempts/{attempt_id}/resolution",
    response_model=OperatorActionView,
    status_code=201,
)
def resolve_supplier_attempt(
    request: Request,
    attempt_id: UUID,
    payload: SupplierResolutionRequest,
    admin: Annotated[AdminUser, Depends(current_admin)],
) -> OperatorActionView:
    """Settle a purchase whose outcome we lost — after asking the supplier.

    Returns `409 reconciliation_required` when the caller has not asserted that
    somebody reconciled against the original operation reference. This is the
    single most important refusal in the chunk: an operations screen that let a
    human skip it would reintroduce exactly the duplicate purchase chunk 11's
    design exists to prevent.
    """
    with request.app.state.session_factory() as session:
        attempt = session.get(SupplierAttempt, attempt_id)
        if attempt is None:
            raise OperationsError("supplier_attempt_not_found")
        action = _operations(request).resolve_supplier_attempt(
            session,
            attempt,
            actor=admin,
            succeeded=payload.succeeded,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
            reconciled=payload.reconciled,
            provider_reference=payload.provider_reference,
            exception_item=_exception(session, payload.exception_item_id),
        )
        view = _view(action)
        session.commit()
        return view


@router.post(
    "/payment-discrepancies", response_model=OperatorActionView, status_code=201
)
def resolve_payment_discrepancy(
    request: Request,
    payload: PaymentDiscrepancyRequest,
    admin: Annotated[AdminUser, Depends(current_admin)],
) -> OperatorActionView:
    """The only money path here, and it is a balanced posting.

    Both accounts are named by the caller and both must hold the same currency.
    Converting inside an exception queue would invent a rate nobody agreed, so a
    cross-currency compensation is refused rather than rounded.
    """
    with request.app.state.session_factory() as session:
        debit = session.get(LedgerAccount, payload.debit_account_id)
        credit = session.get(LedgerAccount, payload.credit_account_id)
        if debit is None or credit is None:
            raise OperationsError("ledger_account_not_found")
        action = _operations(request).resolve_payment_discrepancy(
            session,
            actor=admin,
            debit_account=debit,
            credit_account=credit,
            amount=payload.amount,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
            subject_reference=payload.subject_reference,
            exception_item=_exception(session, payload.exception_item_id),
        )
        view = _view(action)
        session.commit()
        return view


@router.post(
    "/exceptions/{exception_id}/dismissal",
    response_model=OperatorActionView,
    status_code=201,
)
def dismiss_exception(
    request: Request,
    exception_id: UUID,
    payload: ActionRequest,
    admin: Annotated[AdminUser, Depends(current_admin)],
) -> OperatorActionView:
    """Close an item that needs nothing, with a reason on the record.

    Not a delete. The entry stays, resolved, because "somebody read this and
    decided it was fine" is information, and an empty queue is not evidence of
    a quiet week.
    """
    with request.app.state.session_factory() as session:
        item = session.get(ExceptionItem, exception_id)
        if item is None:
            raise OperationsError("exception_not_found")
        action = _operations(request).dismiss_exception(
            session,
            item,
            actor=admin,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
        )
        view = _view(action)
        session.commit()
        return view


@router.post("/lines/lookup", response_model=LineSupportView, status_code=201)
def lookup_line(
    request: Request,
    payload: LineLookupRequest,
    admin: Annotated[AdminUser, Depends(current_admin)],
) -> LineSupportView:
    """Confirm a line from what a customer can read out. Masked, and recorded.

    `201` rather than `200` because this writes: the audit row naming who looked
    is created before the view is built. There is no unmasked variant and no
    route that returns installation credentials — chunk 15's activation material
    is not readable from this surface by anyone.
    """
    with request.app.state.session_factory() as session:
        record, action = _support(request).lookup_line(
            session,
            actor=admin,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
            line_id=payload.line_id,
            iccid=payload.iccid,
            e164=payload.e164,
        )
        view = LineSupportView(
            line_id=record.line_id,
            carrier=record.carrier,
            iccid_masked=record.iccid_masked,
            e164_masked=record.e164_masked,
            activation_state=record.activation_state,
            network_state=record.network_state,
            provider_status=record.provider_status,
            voice_enabled=record.voice_enabled,
            organization_id=record.organization_id,
            holder_user_id=record.holder_user_id,
            access_action_id=action.id,
        )
        session.commit()
        return view


@router.get("/organizations/{organization_id}/lines.csv")
def export_organization_lines(
    request: Request,
    organization_id: UUID,
    admin: Annotated[AdminUser, Depends(current_admin)],
    reason: Annotated[str, Query(min_length=1, max_length=500)],
    idempotency_key: Annotated[str, Query(min_length=1, max_length=200)],
) -> StreamingResponse:
    """One organization's lines, masked, as a file — and the export is recorded.

    The tenant scope is a join through the order that paid, not a filter the
    caller passes, so there is no parameter an operator could widen. Every cell
    goes through `csv_safe`: carrier names and provider status strings are text
    a supplier chose, and this file is opened in a spreadsheet.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    with request.app.state.session_factory() as session:
        records = _support(request).organization_lines(session, organization_id)
        _operations(request).record_sensitive_access(
            session,
            actor=admin,
            subject_kind=OperatorSubjectKind.ORGANIZATION,
            subject_reference=f"organization:{organization_id}",
            reason=reason,
            idempotency_key=idempotency_key,
        )
        session.commit()

    writer.writerow(
        [
            "line_id",
            "carrier",
            "iccid_masked",
            "number_masked",
            "activation_state",
            "network_state",
            "provider_status",
            "voice_enabled",
        ]
    )
    for record in records:
        writer.writerow(
            [
                csv_safe(str(record.line_id)),
                csv_safe(record.carrier),
                csv_safe(record.iccid_masked or ""),
                csv_safe(record.e164_masked or ""),
                csv_safe(record.activation_state),
                csv_safe(record.network_state),
                csv_safe(record.provider_status or ""),
                "true" if record.voice_enabled else "false",
            ]
        )
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="organization-{organization_id}-lines.csv"'
            )
        },
    )
