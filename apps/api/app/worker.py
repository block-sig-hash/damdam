import logging
from datetime import timedelta
from typing import Any
from uuid import UUID

from celery import Celery
from celery.schedules import crontab
from redis import Redis
from sqlmodel import Session, col, select

from app.auth.models import User, utc_now
from app.calling.charging import CallChargingService, EnforcementDecision
from app.calling.contract import LegState
from app.calling.lifecycle import CallLifecycleService
from app.calling.models import (
    TERMINAL_ATTEMPT_STATES,
    AttemptState,
    CallAttempt,
    CallDeadline,
    CallLeg,
    CallSupplierCost,
    ChargeBasis,
    DeadlineKind,
)
from app.calling.service import CallAuthorizationService
from app.calling.telnyx import DisabledCallingAdapter, TelnyxCallingAdapter
from app.config import get_settings
from app.connectivity.service import ConnectivityService
from app.container import (
    CeleryEsimIssuanceScheduler,
    CeleryFailoverScheduler,
    CeleryProvisioningScheduler,
    build_notification_service,
    build_otp_service,
)
from app.controls.service import ControlService
from app.db import create_session_factory
from app.esim.models import EsimIssuanceJob
from app.esim.providers import build_esim_providers
from app.esim.service import EsimError, EsimProfileService
from app.fulfilment.service import FulfilmentService
from app.ledger.service import LedgerService
from app.manifests.invoices import InvoicePDFGenerator, build_invoice_storage
from app.manifests.orders import ManifestOrderService
from app.packages.models import Package
from app.refunds.models import ExceptionKind
from app.retention.service import RetentionService
from app.usage.service import UsageService

settings = get_settings()
celery_app = Celery("damdam", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.beat_schedule = {
    "enqueue-due-esim-issuance": {
        "task": "app.esim.enqueue_due",
        "schedule": 30.0,
    },
    "retention-null-checkin-locations": {
        "task": "app.retention.null_checkin_locations",
        "schedule": crontab(hour=2, minute=0),
    },
    "retention-delete-sos-alerts": {
        "task": "app.retention.delete_sos_alerts",
        "schedule": crontab(hour=2, minute=10),
    },
    "retention-collapse-usage-polls": {
        "task": "app.retention.collapse_usage_polls",
        "schedule": crontab(hour=2, minute=20),
    },
    "retention-delete-call-logs": {
        "task": "app.retention.delete_call_logs",
        "schedule": crontab(hour=2, minute=30),
    },
    "retention-hard-delete-accounts": {
        "task": "app.retention.hard_delete_accounts",
        "schedule": crontab(hour=2, minute=40),
    },
    "retention-strip-device-user-links": {
        "task": "app.retention.strip_device_user_links",
        "schedule": crontab(hour=2, minute=50),
    },
    "retention-delete-device-logs": {
        "task": "app.retention.delete_device_logs",
        "schedule": crontab(hour=3, minute=0),
    },
    "retention-delete-transactions": {
        "task": "app.retention.delete_transactions",
        "schedule": crontab(hour=3, minute=10),
    },
    # V03. A minute is not a guess: a renewal check that fires slower than the
    # shortest hold could expire is a check that arrives after the money is
    # already spoken for.
    "calling-resolve-due-deadlines": {
        "task": "app.calling.resolve_due_deadlines",
        "schedule": 60.0,
    },
}


def _retention() -> RetentionService:
    return RetentionService(utc_now)


@celery_app.task(name="app.retention.null_checkin_locations")  # type: ignore[misc]
def null_expired_checkin_locations() -> int:
    with create_session_factory(settings)() as session:
        return _retention().null_expired_checkin_locations(session)


@celery_app.task(name="app.retention.delete_sos_alerts")  # type: ignore[misc]
def delete_expired_sos_alerts() -> int:
    with create_session_factory(settings)() as session:
        return _retention().delete_expired_sos_alerts(session)


@celery_app.task(name="app.retention.collapse_usage_polls")  # type: ignore[misc]
def collapse_expired_usage_polls() -> int:
    with create_session_factory(settings)() as session:
        return _retention().collapse_expired_usage_polls(session)


@celery_app.task(name="app.retention.delete_call_logs")  # type: ignore[misc]
def delete_expired_call_logs() -> int:
    with create_session_factory(settings)() as session:
        return _retention().delete_expired_call_logs(session)


@celery_app.task(name="app.retention.hard_delete_accounts")  # type: ignore[misc]
def hard_delete_expired_accounts() -> int:
    with create_session_factory(settings)() as session:
        return _retention().hard_delete_expired_accounts(session)


@celery_app.task(name="app.retention.strip_device_user_links")  # type: ignore[misc]
def strip_expired_device_user_links() -> int:
    with create_session_factory(settings)() as session:
        return _retention().strip_expired_device_user_links(session)


@celery_app.task(name="app.retention.delete_device_logs")  # type: ignore[misc]
def delete_expired_device_logs() -> int:
    with create_session_factory(settings)() as session:
        return _retention().delete_expired_device_logs(session)


@celery_app.task(name="app.retention.delete_transactions")  # type: ignore[misc]
def delete_expired_transactions() -> int:
    with create_session_factory(settings)() as session:
        return _retention().delete_expired_transactions(session)


# --- retired features (US-30, chunk 04B) -----------------------------------
#
# SOS and check-in dispatch is withdrawn. The task *names* stay registered on
# purpose: a beat process still running the previous schedule, or a message
# queued before this deploy, would otherwise hit an unregistered name and
# crash its worker in a retry loop. These refuse instead -- they dispatch
# nothing and never open a database session, so no notification can be
# reactivated by replaying old work.
#
# Retirement authority: docs/implementation/SCOPE-DISPOSITION.md.
# The rows in `sos_notifications` and `check_in_notifications` are untouched.

logger = logging.getLogger(__name__)


def _refuse(task_name: str) -> None:
    logger.warning("ignored message for retired task %s (US-30)", task_name)


@celery_app.task(name="app.sos.dispatch")  # type: ignore[misc]
def dispatch_sos_notification(notification_id: str, channel: str) -> bool:
    del notification_id, channel
    _refuse("app.sos.dispatch")
    return False


@celery_app.task(name="app.sos.sms_fallback")  # type: ignore[misc]
def send_sos_sms_fallback(notification_id: str) -> bool:
    del notification_id
    _refuse("app.sos.sms_fallback")
    return False


@celery_app.task(name="app.sos.enqueue_pending")  # type: ignore[misc]
def enqueue_pending_sos_notifications() -> int:
    _refuse("app.sos.enqueue_pending")
    return 0


@celery_app.task(name="app.sos.enqueue_due_fallbacks")  # type: ignore[misc]
def enqueue_due_sos_fallbacks() -> int:
    _refuse("app.sos.enqueue_due_fallbacks")
    return 0


@celery_app.task(name="app.checkins.dispatch")  # type: ignore[misc]
def dispatch_checkin_notification(notification_id: str) -> bool:
    del notification_id
    _refuse("app.checkins.dispatch")
    return False


@celery_app.task(name="app.checkins.sms_fallback")  # type: ignore[misc]
def send_checkin_sms_fallback(notification_id: str) -> bool:
    del notification_id
    _refuse("app.checkins.sms_fallback")
    return False


@celery_app.task(name="app.checkins.enqueue_due_fallbacks")  # type: ignore[misc]
def enqueue_due_checkin_fallbacks() -> int:
    _refuse("app.checkins.enqueue_due_fallbacks")
    return 0


@celery_app.task(name="app.checkins.enqueue_pending")  # type: ignore[misc]
def enqueue_pending_checkin_notifications() -> int:
    _refuse("app.checkins.enqueue_pending")
    return 0


@celery_app.task(name="app.otp.failover")  # type: ignore[misc]
def failover_otp(phone_number: str, challenge_id: str) -> bool:
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    service = build_otp_service(
        settings,
        redis_client,
        CeleryFailoverScheduler(),
    )
    return service.failover(phone_number, challenge_id)


@celery_app.task(
    name="app.manifests.provision",
    bind=True,
    max_retries=5,
)  # type: ignore[misc]
def provision_manifest_order(task: Any, order_id: str) -> str:
    service = ManifestOrderService(
        settings,
        build_notification_service(settings),
        build_invoice_storage(settings),
        CeleryProvisioningScheduler(),
        utc_now,
        InvoicePDFGenerator(),
    )
    try:
        with create_session_factory(settings)() as session:
            order = service.provision(session, UUID(order_id))
        return order.status.value
    except Exception as exc:
        retry = task.retry
        raise retry(exc=exc, countdown=60) from exc


@celery_app.task(name="app.esim.issue", acks_late=True, reject_on_worker_lost=True)  # type: ignore[misc]
def issue_esim(package_id: str) -> bool:
    service = EsimProfileService(
        settings,
        build_esim_providers(settings),
        CeleryEsimIssuanceScheduler(),
        build_notification_service(settings),
        utc_now,
    )
    with create_session_factory(settings)() as session:
        package = session.get(Package, UUID(package_id))
        if package is None:
            return False
        user = session.get(User, package.user_id)
        if user is None:
            return False
        try:
            service.issue(session, user, package.id)
        except EsimError as exc:
            if exc.code == "aggregator_unavailable":
                return False
            raise
    return True


@celery_app.task(name="app.esim.enqueue_due")  # type: ignore[misc]
def enqueue_due_esim_issuance() -> int:
    now = utc_now()
    queued = 0
    with create_session_factory(settings)() as session:
        jobs = session.exec(
            select(EsimIssuanceJob)
            .where(
                col(EsimIssuanceJob.next_attempt_at).is_not(None),
                col(EsimIssuanceJob.next_attempt_at) <= now,
                col(EsimIssuanceJob.admin_queued_at).is_(None),
            )
            .with_for_update(skip_locked=True)
        ).all()
        for job in jobs:
            celery_app.send_task("app.esim.issue", args=[str(job.package_id)])
            job.next_attempt_at = None
            session.add(job)
            queued += 1
        session.commit()
    return queued


# --- calling settlement (US-46, chunk V03) ---------------------------------


@celery_app.task(name="app.calling.resolve_due_deadlines")  # type: ignore[misc]
def resolve_due_deadlines() -> int:
    """Do the work a previous process wrote down before it stopped existing.

    Everything this task acts on is a row, not a timer. That is the whole point:
    the assignment requires durable deadlines to survive a worker restart, and a
    restart is exactly when an in-process timer stops existing while the call it
    was guarding keeps costing money.

    Each deadline is handled in its own transaction. One attempt that cannot be
    resolved must not roll back the ten that could — the queue would then never
    drain past its first bad row.
    """
    ledger = LedgerService(clock=utc_now)
    controls = ControlService(
        UsageService(ledger, clock=utc_now),
        ConnectivityService(FulfilmentService(clock=utc_now), clock=utc_now),
        ledger,
        clock=utc_now,
    )
    charging = CallChargingService(
        ledger,
        controls=controls,
        clock=utc_now,
        supplier_cost_wait_seconds=settings.calling_supplier_cost_wait_seconds,
    )
    adapter = (
        TelnyxCallingAdapter(settings, clock=utc_now)
        if settings.telnyx_api_key or settings.telnyx_public_key
        else DisabledCallingAdapter()
    )
    authorization = CallAuthorizationService(
        ledger,
        clock=utc_now,
        supported_countries=frozenset(
            country.upper()
            for country in settings.calling_supported_destination_countries
        ),
        grant_ttl_seconds=settings.calling_grant_ttl_seconds,
        max_call_seconds=settings.calling_max_call_seconds,
        route_enabled=settings.calling_live_routes_enabled,
    )
    lifecycle = CallLifecycleService(
        adapter, authorization, clock=utc_now, charging=charging
    )
    factory = create_session_factory(settings)
    handled = 0
    with factory() as session:
        due = charging.claim_due(session, now=utc_now(), limit=50)
        claimed = [deadline.id for deadline in due]
        session.commit()

    for deadline_id in claimed:
        with factory() as session:
            deadline = session.get(CallDeadline, deadline_id)
            if deadline is None:  # pragma: no cover - claimed a moment ago
                continue
            try:
                _resolve_deadline(session, charging, lifecycle, deadline)
                session.commit()
                handled += 1
            except Exception:  # noqa: BLE001 - the row must go back either way
                session.rollback()
                with factory() as recovery:
                    row = recovery.get(CallDeadline, deadline_id)
                    if row is not None:
                        charging.release_claim(
                            recovery, row, detail="worker failed mid-resolution"
                        )
                        recovery.commit()
                logging.exception("calling deadline %s failed", deadline_id)
    return handled


def _resolve_deadline(
    session: Session,
    charging: CallChargingService,
    lifecycle: CallLifecycleService,
    deadline: CallDeadline,
) -> None:
    """What each kind of deadline means when it comes due."""
    attempt = session.get(CallAttempt, deadline.attempt_id)
    if attempt is None:  # pragma: no cover - FK guarantees this
        charging.abandon(session, deadline, "the attempt no longer exists")
        return

    if deadline.kind is DeadlineKind.RESERVATION_RENEWAL:
        outcome = charging.renew(session, attempt)
        charging.complete(session, deadline, detail=outcome.reason)
        if outcome.decision is EnforcementDecision.CONTINUE:
            charging.schedule(
                session,
                attempt,
                DeadlineKind.RESERVATION_RENEWAL,
                charging.clock()
                + timedelta(seconds=charging.renewal_interval_seconds),
            )
            return
        attempt.stop_requested_at = attempt.stop_requested_at or charging.clock()
        attempt.end_reason = outcome.reason
        session.add(attempt)
        live_legs = session.exec(
            select(CallLeg).where(
                CallLeg.attempt_id == attempt.id,
                CallLeg.state != LegState.ENDED,
            )
        ).all()
        for leg in live_legs:
            lifecycle.hangup(session, attempt, leg)
        return

    if deadline.kind is DeadlineKind.SUPPLIER_COST_WAIT:
        # The supplier had its window. A provisional charge that nobody
        # corrected becomes final, because leaving it provisional forever means
        # the books never close and the customer's receipt never settles.
        charge = charging.finalize_provisional(session, attempt)
        if (
            charge is not None
            and charge.basis is not ChargeBasis.SUPPLIER_CDR
            and not session.exec(
                select(CallSupplierCost).where(
                    CallSupplierCost.attempt_id == attempt.id,
                    col(CallSupplierCost.billable_seconds).is_not(None),
                )
            ).first()
        ):
            charging.raise_exception(
                session,
                ExceptionKind.SETTLEMENT_MISMATCH,
                f"call-missing-cdr:{attempt.id}",
                "the supplier reconciliation window elapsed without a call "
                "detail record; the event-derived charge was finalized and "
                "the missing evidence remains queued",
            )
        charging.complete(session, deadline, detail="supplier window elapsed")
        return

    # MISSING_TERMINAL_EVENT and UNKNOWN_OUTCOME_REVIEW are the same move: ask
    # the legs again, because a late event may have arrived since. If they still
    # do not resolve, the hold stays and the exception stays open — a worker
    # deciding on its own that an unmeasured call was free is the failure this
    # queue exists to prevent.
    resolvable = (
        attempt.state is AttemptState.UNKNOWN
        or attempt.state in TERMINAL_ATTEMPT_STATES
    )
    if resolvable:
        result = charging.settle(session, attempt)
        if result.charge is not None:
            charging.complete(
                session, deadline, detail=f"resolved as {result.status.value}"
            )
            return
    charging.release_claim(
        session, deadline, detail="still unresolved; hold retained"
    )
