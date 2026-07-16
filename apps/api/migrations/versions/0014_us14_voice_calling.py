"""US-14 Telnyx voice credentials, call history, and billing identifiers.

Revision ID: 0014_us14_voice_calling
Revises: 0013_us13_device_tokens
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_us14_voice_calling"
down_revision: str | None = "0013_us13_device_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

call_direction = postgresql.ENUM("outbound", name="call_direction", create_type=False)
call_type = postgresql.ENUM("pstn", "app_to_app", name="call_type", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    call_direction.create(bind, checkfirst=True)
    call_type.create(bind, checkfirst=True)

    op.create_table(
        "voice_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "telnyx_telephony_credential_id",
            sa.String(length=64),
            nullable=False,
            unique=True,
        ),
        sa.Column("sip_username", sa.String(length=128), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_voice_credentials_user_id", "voice_credentials", ["user_id"])
    op.create_index(
        "ix_voice_credentials_sip_username", "voice_credentials", ["sip_username"]
    )

    # `call_logs` existed only in the written model before this migration, so
    # there is no live Twilio column to rename. The first materialized schema
    # uses Telnyx's stable correlation identifier directly.
    op.create_table(
        "call_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "telnyx_call_leg_id", sa.String(length=64), nullable=False, unique=True
        ),
        sa.Column("direction", call_direction, nullable=False),
        sa.Column("call_type", call_type, nullable=False),
        sa.Column("to_number", sa.String(length=14), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "pstn_minutes_charged",
            sa.Numeric(precision=6, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_call_logs_user_id", "call_logs", ["user_id"])
    op.create_index(
        "ix_call_logs_telnyx_call_leg_id",
        "call_logs",
        ["telnyx_call_leg_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_call_logs_telnyx_call_leg_id", table_name="call_logs")
    op.drop_index("ix_call_logs_user_id", table_name="call_logs")
    op.drop_table("call_logs")
    op.drop_index("ix_voice_credentials_sip_username", table_name="voice_credentials")
    op.drop_index("ix_voice_credentials_user_id", table_name="voice_credentials")
    op.drop_table("voice_credentials")
    call_type.drop(op.get_bind(), checkfirst=True)
    call_direction.drop(op.get_bind(), checkfirst=True)
