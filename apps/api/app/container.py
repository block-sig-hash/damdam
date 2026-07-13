from collections.abc import Callable, Mapping
from datetime import datetime

from redis import Redis

from app.config import Settings
from app.db import SessionFactory, create_session_factory
from app.notifications.providers import MetaWhatsAppSender, ResendEmailSender
from app.notifications.service import EmailSender, NotificationService, WhatsAppSender
from app.otp.providers import OTPProvider, TermiiProvider, TwilioVerifyProvider
from app.otp.service import FailoverScheduler, OTPService, RedisClient, utc_now


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
