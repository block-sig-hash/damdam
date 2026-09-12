"""Recognisable sessions, support requests, notification preferences, exports — US-38.

Revision ID: 0038_account_and_support
Revises: 0037_spending_controls

**Purely additive.** Four new tables, no column added to an existing table, no
row touched and nothing dropped. `refresh_tokens` in particular is left exactly
as it is: authentication keeps checking the same table it checked yesterday, and
`account_sessions` describes those rows from beside them rather than replacing
them. A bug in the description can make a session unrecognisable; it cannot make
a revoked one work.

**Numbering collision, deliberately left for the merge.** `0038` is also taken
by `0038_call_authorization` on the unmerged `chunk/V02-outbound-call-control`
branch. Both chunks were cut from the same `0037` head at the founder's
direction to run them in parallel. Whichever merges second renumbers — the
alternative is guessing a number now and being wrong in a way that is harder to
see. Named in `docs/implementation/handoffs/21.md`.

The foreign keys encode who owns what after an account is erased, and they do
not all agree on purpose:

- `account_sessions` and `notification_preferences` **cascade**. A device list
  and a set of switches describe a live account; neither is a record of anything
  once that account is gone.
- `support_requests.user_id` is **SET NULL**. A closed conversation is still a
  record of a conversation the business had, and chunk 25's operations screens
  read it. The same reasoning chunk 04 applied to retaining call history.
- `support_requests.order_id` and `entitlement_id` are **SET NULL** so a ticket
  about an order outlives the order's visibility to the customer.

`ux_account_export_jobs_live` allows one unfinished export per account: a
customer pressing the button twice gets the job they already asked for rather
than a second copy of their own history to protect and expire.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038_account_and_support"
down_revision: str | None = "0037_spending_controls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_ENUMS = (
    ("account_session_platform", ("ios", "android", "web", "unknown")),
    (
        "support_category",
        ("installation", "connectivity", "billing", "refund", "account", "other"),
    ),
    ("support_state", ("open", "acknowledged", "resolved", "closed")),
    ("notification_category", ("low_balance", "expiry", "order_status")),
    ("notification_channel", ("push", "email", "sms")),
    (
        "account_export_state",
        ("requested", "building", "ready", "expired", "failed"),
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _NEW_ENUMS:
        postgresql.ENUM(*values, name=name, create_type=True).create(
            bind, checkfirst=True
        )

    op.create_table(
        "account_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "refresh_token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("refresh_tokens.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "platform",
            postgresql.ENUM(name="account_session_platform", create_type=False),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("device_label", sa.String(120), nullable=True),
        sa.Column("app_version", sa.String(40), nullable=True),
        sa.Column("last_seen_city", sa.String(120), nullable=True),
        sa.Column("last_seen_country", sa.String(2), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "refresh_token_id", name="uq_account_sessions_refresh_token"
        ),
    )
    op.create_index(
        "ix_account_sessions_user", "account_sessions", ["user_id", "revoked_at"]
    )

    op.create_table(
        "support_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("reference", sa.String(20), nullable=False),
        sa.Column(
            "category",
            postgresql.ENUM(name="support_category", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "state",
            postgresql.ENUM(name="support_state", create_type=False),
            nullable=False,
            server_default="open",
        ),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body", sa.String(4000), nullable=False),
        sa.Column("locale", sa.String(8), nullable=False),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "entitlement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entitlements.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subject_summary", sa.String(300), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("reference", name="uq_support_requests_reference"),
    )
    op.create_index(
        "ix_support_requests_user", "support_requests", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_support_requests_open",
        "support_requests",
        ["state", "created_at"],
        postgresql_where=sa.text("state IN ('open', 'acknowledged')"),
    )

    op.create_table(
        "notification_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "category",
            postgresql.ENUM(name="notification_category", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "channel",
            postgresql.ENUM(name="notification_channel", create_type=False),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "category", "channel", name="uq_notification_preferences"
        ),
    )

    op.create_table(
        "account_export_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "state",
            postgresql.ENUM(name="account_export_state", create_type=False),
            nullable=False,
            server_default="requested",
        ),
        sa.Column("storage_key", sa.String(400), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(300), nullable=True),
    )
    op.create_index(
        "ux_account_export_jobs_live",
        "account_export_jobs",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('requested', 'building')"),
    )


def downgrade() -> None:
    """Drops only what `upgrade` created.

    Dropping `support_requests` discards customer correspondence. That belongs
    in a development rollback and not in a production procedure: `AGENTS.md` is
    explicit that history is not erased because a surface was removed, and a
    support conversation is history even when the screen that started it is gone.
    """
    op.drop_table("account_export_jobs")
    op.drop_table("notification_preferences")
    op.drop_table("support_requests")
    op.drop_table("account_sessions")
    bind = op.get_bind()
    for name, _ in _NEW_ENUMS:
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
