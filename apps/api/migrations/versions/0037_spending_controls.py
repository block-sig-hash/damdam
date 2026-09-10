"""Top-ups, spending bounds, organization caps and low-balance notices — US-36.

Revision ID: 0037_spending_controls
Revises: 0036_usage_reconciliation

Additive. Nothing is seeded, no existing row is touched, and no column is added
to an existing table.

Five constraints carry the chunk's guarantees:

- `uq_entitlement_top_ups_order_item` — one purchase, one top-up, however many
  times a worker replays the request. This is the idempotency the assignment
  asks for, held by the database rather than by a code path.
- `ck_entitlement_top_ups_applied_at` — a top-up that claims to be applied must
  say when. "When did this allowance become available" has to be answerable,
  because the answer decides whether a failed session was our fault.
- `ck_spending_controls_hard_limit_needs_confirmation` — a control claiming
  supplier enforcement must name the limit the supplier confirmed. Claiming
  enforcement with no confirmed number is the exact overstatement `prd.md`
  AC-36.4 forbids: an app-side balance does not stop a native call.
- `ck_spending_controls_policy_needs_reference` — an approved bounded-exposure
  policy must name its approval. An approval nobody can find is not one.
- `uq_allowance_notices` — a threshold is announced once. Usage corrected
  downward and back up re-crosses 80%, and without this the customer is told
  again every five minutes until they learn to turn notifications off.

**No supplier limit is set by this migration**, and no line acquires a control
row. `spending_controls.enforcement` defaults to `none`, which is the honest
state for Telnyx today: the data limit is documented but its network-side
enforcement latency is not, and no voice cap is documented at all. A prepaid
guarantee stays gated until D1 answers that or somebody approves a
bounded-exposure policy.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037_spending_controls"
down_revision: str | None = "0036_usage_reconciliation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUMS = (
    (
        "top_up_state",
        (
            "requested",
            "reserved",
            "paid",
            "provisioning",
            "outcome_unknown",
            "applied",
            "failed",
        ),
    ),
    (
        "spending_enforcement",
        ("provider_hard_limit", "approved_bounded_exposure", "none"),
    ),
    (
        "spending_control_state",
        ("requested", "active", "outcome_unknown", "failed"),
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _ENUMS:
        postgresql.ENUM(*values, name=name, create_type=True).create(
            bind, checkfirst=True
        )

    op.create_table(
        "entitlement_top_ups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "entitlement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entitlements.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "order_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("order_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("business_event_id", sa.String(200), nullable=False),
        sa.Column("data_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "voice_seconds", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("extends_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "state",
            postgresql.ENUM(name="top_up_state", create_type=False),
            nullable=False,
            server_default="requested",
        ),
        sa.Column("detail", sa.String(500), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("order_item_id", name="uq_entitlement_top_ups_order_item"),
        sa.UniqueConstraint(
            "business_event_id", name="uq_entitlement_top_ups_business_event"
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_entitlement_top_ups_currency_iso4217"
        ),
        sa.CheckConstraint(
            "data_bytes >= 0 AND voice_seconds >= 0",
            name="ck_entitlement_top_ups_not_negative",
        ),
        sa.CheckConstraint(
            "data_bytes > 0 OR voice_seconds > 0 OR extends_days > 0",
            name="ck_entitlement_top_ups_grants_something",
        ),
        sa.CheckConstraint(
            "extends_days >= 0", name="ck_entitlement_top_ups_extension"
        ),
        sa.CheckConstraint("amount >= 0", name="ck_entitlement_top_ups_amount"),
        sa.CheckConstraint(
            "(state = 'applied' AND applied_at IS NOT NULL) "
            "OR (state <> 'applied' AND applied_at IS NULL)",
            name="ck_entitlement_top_ups_applied_at",
        ),
    )
    op.create_index(
        "ix_entitlement_top_ups_entitlement",
        "entitlement_top_ups",
        ["entitlement_id", "state"],
    )

    op.create_table(
        "spending_controls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "carrier_line_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("carrier_lines.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # Defaults to `none`, which is the honest state: nothing enforces a cap
        # until a supplier confirms one or somebody approves a policy.
        sa.Column(
            "enforcement",
            postgresql.ENUM(name="spending_enforcement", create_type=False),
            nullable=False,
            server_default="none",
        ),
        sa.Column(
            "state",
            postgresql.ENUM(name="spending_control_state", create_type=False),
            nullable=False,
            server_default="requested",
        ),
        sa.Column("requested_limit_bytes", sa.BigInteger(), nullable=True),
        sa.Column("confirmed_limit_bytes", sa.BigInteger(), nullable=True),
        sa.Column("policy_reference", sa.String(500), nullable=True),
        # Null means unquantified, which is different from zero and is why
        # Telnyx does not get `provider_hard_limit` today.
        sa.Column("max_overshoot_bytes", sa.BigInteger(), nullable=True),
        sa.Column("detail", sa.String(500), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("carrier_line_id", name="uq_spending_controls_line"),
        sa.CheckConstraint(
            "requested_limit_bytes IS NULL OR requested_limit_bytes >= 0",
            name="ck_spending_controls_requested",
        ),
        sa.CheckConstraint(
            "confirmed_limit_bytes IS NULL OR confirmed_limit_bytes >= 0",
            name="ck_spending_controls_confirmed",
        ),
        sa.CheckConstraint(
            "enforcement <> 'provider_hard_limit' "
            "OR confirmed_limit_bytes IS NOT NULL",
            name="ck_spending_controls_hard_limit_needs_confirmation",
        ),
        sa.CheckConstraint(
            "enforcement <> 'approved_bounded_exposure' "
            "OR policy_reference IS NOT NULL",
            name="ck_spending_controls_policy_needs_reference",
        ),
    )
    op.create_index(
        "ix_spending_controls_open",
        "spending_controls",
        ["state"],
        postgresql_where=sa.text("state IN ('requested', 'outcome_unknown')"),
    )

    op.create_table(
        "organization_spending_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("period_cap_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "enforced", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id", "currency", name="uq_org_spending_policies_identity"
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="ck_organization_spending_policies_currency_iso4217",
        ),
        sa.CheckConstraint(
            "period_cap_amount >= 0", name="ck_org_spending_policies_cap"
        ),
    )

    op.create_table(
        "allowance_notices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "entitlement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entitlements.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("threshold_percent", sa.Integer(), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "entitlement_id", "kind", "threshold_percent", name="uq_allowance_notices"
        ),
        sa.CheckConstraint(
            "threshold_percent > 0 AND threshold_percent <= 100",
            name="ck_allowance_notices_threshold",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        "allowance_notices",
        "organization_spending_policies",
        "spending_controls",
        "entitlement_top_ups",
    ):
        op.drop_table(table)
    for name, _ in _ENUMS:
        postgresql.ENUM(name=name, create_type=False).drop(bind, checkfirst=True)
