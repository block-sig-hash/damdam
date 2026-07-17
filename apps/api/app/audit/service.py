from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlmodel import Session

from app.audit.models import AuditEventType, AuditLog, AuditOutcome


class AuditLogService:
    """AC-25.4: every write here is deliberately silent to the end user --
    this is an admin-review trail only, never surfaced to a pilgrim or HTO
    operator. Callers commit as part of their own existing transaction;
    this never commits on its own, so an audit write never has its own
    separate failure mode that could roll back or delay the real work it's
    describing."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self.clock = clock

    def record(
        self,
        session: Session,
        event_type: AuditEventType,
        outcome: AuditOutcome,
        user_id: UUID | None = None,
        reference: str | None = None,
        details: str | None = None,
    ) -> None:
        session.add(
            AuditLog(
                created_at=self.clock(),
                event_type=event_type.value,
                outcome=outcome.value,
                user_id=user_id,
                reference=reference,
                details=details,
            )
        )
