import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.auth.models import User
from app.checkins.models import (
    CheckIn,
    CheckInNotification,
    SmsDeliveryStatus,
    WhatsAppDeliveryStatus,
)
from app.checkins.schemas import CheckInCreate
from app.notifications.service import (
    NotificationError,
    SMSNotificationSender,
    WhatsAppSender,
)
from app.otp.service import RedisClient
from app.packages.models import Package
from app.profile.models import FamilyContact

logger = logging.getLogger(__name__)


class CheckInError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CheckInScheduler(Protocol):
    def schedule_dispatch(self, notification_id: UUID) -> None: ...

    def schedule_fallback(self, notification_id: UUID, countdown: int) -> None: ...


class NoopCheckInScheduler:
    def schedule_dispatch(self, notification_id: UUID) -> None:
        del notification_id

    def schedule_fallback(self, notification_id: UUID, countdown: int) -> None:
        del notification_id, countdown


class CheckInService:
    RATE_LIMIT_SECONDS = 15 * 60

    def __init__(
        self,
        redis_client: RedisClient,
        scheduler: CheckInScheduler,
        clock: Callable[[], datetime],
    ) -> None:
        self.redis = redis_client
        self.scheduler = scheduler
        self.clock = clock

    def create(
        self, session: Session, user: User, payload: CheckInCreate
    ) -> CheckIn:
        existing = session.exec(
            select(CheckIn).where(
                CheckIn.client_generated_id == payload.client_generated_id
            )
        ).first()
        if existing is not None:
            if existing.user_id != user.id:
                raise CheckInError("checkin_id_conflict")
            return existing

        rate_key = f"checkin:rate:{user.id}"
        redis_unavailable = False
        try:
            acquired = self.redis.set(
                rate_key,
                str(payload.client_generated_id),
                nx=True,
                ex=self.RATE_LIMIT_SECONDS,
            )
            same_retry = self.redis.get(rate_key) == str(payload.client_generated_id)
        except Exception:
            # Check-in persistence is safety-critical. PostgreSQL's UUID
            # constraint still prevents duplicate writes, and the write
            # itself is never blocked here, while rate limiting fails open
            # during a Redis outage. That alone would let every distinct
            # check-in during the outage trigger its own WhatsApp/SMS send
            # with no ceiling, so `_recent_checkin_already_notified` below is
            # a Postgres-backed fallback ceiling that suppresses redundant
            # notifications (not the write) for the same 15-minute window
            # Redis would otherwise have enforced. See data-model.md §6.24.
            logger.exception("Check-in rate limiter unavailable; failing open")
            acquired = True
            same_retry = False
            redis_unavailable = True
        if not acquired and not same_retry:
            raise CheckInError("checkin_rate_limited")

        latest_trip_expiry = session.exec(
            select(func.max(Package.expires_at)).where(Package.user_id == user.id)
        ).one()
        event_time = payload.timestamp
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)
        if latest_trip_expiry is not None and latest_trip_expiry.tzinfo is None:
            latest_trip_expiry = latest_trip_expiry.replace(tzinfo=timezone.utc)
        trip_end = max(event_time, latest_trip_expiry or event_time)

        checkin = CheckIn(
            user_id=user.id,
            client_generated_id=payload.client_generated_id,
            timestamp=payload.timestamp,
            latitude=(
                Decimal(str(payload.latitude))
                if payload.latitude is not None
                else None
            ),
            longitude=(
                Decimal(str(payload.longitude))
                if payload.longitude is not None
                else None
            ),
            received_at=self.clock(),
            location_retention_due_at=trip_end + timedelta(days=90),
        )
        session.add(checkin)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            winner = session.exec(
                select(CheckIn).where(
                    CheckIn.client_generated_id == payload.client_generated_id,
                    CheckIn.user_id == user.id,
                )
            ).first()
            if winner is None:
                raise CheckInError("checkin_id_conflict") from None
            return winner

        contact = session.exec(
            select(FamilyContact).where(FamilyContact.user_id == user.id)
        ).first()
        suppressed = redis_unavailable and self._recent_checkin_already_notified(
            session, user.id, checkin.id
        )
        notification: CheckInNotification | None = None
        if contact is not None and not suppressed:
            notification = CheckInNotification(check_in_id=checkin.id)
            session.add(notification)
        session.commit()
        session.refresh(checkin)
        if notification is not None:
            session.refresh(notification)
            self._schedule_dispatch(notification.id)
        return checkin

    def _recent_checkin_already_notified(
        self, session: Session, user_id: UUID, exclude_checkin_id: UUID
    ) -> bool:
        """Redis-independent fallback ceiling used only during a Redis
        outage: if this user already has another check-in within the same
        15-minute window this instance would otherwise have enforced, skip
        triggering a second family notification. The check-in write itself
        is always persisted regardless of this check."""
        window_start = self.clock() - timedelta(seconds=self.RATE_LIMIT_SECONDS)
        return (
            session.exec(
                select(CheckIn.id)
                .where(
                    CheckIn.user_id == user_id,
                    CheckIn.id != exclude_checkin_id,
                    col(CheckIn.received_at) > window_start,
                )
                .limit(1)
            ).first()
            is not None
        )

    def _schedule_dispatch(self, notification_id: UUID) -> None:
        try:
            self.scheduler.schedule_dispatch(notification_id)
        except Exception:
            # The pending row is the durable queue; Celery Beat recovers it.
            return

    def history(self, session: Session, user: User, limit: int) -> list[CheckIn]:
        return list(
            session.exec(
                select(CheckIn)
                .where(CheckIn.user_id == user.id)
                .order_by(col(CheckIn.timestamp).desc())
                .limit(limit)
            ).all()
        )


class CheckInNotificationService:
    WAT = ZoneInfo("Africa/Lagos")

    def __init__(
        self,
        whatsapp: WhatsAppSender,
        sms: SMSNotificationSender,
        scheduler: CheckInScheduler,
        clock: Callable[[], datetime],
        fallback_seconds: int = 60,
        primary_channel: str = "whatsapp",
        secondary_channel: str = "sms",
    ) -> None:
        self.whatsapp = whatsapp
        self.sms = sms
        self.scheduler = scheduler
        self.clock = clock
        self.fallback_seconds = fallback_seconds
        self.primary_channel = primary_channel
        self.secondary_channel = secondary_channel

    def _context(
        self, session: Session, notification: CheckInNotification
    ) -> tuple[CheckIn, User, FamilyContact] | None:
        checkin = session.get(CheckIn, notification.check_in_id)
        if checkin is None:
            return None
        user = session.get(User, checkin.user_id)
        contact = session.exec(
            select(FamilyContact).where(FamilyContact.user_id == checkin.user_id)
        ).first()
        if user is None or contact is None:
            return None
        return checkin, user, contact

    @classmethod
    def _message_parts(
        cls, checkin: CheckIn, user: User
    ) -> tuple[str, str, str | None]:
        name = f"{user.first_name} {user.last_name}".strip() or "Your family member"
        timestamp = checkin.timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        checked_in_at = timestamp.astimezone(cls.WAT).strftime(
            "%d %b %Y, %H:%M WAT"
        )
        maps_url = None
        if checkin.latitude is not None and checkin.longitude is not None:
            maps_url = (
                "https://www.google.com/maps?q="
                f"{float(checkin.latitude):.6f},{float(checkin.longitude):.6f}"
            )
        return name, checked_in_at, maps_url

    def dispatch_whatsapp(self, session: Session, notification_id: UUID) -> bool:
        if self.primary_channel != "whatsapp":
            raise NotificationError(
                f"Unsupported primary family channel: {self.primary_channel}"
            )
        notification = session.exec(
            select(CheckInNotification)
            .where(CheckInNotification.id == notification_id)
            .with_for_update()
        ).first()
        if notification is None or notification.whatsapp_status in {
            WhatsAppDeliveryStatus.ACCEPTED,
            WhatsAppDeliveryStatus.DELIVERED,
        }:
            return False
        context = self._context(session, notification)
        if context is None:
            notification.whatsapp_status = WhatsAppDeliveryStatus.FAILED
            notification.whatsapp_failure_reason = "family contact unavailable"
            session.add(notification)
            session.commit()
            return False
        checkin, user, contact = context
        name, checked_in_at, maps_url = self._message_parts(checkin, user)
        notification.whatsapp_attempted_at = self.clock()
        try:
            message_id = self.whatsapp.send_checkin(
                contact.phone_number, name, checked_in_at, maps_url
            )
            notification.whatsapp_status = WhatsAppDeliveryStatus.ACCEPTED
            notification.whatsapp_message_id = message_id
            notification.fallback_due_at = self.clock() + timedelta(
                seconds=self.fallback_seconds
            )
            notification.whatsapp_failure_reason = None
            session.add(notification)
            session.commit()
            self.scheduler.schedule_fallback(notification.id, self.fallback_seconds)
            return True
        except NotificationError as exc:
            notification.whatsapp_status = WhatsAppDeliveryStatus.FAILED
            notification.whatsapp_failure_reason = str(exc)[:255]
            notification.fallback_due_at = self.clock()
            session.add(notification)
            session.commit()
            self.scheduler.schedule_fallback(notification.id, 0)
            return False

    def confirm_whatsapp_delivery(self, session: Session, message_id: str) -> bool:
        notification = session.exec(
            select(CheckInNotification).where(
                CheckInNotification.whatsapp_message_id == message_id
            )
        ).first()
        if notification is None:
            return False
        if notification.whatsapp_status == WhatsAppDeliveryStatus.DELIVERED:
            return True
        notification.whatsapp_status = WhatsAppDeliveryStatus.DELIVERED
        notification.whatsapp_delivered_at = self.clock()
        session.add(notification)
        session.commit()
        return True

    def send_sms_fallback(self, session: Session, notification_id: UUID) -> bool:
        if self.secondary_channel != "sms":
            raise NotificationError(
                f"Unsupported secondary family channel: {self.secondary_channel}"
            )
        notification = session.exec(
            select(CheckInNotification)
            .where(CheckInNotification.id == notification_id)
            .with_for_update()
        ).first()
        fallback_due_at = notification.fallback_due_at if notification else None
        if fallback_due_at is not None and fallback_due_at.tzinfo is None:
            fallback_due_at = fallback_due_at.replace(tzinfo=timezone.utc)
        if (
            notification is None
            or notification.whatsapp_status == WhatsAppDeliveryStatus.DELIVERED
            or notification.sms_status == SmsDeliveryStatus.SENT
            or notification.admin_queued_at is not None
            or fallback_due_at is None
            or fallback_due_at > self.clock()
        ):
            return False
        context = self._context(session, notification)
        if context is None:
            notification.sms_failure_reason = "family contact unavailable"
            notification.admin_queued_at = self.clock()
            session.add(notification)
            session.commit()
            return False
        checkin, user, contact = context
        name, checked_in_at, maps_url = self._message_parts(checkin, user)
        message = f"{name} checked in safely at {checked_in_at}. All is well."
        if maps_url:
            message = f"{message} {maps_url}"
        notification.sms_attempt_count += 1
        try:
            message_id = self.sms.send(contact.phone_number, message)
            notification.sms_status = SmsDeliveryStatus.SENT
            notification.sms_message_id = message_id
            notification.sms_fallback_sent_at = self.clock()
            notification.sms_failure_reason = None
            session.add(notification)
            session.commit()
            return True
        except NotificationError as exc:
            notification.sms_status = SmsDeliveryStatus.FAILED
            notification.sms_failure_reason = str(exc)[:255]
            if notification.sms_attempt_count >= 3:
                notification.admin_queued_at = self.clock()
            else:
                notification.fallback_due_at = self.clock() + timedelta(seconds=30)
            session.add(notification)
            session.commit()
            return False

    def process_meta_statuses(self, session: Session, payload: dict[str, Any]) -> int:
        processed = 0
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                for status in change.get("value", {}).get("statuses", []):
                    if status.get("status") == "delivered" and status.get("id"):
                        processed += int(
                            self.confirm_whatsapp_delivery(session, str(status["id"]))
                        )
        return processed
