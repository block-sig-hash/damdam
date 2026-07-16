from collections.abc import Callable, Mapping
from datetime import datetime
from uuid import UUID

from redis import Redis

from app.checkins.service import CheckInScheduler
from app.config import Settings
from app.db import SessionFactory, create_session_factory
from app.esim.service import EsimIssuanceScheduler
from app.manifests.orders import ProvisioningScheduler
from app.notifications.providers import (
    MetaWhatsAppSender,
    ResendEmailSender,
    TermiiSmsSender,
)
from app.notifications.service import (
    EmailSender,
    NotificationService,
    SMSNotificationSender,
    WhatsAppSender,
)
from app.otp.providers import OTPProvider, TermiiProvider, TwilioVerifyProvider
from app.otp.service import FailoverScheduler, OTPService, RedisClient, utc_now
from app.payments.providers import (
    FlutterwaveProvider,
    PaymentProvider,
    PaystackProvider,
)
from app.sos.models import SOSNotificationChannel
from app.sos.service import SOSScheduler


class CeleryFailoverScheduler:
    def schedule_failover(
        self, phone_number: str, challenge_id: str, countdown: int
    ) -> None:
        from app.worker import celery_app

        celery_app.send_task(
            "app.otp.failover",
            args=[phone_number, challenge_id],
            countdown=countdown,
        )


class CeleryProvisioningScheduler(ProvisioningScheduler):
    def schedule(self, order_id: UUID) -> None:
        from app.worker import celery_app

        celery_app.send_task("app.manifests.provision", args=[str(order_id)])


class CeleryEsimIssuanceScheduler(EsimIssuanceScheduler):
    def schedule(self, package_id: UUID, countdown: int) -> None:
        from app.worker import celery_app

        celery_app.send_task(
            "app.esim.issue", args=[str(package_id)], countdown=countdown
        )


class CeleryCheckInScheduler(CheckInScheduler):
    def schedule_dispatch(self, notification_id: UUID) -> None:
        from app.worker import celery_app

        celery_app.send_task("app.checkins.dispatch", args=[str(notification_id)])

    def schedule_fallback(self, notification_id: UUID, countdown: int) -> None:
        from app.worker import celery_app

        celery_app.send_task(
            "app.checkins.sms_fallback",
            args=[str(notification_id)],
            countdown=countdown,
        )


class CelerySOSScheduler(SOSScheduler):
    def schedule_dispatch(
        self, notification_id: UUID, channel: SOSNotificationChannel
    ) -> None:
        from app.worker import celery_app

        celery_app.send_task(
            "app.sos.dispatch", args=[str(notification_id), channel.value]
        )

    def schedule_fallback(self, notification_id: UUID, countdown: int) -> None:
        from app.worker import celery_app

        celery_app.send_task(
            "app.sos.sms_fallback",
            args=[str(notification_id)],
            countdown=countdown,
        )


def build_otp_service(
    settings: Settings,
    redis_client: RedisClient,
    scheduler: FailoverScheduler,
    providers: Mapping[str, OTPProvider] | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> OTPService:
    resolved_providers = providers or {
        "termii": TermiiProvider(settings),
        "twilio": TwilioVerifyProvider(settings),
    }
    return OTPService(settings, redis_client, resolved_providers, scheduler, clock)


def default_dependencies(
    settings: Settings,
) -> tuple[Redis, SessionFactory, FailoverScheduler, dict[str, OTPProvider]]:
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    providers: dict[str, OTPProvider] = {
        "termii": TermiiProvider(settings),
        "twilio": TwilioVerifyProvider(settings),
    }
    return (
        redis_client,
        create_session_factory(settings),
        CeleryFailoverScheduler(),
        providers,
    )


def build_notification_service(
    settings: Settings,
    email_sender: EmailSender | None = None,
    whatsapp_sender: WhatsAppSender | None = None,
) -> NotificationService:
    return NotificationService(
        email_sender or ResendEmailSender(settings),
        whatsapp_sender or MetaWhatsAppSender(settings),
    )


def build_sms_sender(
    settings: Settings, sms_sender: SMSNotificationSender | None = None
) -> SMSNotificationSender:
    return sms_sender or TermiiSmsSender(settings)


def build_payment_providers(settings: Settings) -> dict[str, PaymentProvider]:
    return {
        "paystack": PaystackProvider(settings),
        "flutterwave": FlutterwaveProvider(settings),
    }
