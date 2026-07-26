from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.auth.models import Manifest, ManifestPilgrim, Organization, User
from app.sos.models import (
    SOSAlert,
    SOSNotification,
    SOSNotificationChannel,
    SOSNotificationEvent,
    SOSStatus,
)
from app.sos.schemas import HtoSOSAlertResponse, SOSCreate


class SOSError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SOSScheduler(Protocol):
    def schedule_dispatch(
        self, notification_id: UUID, channel: SOSNotificationChannel
    ) -> None: ...

    def schedule_fallback(self, notification_id: UUID, countdown: int) -> None: ...


class NoopSOSScheduler:
    def schedule_dispatch(
        self, notification_id: UUID, channel: SOSNotificationChannel
    ) -> None:
        del notification_id, channel

    def schedule_fallback(self, notification_id: UUID, countdown: int) -> None:
        del notification_id, countdown


# SMS_FAMILY is created lazily by SOSNotificationService.send_sms_fallback
# only if the WHATSAPP_FAMILY leg fails or doesn't confirm delivery within
# the fallback window (AC-22.3/§6.27) — it must never be one of the four
# rows eagerly created here at trigger/cancel time.
EAGER_NOTIFICATION_CHANNELS = (
    SOSNotificationChannel.PUSH,
    SOSNotificationChannel.EMAIL,
    SOSNotificationChannel.WHATSAPP_OPERATOR,
    SOSNotificationChannel.WHATSAPP_FAMILY,
)


class SOSService:
    def __init__(self, scheduler: SOSScheduler, clock: Callable[[], datetime]) -> None:
        self.scheduler = scheduler
        self.clock = clock

    def _notifications(
        self, session: Session, alert: SOSAlert, event: SOSNotificationEvent
    ) -> list[SOSNotification]:
        rows = [
            SOSNotification(sos_alert_id=alert.id, channel=channel, event=event)
            for channel in EAGER_NOTIFICATION_CHANNELS
        ]
        session.add_all(rows)
        return rows

    def _schedule(self, rows: list[SOSNotification]) -> None:
        for row in rows:
            try:
                self.scheduler.schedule_dispatch(row.id, row.channel)
            except Exception:
                # The pending database row is the durable broker-outage recovery queue.
                continue

    def create(self, session: Session, user: User, payload: SOSCreate) -> SOSAlert:
        existing = session.exec(
            select(SOSAlert).where(
                SOSAlert.client_generated_id == payload.client_generated_id
            )
        ).first()
        if existing is not None:
            if existing.user_id != user.id:
                raise SOSError("sos_id_conflict")
            return existing
        alert = SOSAlert(
            user_id=user.id,
            client_generated_id=payload.client_generated_id,
            timestamp=payload.timestamp,
            latitude=Decimal(str(payload.latitude))
            if payload.latitude is not None
            else None,
            longitude=Decimal(str(payload.longitude))
            if payload.longitude is not None
            else None,
        )
        session.add(alert)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            winner = session.exec(
                select(SOSAlert).where(
                    SOSAlert.client_generated_id == payload.client_generated_id,
                    SOSAlert.user_id == user.id,
                )
            ).first()
            if winner is None:
                raise SOSError("sos_id_conflict") from None
            return winner
        rows = self._notifications(session, alert, SOSNotificationEvent.TRIGGERED)
        session.commit()
        session.refresh(alert)
        for row in rows:
            session.refresh(row)
        self._schedule(rows)
        return alert

    def cancel(self, session: Session, user: User, alert_id: UUID) -> SOSAlert:
        alert = session.exec(
            select(SOSAlert)
            .where(SOSAlert.id == alert_id, SOSAlert.user_id == user.id)
            .with_for_update()
        ).first()
        if alert is None:
            raise SOSError("sos_not_found")
        if alert.status == SOSStatus.RESOLVED:
            raise SOSError("sos_already_resolved")
        if alert.status == SOSStatus.CANCELLED:
            return alert
        alert.status = SOSStatus.CANCELLED
        alert.resolved_at = self.clock()
        rows = self._notifications(session, alert, SOSNotificationEvent.CANCELLED)
        session.add(alert)
        session.commit()
        for row in rows:
            session.refresh(row)
        self._schedule(rows)
        return alert

    def _organization_user_ids(self, session: Session, organization_id: UUID) -> Any:
        return (
            select(ManifestPilgrim.user_id)
            .join(Manifest, col(Manifest.id) == col(ManifestPilgrim.manifest_id))
            .where(Manifest.organization_id == organization_id)
        )

    def resolve(
        self, session: Session, organization: Organization, alert_id: UUID
    ) -> SOSAlert:
        alert = session.exec(
            select(SOSAlert)
            .where(
                SOSAlert.id == alert_id,
                col(SOSAlert.user_id).in_(
                    self._organization_user_ids(session, organization.id)
                ),
            )
            .with_for_update()
        ).first()
        if alert is None:
            raise SOSError("sos_not_found")
        if alert.status == SOSStatus.CANCELLED:
            raise SOSError("sos_already_cancelled")
        if alert.status != SOSStatus.RESOLVED:
            alert.status = SOSStatus.RESOLVED
            alert.resolved_at = self.clock()
            alert.resolved_by = organization.id
            session.add(alert)
            session.commit()
            session.refresh(alert)
        return alert

    def list_for_hto(
        self, session: Session, organization: Organization, status: SOSStatus | None
    ) -> list[HtoSOSAlertResponse]:
        statement = (
            select(SOSAlert, User)
            .join(User, col(User.id) == col(SOSAlert.user_id))
            .where(
                col(SOSAlert.user_id).in_(
                    self._organization_user_ids(session, organization.id)
                )
            )
        )
        if status is not None:
            statement = statement.where(SOSAlert.status == status)
        statement = statement.order_by(
            col(SOSAlert.status).asc(), col(SOSAlert.timestamp).desc()
        )
        return [
            HtoSOSAlertResponse(
                id=alert.id,
                pilgrim_name=f"{user.first_name} {user.last_name}".strip(),
                pilgrim_phone=user.phone_number,
                timestamp=alert.timestamp,
                latitude=float(alert.latitude) if alert.latitude is not None else None,
                longitude=float(alert.longitude)
                if alert.longitude is not None
                else None,
                status=alert.status,
            )
            for alert, user in session.exec(statement).all()
        ]
