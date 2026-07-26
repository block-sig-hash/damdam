from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.audit.models import AuditEventType, AuditLog, AuditOutcome
from app.auth.models import RefreshToken, User, UserStatus
from app.checkins.models import CheckIn
from app.esim.models import DailyUsageSummary, DeviceCompatibilityLog, UsagePoll
from app.packages.models import Transaction
from app.sos.models import SOSAlert
from app.voice.models import CallLog


def _calendar_years_before(value: datetime, years: int) -> datetime:
    """Subtract calendar years, mapping leap day to February 28."""
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)


class RetentionService:
    _SWEEP_LOCK_ID = 7_307_782_135_117

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self.clock = clock

    def request_account_deletion(self, session: Session, user_id: UUID) -> User:
        user = session.exec(
            select(User).where(User.id == user_id).with_for_update()
        ).one()
        if user.status == UserStatus.PENDING_DELETION:
            return user

        now = self.clock()
        user.status = UserStatus.PENDING_DELETION
        user.deletion_requested_at = now
        user.updated_at = now
        session.add(user)
        for token in session.exec(
            select(RefreshToken).where(
                RefreshToken.user_id == user.id,
                col(RefreshToken.revoked_at).is_(None),
            )
        ).all():
            token.revoked_at = now
            token.updated_at = now
            session.add(token)
        self._audit(
            session,
            AuditOutcome.ACCOUNT_SOFT_DELETED,
            user.id,
            user.id,
            details=f"hard_delete_at={(now + timedelta(days=30)).isoformat()}",
        )
        session.commit()
        session.refresh(user)
        return user

    def null_expired_checkin_locations(self, session: Session) -> int:
        if not self._acquire_sweep_lock(session):
            return 0
        now = self.clock()
        rows = session.exec(
            select(CheckIn)
            .where(
                (col(CheckIn.latitude).is_not(None))
                | (col(CheckIn.longitude).is_not(None)),
                CheckIn.location_retention_due_at <= now,
            )
            .with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            row.latitude = None
            row.longitude = None
            session.add(row)
            self._audit(
                session,
                AuditOutcome.CHECKIN_LOCATION_NULLED,
                row.id,
                row.user_id,
                details=f"location_retention_due_at={row.location_retention_due_at}",
            )
        session.commit()
        return len(rows)

    def delete_expired_sos_alerts(self, session: Session) -> int:
        if not self._acquire_sweep_lock(session):
            return 0
        cutoff = _calendar_years_before(self.clock(), 3)
        rows = session.exec(
            select(SOSAlert)
            .where(SOSAlert.timestamp <= cutoff)
            .with_for_update(skip_locked=True)
        ).all()
        return self._delete_rows(session, rows, AuditOutcome.SOS_ALERT_DELETED, cutoff)

    def collapse_expired_usage_polls(self, session: Session) -> int:
        if not self._acquire_sweep_lock(session):
            return 0
        cutoff = self.clock() - timedelta(days=30)
        rows = session.exec(
            select(UsagePoll)
            .where(UsagePoll.polled_at <= cutoff)
            .order_by(
                col(UsagePoll.esim_profile_id),
                col(UsagePoll.polled_at),
                col(UsagePoll.id),
            )
            .with_for_update(skip_locked=True)
        ).all()
        grouped: dict[tuple[UUID, object], list[UsagePoll]] = defaultdict(list)
        for row in rows:
            grouped[(row.esim_profile_id, row.polled_at.date())].append(row)

        for (profile_id, summary_date), polls in grouped.items():
            summary = session.exec(
                select(DailyUsageSummary)
                .where(
                    DailyUsageSummary.esim_profile_id == profile_id,
                    DailyUsageSummary.summary_date == summary_date,
                )
                .with_for_update()
            ).first()
            first = polls[0]
            last = polls[-1]
            successful = sum(poll.poll_success for poll in polls)
            failed = len(polls) - successful
            if summary is None:
                summary = DailyUsageSummary(
                    esim_profile_id=profile_id,
                    summary_date=first.polled_at.date(),
                    first_polled_at=first.polled_at,
                    last_polled_at=last.polled_at,
                    first_data_used_gb=first.data_used_gb,
                    last_data_used_gb=last.data_used_gb,
                    successful_poll_count=successful,
                    failed_poll_count=failed,
                )
            else:
                if first.polled_at < summary.first_polled_at:
                    summary.first_polled_at = first.polled_at
                    summary.first_data_used_gb = first.data_used_gb
                if last.polled_at > summary.last_polled_at:
                    summary.last_polled_at = last.polled_at
                    summary.last_data_used_gb = last.data_used_gb
                summary.successful_poll_count += successful
                summary.failed_poll_count += failed
            session.add(summary)
            for poll in polls:
                self._audit(
                    session,
                    AuditOutcome.USAGE_POLL_COLLAPSED,
                    poll.id,
                    details=(
                        f"profile_id={profile_id};summary_date={summary.summary_date}"
                    ),
                )
                session.delete(poll)
        session.commit()
        return len(rows)

    def delete_expired_call_logs(self, session: Session) -> int:
        if not self._acquire_sweep_lock(session):
            return 0
        cutoff = _calendar_years_before(self.clock(), 1)
        rows = session.exec(
            select(CallLog)
            .where(CallLog.started_at <= cutoff)
            .with_for_update(skip_locked=True)
        ).all()
        return self._delete_rows(session, rows, AuditOutcome.CALL_LOG_DELETED, cutoff)

    def hard_delete_expired_accounts(self, session: Session) -> int:
        if not self._acquire_sweep_lock(session):
            return 0
        cutoff = self.clock() - timedelta(days=30)
        users = session.exec(
            select(User)
            .where(
                User.status == UserStatus.PENDING_DELETION,
                col(User.deletion_requested_at).is_not(None),
                col(User.deletion_requested_at) <= cutoff,
            )
            .with_for_update(skip_locked=True)
        ).all()
        for user in users:
            # Account erasure may remove check-in location earlier than the
            # ordinary trip+90-day ceiling. The aggregate row itself survives
            # through its SET NULL user relationship.
            checkins = session.exec(
                select(CheckIn)
                .where(
                    CheckIn.user_id == user.id,
                    (col(CheckIn.latitude).is_not(None))
                    | (col(CheckIn.longitude).is_not(None)),
                )
                .with_for_update()
            ).all()
            for checkin in checkins:
                checkin.latitude = None
                checkin.longitude = None
                session.add(checkin)
                self._audit(
                    session,
                    AuditOutcome.ACCOUNT_CHECKIN_LOCATION_ERASED,
                    checkin.id,
                    user.id,
                    details="account_erasure",
                )
            self._audit(
                session,
                AuditOutcome.ACCOUNT_HARD_DELETED,
                user.id,
                details=f"deletion_requested_at={user.deletion_requested_at}",
            )
            session.delete(user)
        session.commit()
        return len(users)

    def strip_expired_device_user_links(self, session: Session) -> int:
        if not self._acquire_sweep_lock(session):
            return 0
        cutoff = self.clock() - timedelta(days=90)
        rows = session.exec(
            select(DeviceCompatibilityLog)
            .where(
                DeviceCompatibilityLog.checked_at <= cutoff,
                col(DeviceCompatibilityLog.user_id).is_not(None),
            )
            .with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            user_id = row.user_id
            row.user_id = None
            session.add(row)
            self._audit(
                session,
                AuditOutcome.DEVICE_USER_LINK_STRIPPED,
                row.id,
                user_id,
                details=f"checked_at_cutoff={cutoff.isoformat()}",
            )
        session.commit()
        return len(rows)

    def delete_expired_device_logs(self, session: Session) -> int:
        if not self._acquire_sweep_lock(session):
            return 0
        cutoff = _calendar_years_before(self.clock(), 2)
        rows = session.exec(
            select(DeviceCompatibilityLog)
            .where(DeviceCompatibilityLog.checked_at <= cutoff)
            .with_for_update(skip_locked=True)
        ).all()
        return self._delete_rows(session, rows, AuditOutcome.DEVICE_LOG_DELETED, cutoff)

    def delete_expired_transactions(self, session: Session) -> int:
        if not self._acquire_sweep_lock(session):
            return 0
        cutoff = _calendar_years_before(self.clock(), 6)
        rows = session.exec(
            select(Transaction)
            .where(Transaction.created_at <= cutoff)
            .with_for_update(skip_locked=True)
        ).all()
        return self._delete_rows(
            session, rows, AuditOutcome.TRANSACTION_DELETED, cutoff
        )

    def _delete_rows(
        self,
        session: Session,
        rows: Sequence[Any],
        outcome: AuditOutcome,
        cutoff: datetime,
    ) -> int:
        for row in rows:
            row_id = row.id
            user_id = getattr(row, "user_id", None)
            self._audit(
                session,
                outcome,
                row_id,
                user_id,
                details=f"retention_cutoff={cutoff.isoformat()}",
            )
            session.delete(row)
        session.commit()
        return len(rows)

    def _acquire_sweep_lock(self, session: Session) -> bool:
        """Serialize all retention sweeps to avoid cross-task cascade races."""
        if session.connection().dialect.name != "postgresql":
            return True
        return bool(
            session.exec(
                select(func.pg_try_advisory_xact_lock(self._SWEEP_LOCK_ID))
            ).one()
        )

    def _audit(
        self,
        session: Session,
        outcome: AuditOutcome,
        reference: UUID,
        user_id: UUID | None = None,
        details: str | None = None,
    ) -> None:
        session.add(
            AuditLog(
                created_at=self.clock(),
                event_type=AuditEventType.DATA_RETENTION.value,
                outcome=outcome.value,
                user_id=user_id,
                reference=str(reference),
                details=details,
                idempotency_key=f"retention:{outcome.value}:{reference}",
            )
        )
