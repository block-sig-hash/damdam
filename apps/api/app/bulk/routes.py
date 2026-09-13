"""Bulk orders, assignment and activation requests (US-40, chunk 23).

Nine endpoints, split across two audiences and therefore two permissions.

**The organization's administrators** plan, fund, provision, resume and cancel.
Those take `order:place` — buying for fifty people is buying — and read through
`order:read`. Billing and member roles reach neither, which is chunk 07's matrix
doing the work rather than a check per handler.

**The recipient** redeems. That endpoint takes an ordinary member session and no
organization permission at all, because the person claiming a line is usually
not a member of the organization that bought it — they are an employee with a
phone, and requiring them to be an administrator to accept a work SIM would be
exactly backwards.

Every administrator handler reads the organization from the resolved tenant
context and discards the path segment, the same as chunk 22's.
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel import Session, col, select

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.bulk.models import ActivationRequest, BulkJob, BulkJobItem
from app.bulk.schemas import (
    ActivationRequestIssued,
    ActivationRequestView,
    BulkActivationRedeemRequest,
    BulkItemListResponse,
    BulkItemView,
    BulkJobCreate,
    BulkJobListResponse,
    BulkJobProgressView,
    BulkJobView,
    CancelRequest,
)
from app.bulk.service import BulkError, BulkProvisioningService, JobProgress
from app.catalog.market import SalesMarket
from app.catalog.models import Product
from app.catalog.service import CatalogService
from app.organizations.dependencies import TenantContext, require
from app.organizations.permissions import Permission

router = APIRouter(prefix="/organizations", tags=["Bulk provisioning"])
recipient_router = APIRouter(prefix="/me", tags=["Bulk provisioning"])


def _seller_for(session: Session, job: BulkJob) -> UUID:
    """The entity that sells this job's lines, as recorded when it was planned.

    Read from the job's own market rather than re-derived: an order's seller
    must not change after the fact, and a market republished under a different
    entity would otherwise rewrite who sold last quarter's lines.
    """
    market = session.get(SalesMarket, job.sales_market_id)
    if market is None:  # pragma: no cover - FK guarantees this
        raise BulkError("market_not_found")
    if market.legal_entity_id is None:
        # The market lost its seller between planning and provisioning. Better
        # to stop than to attribute fifty lines to a party nobody chose.
        raise BulkError("market_has_no_seller")
    return market.legal_entity_id


def _service(request: Request) -> BulkProvisioningService:
    return cast(BulkProvisioningService, request.app.state.bulk_service)


def _job_view(job: BulkJob) -> BulkJobView:
    return BulkJobView(
        job_id=job.id,
        state=job.state,
        product_id=job.product_id,
        currency=job.currency,
        unit_amount=job.unit_amount,
        recipient_count=job.recipient_count,
        order_id=job.order_id,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


def _progress_view(progress: JobProgress) -> BulkJobProgressView:
    return BulkJobProgressView(
        job_id=progress.job_id,
        state=progress.state,
        recipient_count=progress.recipient_count,
        reserved=progress.reserved,
        provisioned=progress.provisioned,
        failed=progress.failed,
        unknown=progress.unknown,
        invalid=progress.invalid,
        cancelled=progress.cancelled,
        outstanding=progress.outstanding,
    )


def _item_view(item: BulkJobItem) -> BulkItemView:
    return BulkItemView(
        item_id=item.id,
        person_id=item.person_id,
        state=item.state,
        error_code=item.error_code,
        order_item_id=item.order_item_id,
        provisioned_at=item.provisioned_at,
    )


def _request_view(record: ActivationRequest) -> ActivationRequestView:
    return ActivationRequestView(
        request_id=record.id,
        item_id=record.bulk_job_item_id,
        person_id=record.person_id,
        state=record.state,
        delivered_to=record.delivered_to,
        expires_at=record.expires_at,
        redeemed_at=record.redeemed_at,
    )


@router.post(
    "/{organization_id}/bulk-jobs",
    response_model=BulkJobProgressView,
    status_code=201,
)
def plan_job(
    organization_id: UUID,
    payload: BulkJobCreate,
    request: Request,
    context: Annotated[TenantContext, require(Permission.ORDER_PLACE)],
) -> BulkJobProgressView:
    """Choose recipients and validate them. Holds no money and buys nothing."""
    del organization_id
    service = _service(request)
    with request.app.state.session_factory() as session:
        product = session.get(Product, payload.product_id)
        if product is None:
            raise BulkError("product_not_found")
        # Price and seller come from the published market, through the same
        # catalog call a consumer quote uses. A bulk order priced any other way
        # would eventually disagree with a quote for the same product.
        catalog = cast(CatalogService, request.app.state.catalog_service)
        market, unit_amount = catalog.sale_terms(
            session,
            product,
            country=payload.country.upper(),
            currency=payload.currency.upper(),
        )
        job = service.plan(
            session,
            context.organization_id,
            idempotency_key=payload.idempotency_key,
            product=product,
            sales_market_id=market.id,
            person_ids=payload.person_ids,
            currency=payload.currency.upper(),
            unit_amount=unit_amount,
            created_by_user_id=context.actor_user_id,
        )
        view = _progress_view(service.progress(session, job))
        session.commit()
        return view


@router.get("/{organization_id}/bulk-jobs", response_model=BulkJobListResponse)
def list_jobs(
    organization_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.ORDER_READ)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> BulkJobListResponse:
    del organization_id
    with request.app.state.session_factory() as session:
        jobs = session.exec(
            select(BulkJob)
            .where(BulkJob.organization_id == context.organization_id)
            .order_by(col(BulkJob.created_at).desc())
            .limit(limit)
        ).all()
        return BulkJobListResponse(jobs=[_job_view(job) for job in jobs])


@router.get(
    "/{organization_id}/bulk-jobs/{job_id}", response_model=BulkJobProgressView
)
def get_job(
    organization_id: UUID,
    job_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.ORDER_READ)],
) -> BulkJobProgressView:
    """Counts as they are. Forty-seven of fifty is not "in progress"."""
    del organization_id
    service = _service(request)
    with request.app.state.session_factory() as session:
        job = service.job(session, context.organization_id, job_id)
        return _progress_view(service.progress(session, job))


@router.get(
    "/{organization_id}/bulk-jobs/{job_id}/items",
    response_model=BulkItemListResponse,
)
def list_items(
    organization_id: UUID,
    job_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.ORDER_READ)],
) -> BulkItemListResponse:
    del organization_id
    service = _service(request)
    with request.app.state.session_factory() as session:
        job = service.job(session, context.organization_id, job_id)
        return BulkItemListResponse(
            items=[_item_view(item) for item in service.items(session, job)]
        )


@router.post(
    "/{organization_id}/bulk-jobs/{job_id}/fund",
    response_model=BulkJobProgressView,
)
def fund_job(
    organization_id: UUID,
    job_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.ORDER_PLACE)],
) -> BulkJobProgressView:
    """One hold per line. Under-funding serves who it can and says so."""
    del organization_id
    service = _service(request)
    with request.app.state.session_factory() as session:
        job = service.job(session, context.organization_id, job_id)
        view = _progress_view(service.fund(session, job))
        session.commit()
        return view


@router.post(
    "/{organization_id}/bulk-jobs/{job_id}/provision",
    response_model=BulkJobProgressView,
)
def provision_job(
    organization_id: UUID,
    job_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.ORDER_PLACE)],
) -> BulkJobProgressView:
    """Idempotent: a lost response retried is a question, not a second purchase."""
    del organization_id
    service = _service(request)
    with request.app.state.session_factory() as session:
        job = service.job(session, context.organization_id, job_id)
        view = _progress_view(
            service.provision(
                session,
                job,
                seller_legal_entity_id=_seller_for(session, job),
            )
        )
        session.commit()
        return view


@router.post(
    "/{organization_id}/bulk-jobs/{job_id}/resume",
    response_model=BulkJobProgressView,
)
def resume_job(
    organization_id: UUID,
    job_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.ORDER_PLACE)],
) -> BulkJobProgressView:
    """Retry what failed. Items with an unknown outcome are **not** retried.

    Reconciliation talks to a supplier, and no supplier is wired here — so an
    unknown item stays unknown, keeps its hold, and is visible in the item list
    for a human. That is the honest behaviour, not a gap to be papered over
    with a blind retry.
    """
    del organization_id
    service = _service(request)
    with request.app.state.session_factory() as session:
        job = service.job(session, context.organization_id, job_id)
        view = _progress_view(
            service.resume(
                session,
                job,
                seller_legal_entity_id=_seller_for(session, job),
            )
        )
        session.commit()
        return view


@router.post(
    "/{organization_id}/bulk-jobs/{job_id}/items/{item_id}/cancel",
    response_model=BulkItemView,
)
def cancel_item(
    organization_id: UUID,
    job_id: UUID,
    item_id: UUID,
    payload: CancelRequest,
    request: Request,
    context: Annotated[TenantContext, require(Permission.ORDER_PLACE)],
) -> BulkItemView:
    """Withdraw one line. A provisioned one is refunded under policy instead."""
    del organization_id
    service = _service(request)
    with request.app.state.session_factory() as session:
        job = service.job(session, context.organization_id, job_id)
        item = session.get(BulkJobItem, item_id)
        if item is None or item.job_id != job.id:
            raise BulkError("item_not_found")
        cancelled = service.cancel_item(session, job, item, reason=payload.reason)
        view = _item_view(cancelled)
        session.commit()
        return view


@router.post(
    "/{organization_id}/bulk-jobs/{job_id}/items/{item_id}/activation-request",
    response_model=ActivationRequestIssued,
    status_code=201,
)
def issue_activation_request(
    organization_id: UUID,
    job_id: UUID,
    item_id: UUID,
    request: Request,
    context: Annotated[TenantContext, require(Permission.ORDER_PLACE)],
) -> ActivationRequestIssued:
    """Invite one recipient to claim their line.

    The response carries the token **once**. It is stored as a hash, so this
    endpoint is the only moment it exists in a form anybody can use — including
    us.
    """
    del organization_id
    service = _service(request)
    with request.app.state.session_factory() as session:
        job = service.job(session, context.organization_id, job_id)
        item = session.get(BulkJobItem, item_id)
        if item is None or item.job_id != job.id:
            raise BulkError("item_not_found")
        record, token = service.issue_activation_request(session, job, item)
        issued = ActivationRequestIssued(request=_request_view(record), token=token)
        session.commit()
        return issued


@recipient_router.post(
    "/activation-requests/redeem", response_model=ActivationRequestView
)
def redeem_activation_request(
    payload: BulkActivationRedeemRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> ActivationRequestView:
    """Claim a work line, once.

    Deliberately **not** behind an organization permission. The person claiming
    a line is an employee with a phone, not an administrator of the tenant that
    bought it, and requiring membership here would be exactly backwards.
    """
    service = _service(request)
    with request.app.state.session_factory() as session:
        record = service.redeem_activation_request(session, payload.token, user)
        view = _request_view(record)
        session.commit()
        return view


__all__ = ["recipient_router", "router"]
