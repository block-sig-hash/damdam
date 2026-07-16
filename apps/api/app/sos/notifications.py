from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlmodel import Session, col, select

from app.auth.models import Manifest, ManifestPilgrim, Organization, User
from app.notifications.service import NotificationError, NotificationService
from app.profile.models import FamilyContact
from app.sos.models import (
    SOSAlert,
    SOSNotification,
    SOSNotificationChannel,
    SOSNotificationEvent,
    SOSNotificationStatus,
)


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
    def send(self, context: SOSDeliveryContext) -> None: ...


class PushNotificationSender(Protocol):
    def send_topic(
        self, topic: str, title: str, body: str, data: dict[str, str]
    ) -> None: ...


class SOSProviderAdapter:
    """Vendor-neutral SOS channel adapter; routes are never provider-aware."""

    def __init__(
        self, notifications: NotificationService, push: PushNotificationSender
    ) -> None:
        self.notifications = notifications
        self.push = push

    def send(self, context: SOSDeliveryContext) -> None:
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
        elif context.channel == SOSNotificationChannel.EMAIL:
            self.notifications.email.send_sos(
                context.hto_email,
                context.pilgrim_name,
                context.pilgrim_phone,
                context.timestamp,
                context.maps_url,
                cancelled,
            )
        elif context.channel == SOSNotificationChannel.WHATSAPP_OPERATOR:
            self.notifications.whatsapp.send_sos(
                context.hto_phone,
                context.pilgrim_name,
                context.timestamp,
                context.maps_url,
                context.hto_phone,
                cancelled,
            )
        elif context.channel == SOSNotificationChannel.WHATSAPP_FAMILY:
            if not context.family_phone:
                raise NotificationError("family contact unavailable")
            self.notifications.whatsapp.send_sos(
                context.family_phone,
                context.pilgrim_name,
                context.timestamp,
                context.maps_url,
                context.hto_phone,
                cancelled,
            )


class SOSNotificationService:
    WAT = ZoneInfo("Africa/Lagos")

    def __init__(
        self, sender: SOSChannelSender, clock: Callable[[], datetime]
    ) -> None:
        self.sender = sender
        self.clock = clock

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
        context = self._context(session, row)
        row.retry_count += 1
        try:
            if context is None:
                raise NotificationError("SOS delivery context unavailable")
            self.sender.send(context)
            row.status = SOSNotificationStatus.SENT
            row.sent_at = self.clock()
            row.failure_reason = None
        except Exception as exc:
            row.status = SOSNotificationStatus.FAILED
            row.failure_reason = str(exc)[:255]
            if row.retry_count >= 3:
                row.admin_queued_at = self.clock()
            session.add(row)
            session.commit()
            return False
        session.add(row)
        session.commit()
        return True
