"""US-11 eSIM profiles, issuance retry queue, and vendor-attempt audit.

Revision ID: 0012_us11_esim_profiles
Revises: 0011_us10_device_compatibility
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_us11_esim_profiles"
down_revision: str | None = "0011_us10_device_compatibility"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

event_type = postgresql.ENUM(
    "compatibility_check",
    "issuance_attempt",
    name="device_compatibility_event",
    create_type=False,
)
aggregator = postgresql.ENUM(
    "monty_mobile",
    "esim_access",
    "1global",
    name="esim_aggregator",
    create_type=False,
)
profile_status = postgresql.ENUM(
    "issued",
    "downloaded",
    "activated",
    name="esim_profile_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    event_type.create(bind, checkfirst=True)
    aggregator.create(bind, checkfirst=True)
    profile_status.create(bind, checkfirst=True)

    op.add_column(
        "device_compatibility_log",
        sa.Column(
            "event_type",
            event_type,
            nullable=False,
            server_default="compatibility_check",
        ),
    )
    op.alter_column("device_compatibility_log", "platform", nullable=True)
    op.alter_column("device_compatibility_log", "device_model", nullable=True)
    op.alter_column("device_compatibility_log", "esim_supported", nullable=True)
    op.add_column(
        "device_compatibility_log",
        sa.Column("aggregator", aggregator, nullable=True),
    )
    op.add_column(
        "device_compatibility_log",
        sa.Column("attempt_succeeded", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "device_compatibility_log",
        sa.Column("failure_reason", sa.String(length=255), nullable=True),
    )
    op.alter_column("device_compatibility_log", "event_type", server_default=None)

    op.create_table(
        "esim_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "package_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("packages.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("aggregator", aggregator, nullable=False),
        sa.Column("iccid", sa.String(length=22), nullable=False),
        sa.Column("activation_code_lpa", sa.String(length=255), nullable=False),
        sa.Column("qr_code_url", sa.String(length=500), nullable=False),
        sa.Column(
            "status", profile_status, nullable=False, server_default="issued"
        ),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_esim_profiles_package_id", "esim_profiles", ["package_id"])

    op.create_table(
        "esim_issuance_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "package_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("packages.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("success_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_esim_issuance_jobs_package_id", "esim_issuance_jobs", ["package_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_esim_issuance_jobs_package_id", table_name="esim_issuance_jobs"
    )
    op.drop_table("esim_issuance_jobs")
    op.drop_index("ix_esim_profiles_package_id", table_name="esim_profiles")
    op.drop_table("esim_profiles")

    op.execute(
        "DELETE FROM device_compatibility_log "
        "WHERE event_type = 'issuance_attempt'"
    )
    op.drop_column("device_compatibility_log", "failure_reason")
    op.drop_column("device_compatibility_log", "attempt_succeeded")
    op.drop_column("device_compatibility_log", "aggregator")
    op.alter_column("device_compatibility_log", "esim_supported", nullable=False)
    op.alter_column("device_compatibility_log", "device_model", nullable=False)
    op.alter_column("device_compatibility_log", "platform", nullable=False)
    op.drop_column("device_compatibility_log", "event_type")

    profile_status.drop(op.get_bind(), checkfirst=True)
    aggregator.drop(op.get_bind(), checkfirst=True)
    event_type.drop(op.get_bind(), checkfirst=True)
