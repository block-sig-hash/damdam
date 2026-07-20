from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now


class AuditEventType(str, Enum):
    """Not a DB enum (see AuditLog.event_type) so new event sources can be
    added without a migration -- this class exists purely for type safety
    in application code."""

    PAYMENT_WEBHOOK = "payment_webhook"
    ACTIVATION_REDEMPTION = "activation_redemption"
    PACKAGE_PROVISIONING = "package_provisioning"
    ADMIN_ACTION = "admin_action"
    DATA_RETENTION = "data_retention"


class AuditOutcome(str, Enum):
    """See AuditEventType -- same reasoning, plain string column."""

    DUPLICATE_WEBHOOK_ABSORBED = "duplicate_webhook_absorbed"
    DUPLICATE_ACTIVATION_ATTEMPTED = "duplicate_activation_attempted"
    PACKAGE_CHAINED_ONTO_ACTIVE_WINDOW = "package_chained_onto_active_window"
    PACKAGE_CANCELLED_BY_ADMIN = "package_cancelled_by_admin"
    CHECKIN_LOCATION_NULLED = "checkin_location_nulled"
    SOS_ALERT_DELETED = "sos_alert_deleted"
    USAGE_POLL_COLLAPSED = "usage_poll_collapsed"
    CALL_LOG_DELETED = "call_log_deleted"
    ACCOUNT_SOFT_DELETED = "account_soft_deleted"
    ACCOUNT_HARD_DELETED = "account_hard_deleted"
    ACCOUNT_CHECKIN_LOCATION_ERASED = "account_checkin_location_erased"
    DEVICE_USER_LINK_STRIPPED = "device_user_link_stripped"
    DEVICE_LOG_DELETED = "device_log_deleted"
    TRANSACTION_DELETED = "transaction_deleted"


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    # Plain VARCHAR, not a Postgres-native enum type, for both columns: this
    # table is meant to absorb new event sources/outcomes over time (AC-25.4
    # was the first use, not the last) without a migration each time. Type
    # safety is enforced in application code via AuditEventType/AuditOutcome.
    event_type: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    # Nullable + ON DELETE SET NULL rather than CASCADE: the audit trail
    # should survive even if the user account is later removed.
    user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    # A payment processor_reference, an activation code, or a package id --
    # whichever is relevant to this event. Deliberately untyped/unvalidated:
    # this is a log, not a foreign key to any one of those tables.
    reference: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    outcome: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    details: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    idempotency_key: str | None = Field(
        default=None,
        sa_column=Column(String(255), nullable=True, unique=True, index=True),
    )
