"""Connectivity identities and their separated states (US-28, data-model.md §6.44).

`esim_profiles.status` in the legacy schema runs `issued -> downloaded ->
activated`, which is three different questions sharing one column: did the
supplier issue a profile, did the handset install it, and is the line live on a
network. They can disagree -- a profile can be installed on a phone that never
attaches, and a line can be suspended with the profile still installed -- so a
single ordered status has to lie about at least one of them.

These tables keep the questions apart:

| Resource | State | Question it answers |
|---|---|---|
| `order_items` | `provisioning_state` | did the supplier fulfil the purchase |
| `esim_installations` | `installation_state` | is the profile on a device |
| `carrier_lines` | `activation_state` | is the line live with the carrier |
| `carrier_lines` | `network_state` | is it attached to a network right now |

The legacy `esim_profiles` table is untouched and keeps its history.
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now


def _enum(enum_type: type[Enum], name: str, default: Enum) -> "Column[Any]":
    return Column(
        SAEnum(
            enum_type,
            name=name,
            values_callable=lambda choices: [choice.value for choice in choices],
        ),
        nullable=False,
        server_default=default.value,
    )


class InstallationState(str, Enum):
    NOT_INSTALLED = "not_installed"
    INSTALLED = "installed"
    REMOVED = "removed"


class ActivationState(str, Enum):
    PENDING = "pending"
    ACTIVATING = "activating"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class NetworkState(str, Enum):
    """What the carrier last told us, with `UNKNOWN` as the honest default.

    Never inferred from activation: a line can be active and unattached, and
    reporting "attached" because we activated it is how a support agent ends up
    telling someone their phone works when it does not.
    """

    UNKNOWN = "unknown"
    ATTACHED = "attached"
    DETACHED = "detached"


class Entitlement(SQLModel, table=True):
    """What a recipient is owed, in exact units.

    Bytes and seconds, not gigabytes and minutes: the legacy `Numeric(6,2)`
    gigabyte balance cannot represent a supplier's byte-level usage report
    without rounding, and rounding a balance in the customer's disfavour is a
    billing defect. Chunk 10's ledger owns consumption; this is the grant.
    """

    __tablename__ = "entitlements"
    __table_args__ = (
        CheckConstraint(
            "data_bytes_total >= 0", name="ck_entitlements_data_not_negative"
        ),
        CheckConstraint(
            "voice_seconds_total >= 0", name="ck_entitlements_voice_not_negative"
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    order_item_id: UUID = Field(
        sa_column=Column(
            ForeignKey("order_items.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
            index=True,
        )
    )
    holder_user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
        ),
    )
    product_id: UUID = Field(
        sa_column=Column(ForeignKey("products.id"), nullable=False)
    )
    # BigInteger, not Integer: a 5 GB grant is 5,368,709,120 bytes, which
    # overflows a 32-bit column at anything above ~2 GB.
    data_bytes_total: int = Field(sa_column=Column(BigInteger, nullable=False))
    voice_seconds_total: int = Field(sa_column=Column(BigInteger, nullable=False))
    granted_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class EsimInstallation(SQLModel, table=True):
    """Whether a profile is on a device. Separate from issuing it."""

    __tablename__ = "esim_installations"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    entitlement_id: UUID = Field(
        sa_column=Column(
            ForeignKey("entitlements.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    # Optional link to the legacy profile row, so a migrated record keeps its
    # provenance instead of appearing to have come from nowhere.
    esim_profile_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("esim_profiles.id", ondelete="SET NULL"), nullable=True
        ),
    )
    installation_state: InstallationState = Field(
        default=InstallationState.NOT_INSTALLED,
        sa_column=_enum(
            InstallationState,
            "esim_installation_state",
            InstallationState.NOT_INSTALLED,
        ),
    )
    installed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class CarrierLine(SQLModel, table=True):
    """A line with a carrier. Activation and attachment are separate facts."""

    __tablename__ = "carrier_lines"
    __table_args__ = (
        Index(
            "ux_carrier_lines_carrier_reference",
            "carrier",
            "carrier_line_reference",
            unique=True,
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    entitlement_id: UUID = Field(
        sa_column=Column(
            ForeignKey("entitlements.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
    )
    carrier: str = Field(sa_column=Column(String(32), nullable=False))
    carrier_line_reference: str = Field(
        sa_column=Column(String(128), nullable=False)
    )
    iccid: str | None = Field(
        default=None, sa_column=Column(String(22), nullable=True)
    )
    activation_state: ActivationState = Field(
        default=ActivationState.PENDING,
        sa_column=_enum(
            ActivationState, "carrier_line_activation_state", ActivationState.PENDING
        ),
    )
    network_state: NetworkState = Field(
        default=NetworkState.UNKNOWN,
        sa_column=_enum(
            NetworkState, "carrier_line_network_state", NetworkState.UNKNOWN
        ),
    )
    network_state_observed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AssignedNumber(SQLModel, table=True):
    """A number assigned to a line, with release history preserved.

    Uniqueness is over *live* assignments only. A number that has been released
    can legitimately be assigned again later, and the old row has to survive to
    explain who held it when a call was billed.
    """

    __tablename__ = "assigned_numbers"
    __table_args__ = (
        Index(
            "ux_assigned_numbers_live_e164",
            "e164",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
        ),
        # PostgreSQL-only DDL, for the same reason as the currency check in
        # app/money.py: `~` is not SQLite syntax.
        CheckConstraint(
            "e164 ~ '^\\+[1-9][0-9]{6,14}$'", name="ck_assigned_numbers_e164"
        ).ddl_if(dialect="postgresql"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    carrier_line_id: UUID = Field(
        sa_column=Column(
            ForeignKey("carrier_lines.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
    )
    e164: str = Field(sa_column=Column(String(16), nullable=False))
    country: str = Field(sa_column=Column(String(2), nullable=False))
    assigned_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    released_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
