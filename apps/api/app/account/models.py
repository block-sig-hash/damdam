"""Sessions people can recognise, support requests, and deletion that is honest.

Chunk 21 (US-38). Four tables, and each one exists because the account screen
has to answer a question the current schema cannot.

**`account_sessions`** is the device list. `refresh_tokens` already tracks
validity, but a row with only a hash and an expiry cannot be rendered as "iPhone
13, Lagos, last used two hours ago" — and a revocation screen that lists four
identical rows is one nobody dares press. This table is deliberately *beside*
the token rather than replacing it: the token remains the thing authentication
checks, so a bug here can make a session unrecognisable but never make a revoked
one work.

**`support_requests`** carries the order or line it is about. A support queue
whose rows say "my eSIM is not working" with no reference costs one round trip
per ticket before anyone can start, and the customer has already told the app
which line they were looking at.

**`notification_preferences`** is per user per category, with the locale the
customer chose rather than the one their handset reports. `AGENTS.md` keeps
safety and location tracking retired, so the categories here are commercial and
operational only — low balance, expiry, order status — and there is no category
that can be used to reach somebody who has opted out of everything.

**`account_export_jobs`** makes an export a durable request rather than a large
response. An export that streams from a request handler ties a customer's data
to one HTTP connection surviving; this one is a row a worker fulfils, and a
customer who closed the app still gets it.

Nothing here deletes financial history. `AGENTS.md` is explicit — order and
audit history is never erased because a screen was removed — and the deletion
guard in `service.py` is what enforces it.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now


def _enum(
    enum_type: type[Enum], name: str, default: Enum | None = None
) -> Column[Any]:
    return Column(
        SAEnum(
            enum_type,
            name=name,
            values_callable=lambda choices: [choice.value for choice in choices],
        ),
        nullable=False,
        server_default=None if default is None else default.value,
    )


class SessionPlatform(str, Enum):
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"
    UNKNOWN = "unknown"


class SupportCategory(str, Enum):
    """What the customer says it is about, in their words, mapped to a queue.

    Deliberately short. A category list long enough to be precise is one people
    pick the first item from.
    """

    INSTALLATION = "installation"
    CONNECTIVITY = "connectivity"
    BILLING = "billing"
    REFUND = "refund"
    ACCOUNT = "account"
    OTHER = "other"


class SupportState(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    #: Closed without action, with a reason. Not the same as resolved, and the
    #: customer is told which one happened.
    CLOSED = "closed"


class NotificationCategory(str, Enum):
    """The three things we may tell somebody about, and nothing else.

    Safety alerts and location tracking are retired (`SCOPE-DISPOSITION.md`) and
    are not re-introduced as a preference — a preference row is a feature that
    exists, switched off.
    """

    LOW_BALANCE = "low_balance"
    EXPIRY = "expiry"
    ORDER_STATUS = "order_status"


class NotificationChannel(str, Enum):
    PUSH = "push"
    EMAIL = "email"
    SMS = "sms"


class ExportState(str, Enum):
    REQUESTED = "requested"
    BUILDING = "building"
    READY = "ready"
    #: The download window passed. The file is gone; the row stays so the
    #: customer can see that they asked and what happened.
    EXPIRED = "expired"
    FAILED = "failed"


class AccountSession(SQLModel, table=True):
    """One signed-in device, described well enough for its owner to recognise it."""

    __tablename__ = "account_sessions"
    __table_args__ = (
        UniqueConstraint(
            "refresh_token_id", name="uq_account_sessions_refresh_token"
        ),
        Index("ix_account_sessions_user", "user_id", "revoked_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    #: The token this session describes. `CASCADE` because a session with no
    #: token is not a session — unlike the financial rows below, there is
    #: nothing here worth keeping after the thing it describes is gone.
    refresh_token_id: UUID = Field(
        sa_column=Column(
            ForeignKey("refresh_tokens.id", ondelete="CASCADE"), nullable=False
        )
    )
    platform: SessionPlatform = Field(
        default=SessionPlatform.UNKNOWN,
        sa_column=_enum(
            SessionPlatform, "account_session_platform", SessionPlatform.UNKNOWN
        ),
    )
    #: What the customer sees: "iPhone 13", "Pixel 7". Supplied by the client and
    #: therefore never trusted for anything but display — it is truncated, and no
    #: decision is made from it.
    device_label: str | None = Field(
        default=None, sa_column=Column(String(120), nullable=True)
    )
    app_version: str | None = Field(
        default=None, sa_column=Column(String(40), nullable=True)
    )
    #: Coarse location for recognition, from the request's own network data.
    #: A city and country, never coordinates: this is "was this you?", not
    #: tracking, and location tracking stays retired.
    last_seen_city: str | None = Field(
        default=None, sa_column=Column(String(120), nullable=True)
    )
    last_seen_country: str | None = Field(
        default=None, sa_column=Column(String(2), nullable=True)
    )
    last_seen_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    revoked_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    revoked_reason: str | None = Field(
        default=None, sa_column=Column(String(120), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class SupportRequest(SQLModel, table=True):
    """A question about something specific, with the something attached."""

    __tablename__ = "support_requests"
    __table_args__ = (
        Index("ix_support_requests_user", "user_id", "created_at"),
        Index(
            "ix_support_requests_open",
            "state",
            "created_at",
            postgresql_where=text("state IN ('open', 'acknowledged')"),
            sqlite_where=text("state IN ('open', 'acknowledged')"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    #: `SET NULL` rather than cascade: a deleted account's support history is
    #: still the record of a conversation the business had, and chunk 25's
    #: operations screens read it.
    user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    reference: str = Field(
        sa_column=Column(String(20), unique=True, nullable=False, index=True)
    )
    category: SupportCategory = Field(
        sa_column=_enum(SupportCategory, "support_category")
    )
    state: SupportState = Field(
        default=SupportState.OPEN,
        sa_column=_enum(SupportState, "support_state", SupportState.OPEN),
    )
    subject: str = Field(sa_column=Column(String(200), nullable=False))
    body: str = Field(sa_column=Column(String(4000), nullable=False))
    locale: str = Field(sa_column=Column(String(8), nullable=False))
    #: What it is about. Both nullable, both `SET NULL`: a request about an order
    #: outlives the order's visibility to the customer.
    order_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
        ),
    )
    entitlement_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("entitlements.id", ondelete="SET NULL"), nullable=True
        ),
    )
    #: Frozen at submission so the queue shows what the customer was looking at,
    #: even after the order moves on. Display only.
    subject_summary: str | None = Field(
        default=None, sa_column=Column(String(300), nullable=True)
    )
    acknowledged_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    resolved_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class NotificationPreference(SQLModel, table=True):
    """One person's answer for one category. Absent means the default applies."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "category", "channel", name="uq_notification_preferences"
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    category: NotificationCategory = Field(
        sa_column=_enum(NotificationCategory, "notification_category")
    )
    channel: NotificationChannel = Field(
        sa_column=_enum(NotificationChannel, "notification_channel")
    )
    enabled: bool = Field(default=True, nullable=False)
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AccountExportJob(SQLModel, table=True):
    """A request for one's own data, fulfilled durably rather than in a response."""

    __tablename__ = "account_export_jobs"
    __table_args__ = (
        Index(
            "ux_account_export_jobs_live",
            "user_id",
            unique=True,
            postgresql_where=text("state IN ('requested', 'building')"),
            sqlite_where=text("state IN ('requested', 'building')"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    state: ExportState = Field(
        default=ExportState.REQUESTED,
        sa_column=_enum(ExportState, "account_export_state", ExportState.REQUESTED),
    )
    #: Where the built file lives. A storage key, never a public URL — the
    #: download is authorized per request, because a link that works without a
    #: session is a copy of somebody's account history that anyone can forward.
    storage_key: str | None = Field(
        default=None, sa_column=Column(String(400), nullable=True)
    )
    requested_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    failure_reason: str | None = Field(
        default=None, sa_column=Column(String(300), nullable=True)
    )
