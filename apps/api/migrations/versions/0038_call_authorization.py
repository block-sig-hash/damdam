"""Outbound call authorization, provider legs, operations and event inbox — US-45.

Revision ID: 0038_call_authorization
Revises: 0037_spending_controls

**Purely additive.** Five new tables, no column added to an existing table, no
row touched, nothing seeded and nothing dropped. `call_logs`,
`voice_credentials`, `verified_caller_identities` and `caller_id_consents` —
the historical voice tables chunk 04 deliberately retained — are not read, not
written and not altered here. Old call history survives this migration
unchanged because this migration does not know it exists.

Two existing enums are **reused, not redefined**: `voice_origin_kind` and
`voice_destination_kind` were created by `0030_catalog_and_quotes`, and a call
attempt records its origin and destination in exactly the vocabulary the tariff
that priced it uses. Creating parallel types would let a rate and the call it
priced disagree about what "mobile" means.

Six constraints carry this chunk's guarantees, and each one is a failure that a
code path alone has historically not prevented:

- `uq_call_attempts_idempotency` — one authorize key, one attempt, one
  reservation, however many times a flaky mobile connection resends it (N1).
  Scoped per user, because a global key space lets one customer's replay collide
  with another customer's key and return them somebody else's call.
- `uq_call_attempts_reservation` — one reservation backs one attempt. Two
  attempts sharing a hold means the second one is funded by money the first has
  already spoken for.
- `ck_call_attempts_payer_matches_scope` — an organization-billed call names its
  organization and a personal call does not. Without it a work call can be
  settled against a company that appears nowhere on the row.
- `ux_call_legs_live_destination` — **one live destination leg per attempt.**
  This is the database saying no to a duplicate PSTN call. A worker that lost an
  originate response and reconnects cannot create a second billable leg even if
  its own bookkeeping is confused (N11).
- `ux_call_operations_live` — one live command per attempt and kind. A second
  concurrent originate is not a retry; it is a second call.
- `uq_call_events_provider_event` — every signed provider event applied at most
  once, including a replay *inside* the signature's timestamp tolerance (N8).
  An Ed25519 signature proves who sent an event; only this proves we have not
  already acted on it.

`ux_calling_credentials_live_device` adds a seventh: one active credential per
device per user, so revoking one installation leaves the customer's other
devices working.

**No provider is enabled by this migration.** No credential is created, no
connection is configured and `Settings.calling_live_routes_enabled` defaults to
False. The schema exists so that the authorization path can be built and tested
against PostgreSQL's real guarantees while blockers B1–B5 remain open.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038_call_authorization"
down_revision: str | None = "0037_spending_controls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_E164 = "'^\\+[1-9][0-9]{6,14}$'"

_NEW_ENUMS = (
    ("call_payer_kind", ("user", "organization")),
    (
        "call_attempt_state",
        (
            "authorized",
            "accepted",
            "ringing",
            "answered",
            "completed",
            "failed",
            "unknown",
            "expired",
            "cancelled",
        ),
    ),
    ("call_leg_role", ("client", "destination")),
    (
        "call_leg_state",
        ("created", "parked", "ringing", "answered", "bridged", "ended", "unknown"),
    ),
    (
        "call_operation_kind",
        ("issue_client_session", "create_destination_leg", "bridge", "hangup"),
    ),
    (
        "call_operation_outcome",
        (
            "in_flight",
            "accepted",
            "rejected",
            "outcome_unknown",
            "held_for_review",
        ),
    ),
    (
        "call_event_disposition",
        ("applied", "duplicate", "unmatched", "quarantined", "superseded"),
    ),
    ("calling_credential_state", ("active", "revoked")),
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _NEW_ENUMS:
        postgresql.ENUM(*values, name=name, create_type=True).create(
            bind, checkfirst=True
        )

    op.create_table(
        "calling_client_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("device_id", sa.String(200), nullable=False),
        sa.Column("device_label", sa.String(200), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_credential_id", sa.String(200), nullable=False),
        sa.Column("provider_connection_id", sa.String(200), nullable=True),
        sa.Column("sip_identity", sa.String(200), nullable=True),
        sa.Column(
            "state",
            postgresql.ENUM(name="calling_credential_state", create_type=False),
            nullable=False,
            server_default="active",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(200), nullable=True),
        sa.Column(
            "sessions_issued", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("last_session_issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider",
            "provider_credential_id",
            name="uq_calling_credentials_provider_id",
        ),
        sa.CheckConstraint(
            "(state = 'revoked' AND revoked_at IS NOT NULL) OR state <> 'revoked'",
            name="ck_calling_credentials_revoked_at",
        ),
    )
    op.create_index(
        "ux_calling_credentials_live_device",
        "calling_client_credentials",
        ["user_id", "device_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )
    op.create_index(
        "ix_calling_credentials_user",
        "calling_client_credentials",
        ["user_id", "state"],
    )

    op.create_table(
        "call_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "payer_kind",
            postgresql.ENUM(name="call_payer_kind", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "seller_legal_entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("legal_entities.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "entitlement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entitlements.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
        sa.Column("e164_destination", sa.String(16), nullable=False),
        sa.Column("destination_country", sa.String(2), nullable=False),
        sa.Column(
            "destination_kind",
            postgresql.ENUM(name="voice_destination_kind", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "origin_kind",
            postgresql.ENUM(name="voice_origin_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("origin_country", sa.String(2), nullable=True),
        sa.Column("identity_e164", sa.String(16), nullable=False),
        sa.Column(
            "identity_number_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assigned_numbers.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "tariff_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tariffs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("tariff_version", sa.Integer(), nullable=False),
        sa.Column("rate_per_minute_amount", sa.Numeric(20, 10), nullable=False),
        sa.Column("rate_setup_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("rate_minimum_seconds", sa.Integer(), nullable=False),
        sa.Column("rate_increment_seconds", sa.Integer(), nullable=False),
        sa.Column("max_seconds", sa.Integer(), nullable=False),
        sa.Column("max_charge_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "reservation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ledger_reservations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "client_credential_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("calling_client_credentials.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "state",
            postgresql.ENUM(name="call_attempt_state", create_type=False),
            nullable=False,
            server_default="authorized",
        ),
        sa.Column("grant_consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "owner_user_id", "idempotency_key", name="uq_call_attempts_idempotency"
        ),
        sa.UniqueConstraint("reservation_id", name="uq_call_attempts_reservation"),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_call_attempts_currency_iso4217"
        ),
        sa.CheckConstraint(
            "max_seconds > 0 AND max_charge_amount > 0",
            name="ck_call_attempts_positive_bounds",
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name="ck_call_attempts_expiry_after_creation"
        ),
        sa.CheckConstraint(
            "(payer_kind = 'organization' AND organization_id IS NOT NULL) "
            "OR (payer_kind = 'user' AND organization_id IS NULL)",
            name="ck_call_attempts_payer_matches_scope",
        ),
        sa.CheckConstraint(
            "(state = 'authorized' AND grant_consumed_at IS NULL) "
            "OR state <> 'authorized'",
            name="ck_call_attempts_unconsumed_while_authorized",
        ),
        sa.CheckConstraint(
            f"e164_destination ~ {_E164}", name="ck_call_attempts_destination_e164"
        ),
        sa.CheckConstraint(
            f"identity_e164 ~ {_E164}", name="ck_call_attempts_identity_e164"
        ),
    )
    op.create_index(
        "ix_call_attempts_owner_created",
        "call_attempts",
        ["owner_user_id", "created_at"],
    )
    op.create_index(
        "ix_call_attempts_organization_created",
        "call_attempts",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_call_attempts_open", "call_attempts", ["state", "expires_at"]
    )

    op.create_table(
        "call_legs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("call_attempts.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "role",
            postgresql.ENUM(name="call_leg_role", create_type=False),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_call_control_id", sa.String(200), nullable=False),
        sa.Column("provider_call_leg_id", sa.String(200), nullable=True),
        sa.Column("provider_call_session_id", sa.String(200), nullable=True),
        sa.Column("provider_connection_id", sa.String(200), nullable=True),
        sa.Column("provider_credential_id", sa.String(200), nullable=True),
        sa.Column(
            "state",
            postgresql.ENUM(name="call_leg_state", create_type=False),
            nullable=False,
            server_default="created",
        ),
        sa.Column("time_limit_seconds", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hangup_cause", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider", "provider_call_control_id", name="uq_call_legs_control_id"
        ),
        sa.CheckConstraint(
            "time_limit_seconds IS NULL OR time_limit_seconds > 0",
            name="ck_call_legs_time_limit_positive",
        ),
        sa.CheckConstraint(
            "(state IN ('answered', 'bridged') AND answered_at IS NOT NULL) "
            "OR state NOT IN ('answered', 'bridged')",
            name="ck_call_legs_answered_at",
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR answered_at IS NULL OR ended_at >= answered_at",
            name="ck_call_legs_not_negative_duration",
        ),
    )
    op.create_index(
        "ux_call_legs_live_destination",
        "call_legs",
        ["attempt_id"],
        unique=True,
        postgresql_where=sa.text("role = 'destination' AND state <> 'ended'"),
    )
    op.create_index("ix_call_legs_attempt_role", "call_legs", ["attempt_id", "role"])
    op.create_index(
        "ix_call_legs_session", "call_legs", ["provider", "provider_call_session_id"]
    )

    op.create_table(
        "call_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("call_attempts.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "kind",
            postgresql.ENUM(name="call_operation_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("operation_key", sa.String(200), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "outcome",
            postgresql.ENUM(name="call_operation_outcome", create_type=False),
            nullable=False,
            server_default="in_flight",
        ),
        sa.Column("provider_reference", sa.String(200), nullable=True),
        sa.Column("detail", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "provider", "operation_key", name="uq_call_operations_key"
        ),
        sa.CheckConstraint("attempt_number >= 1", name="ck_call_operations_number"),
        sa.CheckConstraint(
            "(outcome = 'accepted' AND provider_reference IS NOT NULL) "
            "OR outcome <> 'accepted'",
            name="ck_call_operations_accepted_reference",
        ),
    )
    op.create_index(
        "ux_call_operations_live",
        "call_operations",
        ["attempt_id", "kind"],
        unique=True,
        postgresql_where=sa.text(
            "outcome IN ('in_flight', 'accepted', 'outcome_unknown', "
            "'held_for_review')"
        ),
    )
    op.create_index(
        "ix_call_operations_outcome", "call_operations", ["outcome", "created_at"]
    )

    op.create_table(
        "call_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_event_id", sa.String(200), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("call_attempts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "leg_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("call_legs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "disposition",
            postgresql.ENUM(name="call_event_disposition", create_type=False),
            nullable=False,
        ),
        sa.Column("disposition_reason", sa.String(500), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint(
            "provider", "provider_event_id", name="uq_call_events_provider_event"
        ),
    )
    op.create_index(
        "ix_call_events_attempt", "call_events", ["attempt_id", "occurred_at"]
    )
    op.create_index(
        "ix_call_events_disposition", "call_events", ["disposition", "received_at"]
    )
    op.create_index(
        "ix_call_events_replayable",
        "call_events",
        ["disposition", "received_at"],
        postgresql_where=sa.text("disposition = 'unmatched'"),
    )


def downgrade() -> None:
    """Drops only what `upgrade` created.

    Safe in a way most downgrades are not, because this migration added nothing
    to an existing table: there is no backfilled column to unwind and no
    historical row that would lose information. Dropping these tables loses the
    call attempts recorded since the upgrade, which is why it belongs in a
    development rollback and not in a production procedure — `AGENTS.md` is
    explicit that order and audit history is never erased because a surface was
    removed.
    """
    op.drop_table("call_events")
    op.drop_table("call_operations")
    op.drop_table("call_legs")
    op.drop_table("call_attempts")
    op.drop_table("calling_client_credentials")
    bind = op.get_bind()
    for name, _ in _NEW_ENUMS:
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
