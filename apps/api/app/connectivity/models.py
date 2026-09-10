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
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
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


def _enum_required(enum_type: type[Enum], name: str) -> "Column[Any]":
    """An enum column with no default. Used where there is no sensible one."""
    return Column(
        SAEnum(
            enum_type,
            name=name,
            values_callable=lambda choices: [choice.value for choice in choices],
        ),
        nullable=False,
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
    #: When the *supplier* released the profile for download. Chunk 15 added
    #: this because Telnyx reports `esim_installation_status: released` and
    #: somebody will eventually read that as "installed". It is not. Nobody at
    #: a carrier can observe a handset; only the device can tell us, and that
    #: is what `installed_at` records.
    profile_released_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
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
    #: The supplier's own status string, kept verbatim (chunk 15). Our states
    #: are an interpretation; this is the thing that was interpreted, and an
    #: operator asking "but what does the carrier say" gets an answer instead
    #: of a translation of a translation.
    provider_status: str | None = Field(
        default=None, sa_column=Column(String(50), nullable=True)
    )
    provider_status_observed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: Voice is its own fact. A line can be active for data and carry no voice
    #: service at all, and selling a native-voice plan against one is the
    #: failure `market.py` exists to prevent.
    voice_enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    voice_enabled_observed_at: datetime | None = Field(
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
    #: The supplier's identifier for the number resource, when it has one.
    #: Nullable because a supplier may only ever tell us the number itself.
    provider_number_reference: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    assigned_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    released_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


# --- chunk 15: lifecycle actions and installation credentials ---------------


class LineActionKind(str, Enum):
    """What was asked of the carrier.

    Narrow on purpose. `TERMINATE` is absent because deleting an eSIM is
    documented as irreversible and the profile cannot be re-registered — that
    is an operator decision with a person behind it, not something a worker
    queues.
    """

    ACTIVATE = "activate"
    SUSPEND = "suspend"
    RESUME = "resume"
    ENABLE_VOICE = "enable_voice"


class LineActionState(str, Enum):
    """Four states, because every carrier lifecycle change is asynchronous.

    Telnyx is explicit: *"All state changes return 202 with a SIM Card Action —
    they are not instant."* So there is a real difference between having
    decided to suspend a line, having asked, having been told it happened, and
    having been told it did not:

    | State | What is true |
    |---|---|
    | `REQUESTED` | We decided. Nothing has been sent. |
    | `PENDING` | The carrier accepted the request and is working on it. |
    | `CONFIRMED` | The carrier says it is done. |
    | `FAILED` | The carrier says it did not happen. |

    Collapsing `PENDING` into `CONFIRMED` is how an app tells somebody their
    line is suspended while it is still passing traffic and still costing money.
    """

    REQUESTED = "requested"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class CarrierLineAction(SQLModel, table=True):
    """One requested lifecycle change on one line, and how far it has got.

    The partial unique index is the concurrency guard: a line may have at most
    one *open* action at a time. Two simultaneous suspend requests are not two
    suspensions, and a suspend racing a resume has no defined answer — Telnyx
    refuses a transition while another is in progress anyway, so the database
    refuses it first and gives a comprehensible error instead of a supplier
    rejection nobody can act on.
    """

    __tablename__ = "carrier_line_actions"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_action_reference", name="uq_line_actions_provider_ref"
        ),
        # An action that settled must say when, and one that has not must not
        # pretend to. Chunk 17's suspension states are read off these rows.
        CheckConstraint(
            "(state IN ('confirmed', 'failed') AND settled_at IS NOT NULL) "
            "OR (state NOT IN ('confirmed', 'failed') AND settled_at IS NULL)",
            name="ck_line_actions_settled_at",
        ),
        CheckConstraint(
            "(state = 'requested' AND provider_action_reference IS NULL) "
            "OR state <> 'requested'",
            name="ck_line_actions_requested_has_no_reference",
        ),
        Index(
            "ux_carrier_line_actions_open",
            "carrier_line_id",
            unique=True,
            postgresql_where=text("state IN ('requested', 'pending')"),
            sqlite_where=text("state IN ('requested', 'pending')"),
        ),
        Index("ix_carrier_line_actions_open_state", "state", "requested_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    carrier_line_id: UUID = Field(
        sa_column=Column(
            ForeignKey("carrier_lines.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    provider: str = Field(sa_column=Column(String(32), nullable=False))
    kind: LineActionKind = Field(
        sa_column=_enum_required(LineActionKind, "line_action_kind")
    )
    state: LineActionState = Field(
        default=LineActionState.REQUESTED,
        sa_column=_enum(
            LineActionState, "line_action_state", LineActionState.REQUESTED
        ),
    )
    #: The carrier's handle on the asynchronous change. Null until they accept.
    provider_action_reference: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    #: Why it failed, in the carrier's words where they gave any.
    failure_reason: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    requested_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    settled_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class EsimActivationCredential(SQLModel, table=True):
    """The installation material for one profile, encrypted at rest.

    This is the most sensitive row in the connectivity schema. Telnyx documents
    that an eSIM activation code is **one-time use**: a profile that is lost
    cannot be re-downloaded and needs a fresh purchase. So a leaked activation
    code is not a credential that can be rotated — it is a paid-for profile
    somebody else can install instead of the customer.

    Three consequences, all of them structural rather than procedural:

    - The plaintext is never stored. `ciphertext` holds it sealed under a key
      named by `key_reference`, so a database dump on its own is not a set of
      working eSIMs.
    - `fingerprint` exists so support and tests can say "the same code" without
      anybody handling the code. It is a keyed hash, not the value.
    - Retrieval is counted. A profile fetched three times is either a customer
      with a broken installation or somebody else fetching it, and both are
      worth being able to see.
    """

    __tablename__ = "esim_activation_credentials"
    __table_args__ = (
        UniqueConstraint(
            "esim_installation_id", name="uq_esim_activation_credentials_installation"
        ),
        CheckConstraint(
            "delivery_count >= 0", name="ck_esim_activation_credentials_deliveries"
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    esim_installation_id: UUID = Field(
        sa_column=Column(
            ForeignKey("esim_installations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    #: Names the key this was sealed under, never the key itself. Rotation
    #: re-seals rows and changes this; without it, a rotated key makes every
    #: existing profile unreadable with no way to tell which are affected.
    key_reference: str = Field(sa_column=Column(String(64), nullable=False))
    ciphertext: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    #: Keyed hash of the plaintext. Comparable, not reversible.
    fingerprint: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    one_time_use: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default="true")
    )
    delivery_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    last_delivered_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class CredentialGrant(SQLModel, table=True):
    """A short-lived, single-use authorization to fetch one profile.

    The alternative — an endpoint that returns the activation code to anyone
    holding a session for the account — makes the profile as durable as the
    session, and sessions are long. A grant is minutes long, redeemable once,
    and bound to the person it was issued to, so an intercepted link is worth
    almost nothing almost immediately.

    Only the token's hash is stored. A grants table that could hand out its own
    tokens is a second copy of the secret it protects.
    """

    __tablename__ = "esim_credential_grants"
    __table_args__ = (
        UniqueConstraint("token_fingerprint", name="uq_credential_grants_token"),
        CheckConstraint(
            "expires_at > issued_at", name="ck_credential_grants_window"
        ),
        Index(
            "ix_credential_grants_live",
            "credential_id",
            "expires_at",
            postgresql_where=text("redeemed_at IS NULL"),
            sqlite_where=text("redeemed_at IS NULL"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    credential_id: UUID = Field(
        sa_column=Column(
            ForeignKey("esim_activation_credentials.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    #: Who may redeem it. A grant that any authenticated caller can spend is a
    #: URL, and URLs end up in screenshots and support tickets.
    subject_user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    token_fingerprint: str = Field(sa_column=Column(String(64), nullable=False))
    issued_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    redeemed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
