"""Line lifecycle, product allowances and sealed activation material — US-35.

Revision ID: 0035_connectivity_line_lifecycle
Revises: 0034_refunds_and_reconciliation

Additive. Nothing is seeded, no existing row is touched, and every added column
is nullable or carries a server default, so an old worker reading these tables
mid-deploy sees exactly what it saw before.

Four constraints carry the chunk's guarantees:

- `ux_carrier_line_actions_open` — a line may have **one** open lifecycle action.
  Two simultaneous suspends are not two suspensions, and a suspend racing a
  resume has no defined answer. Telnyx refuses a transition while another is in
  progress anyway; this refuses it earlier and more comprehensibly.
- `ck_line_actions_settled_at` — an action that claims to have settled must say
  when. Chunk 17's suspension states are read off these rows, and a confirmed
  action with no timestamp makes "when did this line stop working" unanswerable.
- `uq_esim_activation_credentials_installation` — one profile, one credential.
  An eSIM activation code is one-time use: a second row for the same
  installation would mean one of the two profiles is unrecoverable and nobody
  knows which.
- `uq_credential_grants_token` — a delivery token is redeemable once. The table
  stores only the token's fingerprint, so a database dump cannot mint
  deliveries of the profiles it holds.

`product_allowances` is the gap chunk 15 found in the chunk 09 catalog: an
`Entitlement` cannot be granted without knowing what was sold, and `products`
records what a thing is and what it costs but never how much connectivity it
carries. Bytes and seconds, matching `entitlements`, because a supplier reports
usage in bytes and a balance that cannot represent the supplier's own number has
to round in somebody's favour every time.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035_connectivity_line_lifecycle"
down_revision: str | None = "0034_refunds_and_reconciliation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUMS = (
    ("line_action_kind", ("activate", "suspend", "resume", "enable_voice")),
    ("line_action_state", ("requested", "pending", "confirmed", "failed")),
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _ENUMS:
        postgresql.ENUM(*values, name=name, create_type=True).create(
            bind, checkfirst=True
        )

    # --- what the customer actually bought --------------------------------
    op.create_table(
        "product_allowances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("data_bytes", sa.BigInteger(), nullable=False),
        sa.Column("voice_seconds", sa.BigInteger(), nullable=False),
        # Null means "does not expire", which is a real product. Zero would
        # mean the opposite, so the column is nullable rather than defaulted.
        sa.Column("validity_days", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("product_id", name="uq_product_allowances_product"),
        sa.CheckConstraint(
            "data_bytes >= 0 AND voice_seconds >= 0",
            name="ck_product_allowances_not_negative",
        ),
        sa.CheckConstraint(
            "validity_days IS NULL OR validity_days > 0",
            name="ck_product_allowances_validity",
        ),
    )

    # --- what the supplier says, kept apart from what we conclude ---------
    op.add_column(
        "carrier_lines", sa.Column("provider_status", sa.String(50), nullable=True)
    )
    op.add_column(
        "carrier_lines",
        sa.Column("provider_status_observed_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "carrier_lines",
        sa.Column(
            "voice_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "carrier_lines",
        sa.Column("voice_enabled_observed_at", sa.DateTime(timezone=True)),
    )
    # Released for download is not installed on a device. Separate column,
    # separate meaning, and no backfill: we have never observed either fact for
    # an existing row, and inventing one would be inventing evidence.
    op.add_column(
        "esim_installations",
        sa.Column("profile_released_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "assigned_numbers",
        sa.Column("provider_number_reference", sa.String(200), nullable=True),
    )

    # --- asynchronous lifecycle changes -----------------------------------
    op.create_table(
        "carrier_line_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "carrier_line_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("carrier_lines.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(name="line_action_kind", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "state",
            postgresql.ENUM(name="line_action_state", create_type=False),
            nullable=False,
            server_default="requested",
        ),
        sa.Column("provider_action_reference", sa.String(200), nullable=True),
        sa.Column("failure_reason", sa.String(500), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "provider",
            "provider_action_reference",
            name="uq_line_actions_provider_ref",
        ),
        sa.CheckConstraint(
            "(state IN ('confirmed', 'failed') AND settled_at IS NOT NULL) "
            "OR (state NOT IN ('confirmed', 'failed') AND settled_at IS NULL)",
            name="ck_line_actions_settled_at",
        ),
        sa.CheckConstraint(
            "(state = 'requested' AND provider_action_reference IS NULL) "
            "OR state <> 'requested'",
            name="ck_line_actions_requested_has_no_reference",
        ),
    )
    op.create_index(
        "ux_carrier_line_actions_open",
        "carrier_line_actions",
        ["carrier_line_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('requested', 'pending')"),
    )
    op.create_index(
        "ix_carrier_line_actions_open_state",
        "carrier_line_actions",
        ["state", "requested_at"],
    )

    # --- installation material --------------------------------------------
    op.create_table(
        "esim_activation_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "esim_installation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("esim_installations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # The key's name, never the key. A rotation re-seals rows and changes
        # this; without it, a rotated key makes every profile unreadable with
        # no way to tell which rows are affected.
        sa.Column("key_reference", sa.String(64), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False, index=True),
        sa.Column(
            "one_time_use",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "delivery_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("last_delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "esim_installation_id",
            name="uq_esim_activation_credentials_installation",
        ),
        sa.CheckConstraint(
            "delivery_count >= 0", name="ck_esim_activation_credentials_deliveries"
        ),
    )

    op.create_table(
        "esim_credential_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "credential_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("esim_activation_credentials.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "subject_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("token_fingerprint", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_fingerprint", name="uq_credential_grants_token"),
        sa.CheckConstraint("expires_at > issued_at", name="ck_credential_grants_window"),
    )
    op.create_index(
        "ix_credential_grants_live",
        "esim_credential_grants",
        ["credential_id", "expires_at"],
        postgresql_where=sa.text("redeemed_at IS NULL"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_table("esim_credential_grants")
    op.drop_table("esim_activation_credentials")
    op.drop_table("carrier_line_actions")
    op.drop_column("assigned_numbers", "provider_number_reference")
    op.drop_column("esim_installations", "profile_released_at")
    op.drop_column("carrier_lines", "voice_enabled_observed_at")
    op.drop_column("carrier_lines", "voice_enabled")
    op.drop_column("carrier_lines", "provider_status_observed_at")
    op.drop_column("carrier_lines", "provider_status")
    op.drop_table("product_allowances")
    for name, _ in _ENUMS:
        postgresql.ENUM(name=name, create_type=False).drop(bind, checkfirst=True)
