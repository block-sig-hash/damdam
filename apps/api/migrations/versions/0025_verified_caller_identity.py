"""Verified Caller Identity -- US-14 CLI hardening (data-model.md §6.40).

Revision ID: 0025_verified_caller_identity
Revises: 0024_retention_payment_gaps
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025_verified_caller_identity"
down_revision: str | None = "0024_retention_payment_gaps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str):
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    phone_verification_provider = _enum("phone_verification_provider", "telnyx")
    phone_verification_status = _enum(
        "phone_verification_status", "not_started", "pending", "verified", "failed",
        "expired",
    )
    identity_provider = _enum("identity_provider", "mock")
    identity_verification_status = _enum(
        "identity_verification_status", "not_required", "pending", "approved",
        "rejected",
    )
    nin_msisdn_match_status = _enum(
        "nin_msisdn_match_status", "not_checked", "matched", "not_matched",
        "unavailable",
    )
    verified_caller_identity_status = _enum(
        "verified_caller_identity_status",
        "unverified",
        "phone_verification_pending",
        "phone_verified",
        "identity_verification_pending",
        "identity_verified",
        "consent_required",
        "active",
        "suspended",
        "expired",
        "revoked",
    )
    caller_identity_risk_status = _enum(
        "caller_identity_risk_status", "normal", "elevated", "blocked"
    )
    call_provider = _enum("call_provider", "telnyx", "idt")
    for enum in (
        phone_verification_provider,
        phone_verification_status,
        identity_provider,
        identity_verification_status,
        nin_msisdn_match_status,
        verified_caller_identity_status,
        caller_identity_risk_status,
        call_provider,
    ):
        enum.create(bind, checkfirst=True)

    op.create_table(
        "verified_caller_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phone_number", sa.String(14), nullable=False),
        sa.Column("detected_country", sa.String(2), nullable=False),
        sa.Column("detected_carrier", sa.String(32), nullable=True),
        sa.Column(
            "phone_verification_provider", phone_verification_provider, nullable=False
        ),
        sa.Column("phone_verification_reference", sa.String(64), nullable=True),
        sa.Column(
            "phone_verification_status",
            phone_verification_status,
            nullable=False,
            server_default="not_started",
        ),
        sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("identity_provider", identity_provider, nullable=True),
        sa.Column("identity_verification_reference", sa.String(64), nullable=True),
        sa.Column(
            "identity_verification_status",
            identity_verification_status,
            nullable=False,
            server_default="not_required",
        ),
        sa.Column(
            "nin_msisdn_match_status",
            nin_msisdn_match_status,
            nullable=False,
            server_default="not_checked",
        ),
        sa.Column(
            "status",
            verified_caller_identity_status,
            nullable=False,
            server_default="unverified",
        ),
        sa.Column("consent_version", sa.String(20), nullable=True),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reverified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "risk_status",
            caller_identity_risk_status,
            nullable=False,
            server_default="normal",
        ),
        sa.Column("suspension_reason", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_verified_caller_identities_user_id",
        "verified_caller_identities",
        ["user_id"],
    )
    op.create_index(
        "ix_verified_caller_identities_phone_number",
        "verified_caller_identities",
        ["phone_number"],
    )
    op.create_index(
        "ux_verified_caller_identities_active_user",
        "verified_caller_identities",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ux_verified_caller_identities_active_number",
        "verified_caller_identities",
        ["phone_number"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "caller_id_consents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "verified_caller_identity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("verified_caller_identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("consent_version", sa.String(20), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("device_session_id", sa.String(64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_caller_id_consents_verified_caller_identity_id",
        "caller_id_consents",
        ["verified_caller_identity_id"],
    )
    op.create_index(
        "ix_caller_id_consents_user_id", "caller_id_consents", ["user_id"]
    )

    op.add_column(
        "call_logs",
        sa.Column(
            "verified_caller_identity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("verified_caller_identities.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "call_logs", sa.Column("idempotency_key", sa.String(64), nullable=True)
    )
    op.add_column(
        "call_logs", sa.Column("requested_provider", call_provider, nullable=True)
    )
    op.add_column(
        "call_logs", sa.Column("failure_code", sa.String(64), nullable=True)
    )
    op.add_column(
        "call_logs", sa.Column("failure_description", sa.String(255), nullable=True)
    )
    op.create_index(
        "ix_call_logs_verified_caller_identity_id",
        "call_logs",
        ["verified_caller_identity_id"],
    )
    op.create_index(
        "ix_call_logs_idempotency_key", "call_logs", ["idempotency_key"]
    )

    # One-time migration (verified-cli-scoping.md §4.3): existing
    # verified_cli=true users proved possession of users.phone_number
    # through the now-retired login-OTP shortcut, but never gave a
    # separate, versioned CLI consent. They land at `phone_verified`, not
    # `active` -- one fresh consent capture is required before calls
    # resume, matching prd.md §5.5's CLI-verification amendment.
    op.execute(
        sa.text(
            """
            INSERT INTO verified_caller_identities (
                id, user_id, phone_number, detected_country,
                phone_verification_provider, phone_verification_status,
                phone_verified_at, identity_verification_status,
                nin_msisdn_match_status, status, risk_status,
                created_at, updated_at
            )
            SELECT
                md5('verified-caller-identity:' || users.id::text)::uuid,
                users.id,
                users.phone_number,
                'NG',
                'telnyx',
                'verified',
                users.created_at,
                'not_required',
                'not_checked',
                'phone_verified',
                'normal',
                now(),
                now()
            FROM users
            WHERE users.verified_cli = true
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_call_logs_idempotency_key", table_name="call_logs")
    op.drop_index(
        "ix_call_logs_verified_caller_identity_id", table_name="call_logs"
    )
    op.drop_column("call_logs", "failure_description")
    op.drop_column("call_logs", "failure_code")
    op.drop_column("call_logs", "requested_provider")
    op.drop_column("call_logs", "idempotency_key")
    op.drop_column("call_logs", "verified_caller_identity_id")

    op.drop_index(
        "ix_caller_id_consents_user_id", table_name="caller_id_consents"
    )
    op.drop_index(
        "ix_caller_id_consents_verified_caller_identity_id",
        table_name="caller_id_consents",
    )
    op.drop_table("caller_id_consents")

    op.drop_index(
        "ux_verified_caller_identities_active_number",
        table_name="verified_caller_identities",
    )
    op.drop_index(
        "ux_verified_caller_identities_active_user",
        table_name="verified_caller_identities",
    )
    op.drop_index(
        "ix_verified_caller_identities_phone_number",
        table_name="verified_caller_identities",
    )
    op.drop_index(
        "ix_verified_caller_identities_user_id",
        table_name="verified_caller_identities",
    )
    op.drop_table("verified_caller_identities")

    bind = op.get_bind()
    for name, values in reversed(
        (
            ("phone_verification_provider", ("telnyx",)),
            (
                "phone_verification_status",
                ("not_started", "pending", "verified", "failed", "expired"),
            ),
            ("identity_provider", ("mock",)),
            (
                "identity_verification_status",
                ("not_required", "pending", "approved", "rejected"),
            ),
            (
                "nin_msisdn_match_status",
                ("not_checked", "matched", "not_matched", "unavailable"),
            ),
            (
                "verified_caller_identity_status",
                (
                    "unverified",
                    "phone_verification_pending",
                    "phone_verified",
                    "identity_verification_pending",
                    "identity_verified",
                    "consent_required",
                    "active",
                    "suspended",
                    "expired",
                    "revoked",
                ),
            ),
            ("caller_identity_risk_status", ("normal", "elevated", "blocked")),
            ("call_provider", ("telnyx", "idt")),
        )
    ):
        _enum(name, *values).drop(bind, checkfirst=True)
