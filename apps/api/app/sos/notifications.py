import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import Session, col, select

from app.auth.models import Manifest, ManifestPilgrim, Organization, User
from app.notifications.service import (
    NotificationError,
    NotificationService,
    SMSNotificationSender,
)
from app.profile.models import FamilyContact
from app.sos.models import (
    SOSAlert,
    SOSNotification,
    SOSNotificationChannel,
    SOSNotificationEvent,
    SOSNotificationStatus,
    SOSStatus,
)
from app.sos.service import SOSError, SOSScheduler

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SOSDeliveryContext:
    notification_id: UUID
    channel: SOSNotificationChannel
    event: SOSNotificationEvent
    pilgrim_name: str
    pilgrim_phone: str
    hto_name: str
    hto_phone: str
    hto_email: str
    family_phone: str | None
    timestamp: str
    maps_url: str | None
    hto_topic: str


class SOSChannelSender(Protocol):
    def send(self, context: SOSDeliveryContext) -> str | None: ...


class PushNotificationSender(Protocol):
    def send_topic(
        self, topic: str, title: str, body: str, data: dict[str, str]
    ) -> None: ...


class PushSubscriptionManager(Protocol):
    def subscribe_topic(self, token: str, topic: str) -> None: ...


class PushSubscriptionService:
    """Lets a browser opt into an organization's SOS push topic. Kept
    separate from SOSNotificationService/SOSProviderAdapter: subscribing is
    a one-off client action, not part of the per-alert dispatch pipeline,
    and only FirebasePushSender needs both capabilities."""

    def __init__(self, manager: PushSubscriptionManager) -> None:
        self.manager = manager

    def subscribe(self, organization_id: UUID, token: str) -> None:
        try:
            self.manager.subscribe_topic(token, f"hto-{organization_id}")
        except NotificationError as exc:
            raise SOSError("push_subscription_failed") from exc


def pending_dispatchable_notifications_query() -> Any:
    """Rows eligible for the recovery-sweep retry: not yet sent, not admin-
    queued, under the retry cap, and — for the original TRIGGERED-event
    rows only — belonging to an alert that is still active. A CANCELLED-
    event row's alert is always CANCELLED by the time it's queued and never
    transitions again, so that half of the OR is exempt from the check.
    Kept separate from the Celery task itself so the filter is testable
    against any session without going through create_session_factory or a
    real broker."""
    return (
        select(SOSNotification)
        .join(SOSAlert, col(SOSAlert.id) == col(SOSNotification.sos_alert_id))
        .where(
            SOSNotification.status != SOSNotificationStatus.SENT,
            SOSNotification.retry_count < 3,
            col(SOSNotification.admin_queued_at).is_(None),
            (
                (SOSNotification.event != SOSNotificationEvent.TRIGGERED)
                | (SOSAlert.status == SOSStatus.ACTIVE)
            ),
        )
    )


def due_sos_fallback_notifications_query(now: datetime) -> Any:
    """AC-22.3: WHATSAPP_FAMILY rows whose 60s window has elapsed with no
    Meta delivery confirmation and no SMS_FAMILY sibling row yet — the
    anti-join is what stops this sweep from re-triggering send_sms_fallback
    forever once the fallback has already been created (that row's own
    retries, if any, belong to pending_dispatchable_notifications_query
    instead, same as every other channel). `now` is passed in rather than
    computed with SQL's own now() so this stays testable against a
    controlled clock, matching every other timing-sensitive query in this
    codebase. Kept separate from the Celery task for the same testability
    reason as the query above."""
    fallback_sibling = aliased(SOSNotification)
    return (
        select(SOSNotification)
        .where(
            SOSNotification.channel == SOSNotificationChannel.WHATSAPP_FAMILY,
            col(SOSNotification.fallback_due_at).is_not(None),
            col(SOSNotification.fallback_due_at) <= now,
            col(SOSNotification.whatsapp_delivered_at).is_(None),
            col(SOSNotification.admin_queued_at).is_(None),
            ~select(fallback_sibling.id)
            .where(
                fallback_sibling.sos_alert_id == SOSNotification.sos_alert_id,
                fallback_sibling.channel == SOSNotificationChannel.SMS_FAMILY,
                fallback_sibling.event == SOSNotification.event,
            )
            .exists(),
        )
    )


class SOSProviderAdapter:
    """Vendor-neutral SOS channel adapter; routes are never provider-aware."""

    def __init__(
        self,
        notifications: NotificationService,
        push: PushNotificationSender,
        sms: SMSNotificationSender | None = None,
    ) -> None:
        self.notifications = notifications
        self.push = push
        self.sms = sms

    def send(self, context: SOSDeliveryContext) -> str | None:
        cancelled = context.event == SOSNotificationEvent.CANCELLED
        if context.channel == SOSNotificationChannel.PUSH:
            title = "SOS cancelled" if cancelled else "URGENT: pilgrim SOS"
            self.push.send_topic(
                context.hto_topic,
                title,
                (
                    f"{context.pilgrim_name} "
                    f"{'cancelled the SOS' if cancelled else 'needs help now'}."
                ),
                {"sos_id": str(context.notification_id), "event": context.event.value},
            )
            return None
        if context.channel == SOSNotificationChannel.EMAIL:
            self.notifications.email.send_sos(
                context.hto_email,
                context.pilgrim_name,
                context.pilgrim_phone,
                context.timestamp,
                context.maps_url,
                cancelled,
                str(context.notification_id),
            )
            return None
        if context.channel == SOSNotificationChannel.WHATSAPP_OPERATOR:
            self.notifications.whatsapp.send_sos(
                context.hto_phone,
                context.pilgrim_name,
                context.timestamp,
                context.maps_url,
                context.hto_phone,
                cancelled,
            )
            return None
        if context.channel == SOSNotificationChannel.WHATSAPP_FAMILY:
            if not context.family_phone:
                raise NotificationError("family contact unavailable")
            return self.notifications.whatsapp.send_sos(
                context.family_phone,
                context.pilgrim_name,
                context.timestamp,
                context.maps_url,
                context.hto_phone,
                cancelled,
            )
        if context.channel == SOSNotificationChannel.SMS_FAMILY:
            if not context.family_phone:
                raise NotificationError("family contact unavailable")
            if self.sms is None:
                raise NotificationError("SMS fallback is not configured")
            prefix = "SOS cancelled" if cancelled else "URGENT"
            verb = (
                "cancelled their SOS"
                if cancelled
                else "triggered an SOS and needs help"
            )
            message = (
                f"{prefix}: {context.pilgrim_name} {verb} at {context.timestamp}. "
                f"Contact the operator: {context.hto_phone}."
            )
            if context.maps_url:
                message = f"{message} {context.maps_url}"
            self.sms.send(context.family_phone, message)
            return None
        return None


class SOSNotificationService:
    WAT = ZoneInfo("Africa/Lagos")

    def __init__(
        self,
        sender: SOSChannelSender,
        clock: Callable[[], datetime],
        scheduler: SOSScheduler,
        fallback_seconds: int = 60,
    ) -> None:
        self.sender = sender
        self.clock = clock
        self.scheduler = scheduler
        self.fallback_seconds = fallback_seconds

    def _context(
        self, session: Session, row: SOSNotification
    ) -> SOSDeliveryContext | None:
        alert = session.get(SOSAlert, row.sos_alert_id)
        user = session.get(User, alert.user_id) if alert else None
        if alert is None or user is None:
            return None
        organization = session.exec(
            select(Organization)
            .join(Manifest, col(Manifest.organization_id) == col(Organization.id))
            .join(ManifestPilgrim, col(ManifestPilgrim.manifest_id) == col(Manifest.id))
            .where(ManifestPilgrim.user_id == user.id)
        ).first()
        if organization is None:
            return None
        family = session.exec(
            select(FamilyContact).where(FamilyContact.user_id == user.id)
        ).first()
        timestamp = alert.timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        maps_url = None
        if alert.latitude is not None and alert.longitude is not None:
            maps_url = f"https://www.google.com/maps?q={float(alert.latitude):.6f},{float(alert.longitude):.6f}"
        return SOSDeliveryContext(
            notification_id=row.id,
            channel=row.channel,
            event=row.event,
            pilgrim_name=f"{user.first_name} {user.last_name}".strip(),
            pilgrim_phone=user.phone_number,
            hto_name=organization.name,
            hto_phone=organization.phone_number,
            hto_email=organization.email,
            family_phone=family.phone_number if family else None,
            timestamp=timestamp.astimezone(self.WAT).strftime("%d %b %Y, %H:%M WAT"),
            maps_url=maps_url,
            hto_topic=f"hto-{organization.id}",
        )

    def dispatch(self, session: Session, notification_id: UUID) -> bool:
        row = session.exec(
            select(SOSNotification)
            .where(SOSNotification.id == notification_id)
            .with_for_update()
        ).first()
        if (
            row is None
            or row.status == SOSNotificationStatus.SENT
            or row.admin_queued_at is not None
        ):
            return False
        # A CANCELLED-event row's alert is always CANCELLED by the time it
        # dispatches (cancel() sets that status before creating the row, and
        # the state machine never transitions out of CANCELLED again), so
        # only the original TRIGGERED-event rows need this check: an alert
        # resolved or cancelled after they were queued must not still notify.
        if row.event == SOSNotificationEvent.TRIGGERED:
            alert = session.get(SOSAlert, row.sos_alert_id)
            if alert is not None and alert.status != SOSStatus.ACTIVE:
                logger.info(
                    "Skipping SOS notification %s: alert %s is no longer "
                    "active (%s)",
                    row.id,
                    alert.id,
                    alert.status.value,
                )
                return False
        # AC-22.3: only the original family WhatsApp leg has an SMS
        # fallback. A CANCELLED-event row is excluded even though it's the
        # same channel -- a missed "never mind" WhatsApp isn't safety
        # critical the way a missed SOS trigger is.
        is_fallback_eligible = (
            row.channel == SOSNotificationChannel.WHATSAPP_FAMILY
            and row.event == SOSNotificationEvent.TRIGGERED
        )
        context = self._context(session, row)
        row.retry_count += 1
        try:
            if context is None:
                raise NotificationError("SOS delivery context unavailable")
            message_id = self.sender.send(context)
            row.status = SOSNotificationStatus.SENT
            row.sent_at = self.clock()
            row.failure_reason = None
            if is_fallback_eligible:
                row.whatsapp_message_id = message_id
                row.fallback_due_at = self.clock() + timedelta(
                    seconds=self.fallback_seconds
                )
        except Exception as exc:
            row.status = SOSNotificationStatus.FAILED
            row.failure_reason = str(exc)[:255]
            if row.retry_count >= 3:
                row.admin_queued_at = self.clock()
            if is_fallback_eligible:
                # A send failure (not just a missed delivery confirmation)
                # makes the SMS fallback immediately eligible rather than
                # waiting out the full 60s window.
                row.fallback_due_at = self.clock()
            session.add(row)
            session.commit()
            if is_fallback_eligible:
                self.scheduler.schedule_fallback(row.id, 0)
            return False
        session.add(row)
        session.commit()
        if is_fallback_eligible:
            self.scheduler.schedule_fallback(row.id, self.fallback_seconds)
        return True

    def confirm_whatsapp_delivery(self, session: Session, message_id: str) -> bool:
        row = session.exec(
            select(SOSNotification).where(
                SOSNotification.whatsapp_message_id == message_id
            )
        ).first()
        if row is None:
            return False
        if row.whatsapp_delivered_at is not None:
            return True
        row.whatsapp_delivered_at = self.clock()
        session.add(row)
        session.commit()
        return True

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

    def send_sms_fallback(self, session: Session, notification_id: UUID) -> bool:
        row = session.exec(
            select(SOSNotification)
            .where(SOSNotification.id == notification_id)
            .with_for_update()
        ).first()
        fallback_due_at = row.fallback_due_at if row else None
        if fallback_due_at is not None and fallback_due_at.tzinfo is None:
            fallback_due_at = fallback_due_at.replace(tzinfo=timezone.utc)
        if (
            row is None
            or row.channel != SOSNotificationChannel.WHATSAPP_FAMILY
            or row.whatsapp_delivered_at is not None
            or fallback_due_at is None
            or fallback_due_at > self.clock()
        ):
            return False
        sms_row = SOSNotification(
            sos_alert_id=row.sos_alert_id,
            channel=SOSNotificationChannel.SMS_FAMILY,
            event=row.event,
        )
        session.add(sms_row)
        try:
            session.flush()
        except IntegrityError:
            # Another dispatch already created the SMS_FAMILY row for this
            # alert -- the unique (sos_alert_id, channel, event) constraint
            # is the idempotency boundary, same pattern as SOSService.create.
            session.rollback()
            return False
        session.commit()
        session.refresh(sms_row)
        return self.dispatch(session, sms_row.id)
