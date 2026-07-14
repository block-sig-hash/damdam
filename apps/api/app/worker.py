from typing import Any
from uuid import UUID

from celery import Celery
from redis import Redis

from app.auth.models import utc_now
from app.config import get_settings
from app.container import (
    CeleryFailoverScheduler,
    CeleryProvisioningScheduler,
    build_notification_service,
    build_otp_service,
)
from app.db import create_session_factory
from app.manifests.invoices import InvoicePDFGenerator, build_invoice_storage
from app.manifests.orders import ManifestOrderService

settings = get_settings()
celery_app = Celery("damdam", broker=settings.redis_url, backend=settings.redis_url)


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
