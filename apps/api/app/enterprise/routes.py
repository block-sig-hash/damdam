"""Enterprise funding, departmental reports and offboarding (US-40, chunk 24).

Six endpoints, and the permissions split along the line the assignment draws:
*add audited exports and financial permissions.*

- **Money is `billing:read`.** Funding, budgets and departmental totals are what
  a finance person needs and an administrator does not automatically get.
- **The export is `report:export`**, and it writes an audit entry naming who
  downloaded what. A tenant's staff spend leaving on a laptop is the kind of
  thing that needs a record, not a log line.
- **Offboarding is `member:revoke`**, which chunk 07 puts behind a second
  factor: ending somebody's access is exactly the kind of action a stolen
  session should not be able to perform. **Reading** a departure record is
  `people:read` instead — it names who left and why, which is people data rather
  than membership data, and requiring a second factor to look at a list nobody
  can act on would train administrators to step up for everything.

Every handler reads the organization from the resolved tenant context and
discards the path segment, as chunks 22 and 23 do.
"""

from __future__ import annotations

import csv
import io
from datetime import timedelta
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.audit.models import AuditEventType, AuditOutcome
from app.audit.service import AuditLogService
from app.csv_export import csv_safe
from app.enterprise.models import OrganizationOffboarding
from app.enterprise.offboarding import OffboardingService, OffboardingSummary
from app.enterprise.reporting import EnterpriseReportingService
from app.enterprise.schemas import (
    DepartmentalReportView,
    DepartmentTotalView,
    FundingView,
    OffboardingActionView,
    OffboardingDetailView,
    OffboardingListResponse,
    OffboardingRequest,
    OffboardingView,
)
from app.organizations.dependencies import TenantContext, require
from app.organizations.permissions import Permission

router = APIRouter(prefix="/organizations", tags=["Enterprise"])

#: How far back a report looks when the caller does not say. A month is the
#: period an invoice covers and the one an administrator has in mind.
DEFAULT_PERIOD_DAYS = 30


def _reporting(request: Request) -> EnterpriseReportingService:
    return cast(
        EnterpriseReportingService, request.app.state.enterprise_reporting_service
    )


def _offboarding(request: Request) -> OffboardingService:
    return cast(OffboardingService, request.app.state.offboarding_service)


def _audit(request: Request) -> AuditLogService:
    return cast(AuditLogService, request.app.state.audit_service)


def _offboarding_view(
    run: OrganizationOffboarding, summary: OffboardingSummary
) -> OffboardingView:
    return OffboardingView(
        offboarding_id=run.id,
        person_id=run.person_id,
        state=summary.state,
        confirmed=summary.confirmed,
        pending_carrier=summary.pending_carrier,
        not_applicable=summary.not_applicable,
        failed=summary.failed,
        requested_at=run.requested_at,
        completed_at=run.completed_at,
    )


@router.get("/{organization_id}/funding", response_model=FundingView)
def get_funding(
    organization_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.BILLING_READ)],
    currency: Annotated[str, Query(min_length=3, max_length=3)] = "NGN",
) -> FundingView:
    """Credit, holds and any recorded cap — kept as three separate numbers."""
    del organization_id
    service = _reporting(request)
    with request.app.state.session_factory() as session:
        summary = service.funding(
            session,
            context.organization_id,
            currency.upper(),
            since=service.clock() - timedelta(days=DEFAULT_PERIOD_DAYS),
        )
        return FundingView(
            currency=summary.currency,
            balance=summary.balance,
            held=summary.held,
            available=summary.available,
            period_cap=summary.period_cap,
            committed_this_period=summary.committed_this_period,
            spent_this_period=summary.spent_this_period,
            headroom=summary.headroom,
            pooling=summary.pooling,
            pooling_note=summary.pooling_note,
        )


@router.get(
    "/{organization_id}/reports/departments",
    response_model=DepartmentalReportView,
)
def get_departmental_report(
    organization_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.REPORT_READ)],
    currency: Annotated[str, Query(min_length=3, max_length=3)] = "NGN",
    by: Annotated[str, Query(pattern="^(team|cost_centre)$")] = "team",
    days: Annotated[int, Query(ge=1, le=365)] = DEFAULT_PERIOD_DAYS,
) -> DepartmentalReportView:
    """Spend by team or cost centre, with the freshness of the usage half."""
    del organization_id
    service = _reporting(request)
    now = service.clock()
    with request.app.state.session_factory() as session:
        report = service.departmental(
            session,
            context.organization_id,
            currency.upper(),
            period_from=now - timedelta(days=days),
            period_to=now + timedelta(days=1),
            by=by,
        )
        return DepartmentalReportView(
            organization_id=report.organization_id,
            currency=report.currency,
            period_from=report.period_from,
            period_to=report.period_to,
            totals=[
                DepartmentTotalView(
                    key=total.key,
                    label=total.label,
                    people=total.people,
                    lines=total.lines,
                    purchased_amount=total.purchased_amount,
                    usage_amount=total.usage_amount,
                    currency=total.currency,
                )
                for total in report.totals
            ],
            purchased_total=report.purchased_total,
            usage_total=report.usage_total,
            observed_through=report.observed_through,
        )


@router.get("/{organization_id}/reports/departments.csv")
def export_departmental_report(
    organization_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.REPORT_EXPORT)],
    currency: Annotated[str, Query(min_length=3, max_length=3)] = "NGN",
    by: Annotated[str, Query(pattern="^(team|cost_centre)$")] = "team",
    days: Annotated[int, Query(ge=1, le=365)] = DEFAULT_PERIOD_DAYS,
) -> StreamingResponse:
    """The same report as a file, audited and safe to open.

    Two things happen here that do not happen on the JSON route. Every cell
    passes through `csv_safe`, because team and cost-centre names are text a
    customer typed and this file is opened in a spreadsheet. And the download is
    **recorded** — a tenant's staff spend leaving on somebody's laptop is a fact
    worth being able to reconstruct later.

    The freshness line is written into the file itself. A CSV outlives the
    screen it was downloaded from, and a total with no "as of" becomes a
    current figure the moment it is pasted into a deck.
    """
    del organization_id
    service = _reporting(request)
    now = service.clock()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    with request.app.state.session_factory() as session:
        report = service.departmental(
            session,
            context.organization_id,
            currency.upper(),
            period_from=now - timedelta(days=days),
            period_to=now + timedelta(days=1),
            by=by,
        )
        writer.writerow(
            ["Department", "People", "Lines", "Purchased", "Used", "Currency"]
        )
        for total in report.totals:
            writer.writerow(
                [
                    csv_safe(total.label),
                    total.people,
                    total.lines,
                    str(total.purchased_amount),
                    str(total.usage_amount),
                    total.currency,
                ]
            )
        writer.writerow([])
        writer.writerow(
            [
                "Usage observed through",
                report.observed_through.isoformat()
                if report.observed_through
                else "no usage has been observed",
            ]
        )
        _audit(request).record(
            session,
            AuditEventType.ADMIN_ACTION,
            AuditOutcome.ENTERPRISE_REPORT_EXPORTED,
            user_id=context.actor_user_id,
            reference=f"organization:{context.organization_id}",
            details=f"departmental report by {by} in {currency.upper()}",
        )
        session.commit()
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="departments.csv"'
        },
    )


@router.post(
    "/{organization_id}/offboardings",
    response_model=OffboardingDetailView,
    status_code=201,
)
def offboard_person(
    organization_id: UUID,
    payload: OffboardingRequest,
    request: Request,
    context: Annotated[TenantContext, require(Permission.MEMBER_REVOKE)],
) -> OffboardingDetailView:
    """End somebody's work relationship. Their personal service is untouched.

    Idempotent: a second request for somebody already offboarded returns the
    run that exists rather than re-asking a carrier to suspend a line it is
    already suspending.
    """
    del organization_id
    service = _offboarding(request)
    with request.app.state.session_factory() as session:
        summary = service.offboard(
            session,
            context.organization_id,
            payload.person_id,
            requested_by_user_id=context.actor_user_id,
            reason=payload.reason,
        )
        run = service.run(session, context.organization_id, summary.offboarding_id)
        view = _detail(service, session, run, summary)
        session.commit()
        return view


@router.get(
    "/{organization_id}/offboardings", response_model=OffboardingListResponse
)
def list_offboardings(
    organization_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.PEOPLE_READ)],
) -> OffboardingListResponse:
    del organization_id
    service = _offboarding(request)
    with request.app.state.session_factory() as session:
        runs = service.history(session, context.organization_id)
        return OffboardingListResponse(
            offboardings=[
                _offboarding_view(run, service.summary(session, run)) for run in runs
            ]
        )


@router.get(
    "/{organization_id}/offboardings/{offboarding_id}",
    response_model=OffboardingDetailView,
)
def get_offboarding(
    organization_id: UUID,
    offboarding_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.PEOPLE_READ)],
) -> OffboardingDetailView:
    """Every action and its outcome, including what a carrier has not answered."""
    del organization_id
    service = _offboarding(request)
    with request.app.state.session_factory() as session:
        run = service.run(session, context.organization_id, offboarding_id)
        return _detail(service, session, run, service.summary(session, run))


def _detail(
    service: OffboardingService,
    session: Session,
    run: OrganizationOffboarding,
    summary: OffboardingSummary,
) -> OffboardingDetailView:
    base = _offboarding_view(run, summary)
    return OffboardingDetailView(
        **base.model_dump(),
        actions=[
            OffboardingActionView(
                action_id=action.id,
                kind=action.kind,
                state=action.state,
                target_reference=action.target_reference,
                detail=action.detail,
                requested_at=action.requested_at,
                confirmed_at=action.confirmed_at,
            )
            for action in service.actions(session, run)
        ],
    )


__all__ = ["router"]
