from typing import Any
from uuid import UUID

from celery import Celery
from redis import Redis
from sqlmodel import col, select

from app.auth.models import User, utc_now
from app.checkins.models import CheckInNotification, WhatsAppDeliveryStatus
from app.checkins.service import CheckInNotificationService
from app.config import get_settings
from app.container import (
    CeleryCheckInScheduler,
    CeleryEsimIssuanceScheduler,
    CeleryFailoverScheduler,
    CeleryProvisioningScheduler,
    build_notification_service,
    build_otp_service,
    build_sms_sender,
)
from app.db import create_session_factory
from app.esim.models import EsimIssuanceJob
from app.esim.providers import build_esim_providers
from app.esim.service import EsimError, EsimProfileService
from app.manifests.invoices import InvoicePDFGenerator, build_invoice_storage
from app.manifests.orders import ManifestOrderService
from app.packages.models import Package

settings = get_settings()
celery_app = Celery("damdam", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.beat_schedule = {
    "enqueue-due-esim-issuance": {
        "task": "app.esim.enqueue_due",
        "schedule": 30.0,
    },
    "enqueue-due-checkin-fallbacks": {
        "task": "app.checkins.enqueue_due_fallbacks",
        "schedule": 30.0,
    },
    "enqueue-pending-checkin-notifications": {
        "task": "app.checkins.enqueue_pending",
        "schedule": 30.0,
    },
}


def _checkin_notifications() -> CheckInNotificationService:
    notifications = build_notification_service(settings)
    return CheckInNotificationService(
        notifications.whatsapp,
        build_sms_sender(settings),
        CeleryCheckInScheduler(),
        utc_now,
        settings.family_notify_fallback_seconds,
    )


@celery_app.task(name="app.checkins.dispatch")  # type: ignore[misc]
def dispatch_checkin_notification(notification_id: str) -> bool:
    with create_session_factory(settings)() as session:
        return _checkin_notifications().dispatch_whatsapp(
            session, UUID(notification_id)
        )


@celery_app.task(name="app.checkins.sms_fallback")  # type: ignore[misc]
def send_checkin_sms_fallback(notification_id: str) -> bool:
    with create_session_factory(settings)() as session:
        return _checkin_notifications().send_sms_fallback(
            session, UUID(notification_id)
        )


@celery_app.task(name="app.checkins.enqueue_due_fallbacks")  # type: ignore[misc]
def enqueue_due_checkin_fallbacks() -> int:
    now = utc_now()
    queued = 0
    with create_session_factory(settings)() as session:
        rows = session.exec(
            select(CheckInNotification)
            .where(
                col(CheckInNotification.fallback_due_at).is_not(None),
                col(CheckInNotification.fallback_due_at) <= now,
                col(CheckInNotification.sms_fallback_sent_at).is_(None),
                col(CheckInNotification.whatsapp_delivered_at).is_(None),
                col(CheckInNotification.admin_queued_at).is_(None),
            )
            .with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            celery_app.send_task("app.checkins.sms_fallback", args=[str(row.id)])
            queued += 1
    return queued


@celery_app.task(name="app.checkins.enqueue_pending")  # type: ignore[misc]
def enqueue_pending_checkin_notifications() -> int:
    queued = 0
    with create_session_factory(settings)() as session:
        rows = session.exec(
            select(CheckInNotification)
            .where(
                CheckInNotification.whatsapp_status
                == WhatsAppDeliveryStatus.PENDING
            )
            .with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            celery_app.send_task("app.checkins.dispatch", args=[str(row.id)])
            queued += 1
    return queued


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


@celery_app.task(
    name="app.esim.issue", acks_late=True, reject_on_worker_lost=True
)  # type: ignore[misc]
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
