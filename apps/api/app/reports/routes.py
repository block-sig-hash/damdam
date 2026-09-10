from datetime import date
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from app.organizations.dependencies import TenantContext, require_tenant
from app.organizations.permissions import Permission
from app.reports.service import ProvisioningReportService

router = APIRouter(prefix="/hto/reports", tags=["HTO reports"])


@router.get("/provisioning.csv")
def download_provisioning_report(
    request: Request,
    context: Annotated[TenantContext, require_tenant(Permission.REPORT_EXPORT)],
    manifest_id: Annotated[UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> Response:
    service = cast(ProvisioningReportService, request.app.state.report_service)
    with request.app.state.session_factory() as session:
        csv_text = service.generate_csv(
            session, context.organization, manifest_id, date_from, date_to
        )
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": ('attachment; filename="provisioning-report.csv"')
        },
    )
