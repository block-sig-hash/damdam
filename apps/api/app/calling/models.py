"""Call authorization, provider legs, durable operations and the event inbox.

Five tables, and the reason each exists is a specific way a calling product
loses money or leaks a call across a tenant boundary.

**`call_attempts`** is the grant. It is written before anything external happens
and it records, immutably, every fact that decides what the call may do: who is
paying, in what currency, from what identity, to which normalized destination,
under which tariff version, against which reservation, until when. The client
supplies a destination *claim*; this row is the authority. `grant_consumed_at`
is a single-use latch — the conditional update that sets it is the only thing
standing between one authorization and two funded calls.

**`call_legs`** is separate from attempts because the two are not the same
count. V01's cost review is blunt about it: the number of billable legs per
attempt is unproven for the chosen topology, and the retained legacy code
assumed exactly one. A partial unique index allows exactly one *live* destination
leg per attempt, which is the "no duplicate PSTN leg" requirement held by the
database rather than by a code path.

**`call_operations`** records a provider command *before* it is sent, so a lost
response has something to reconcile against. `command_id` on the provider side
deduplicates for 60 seconds; a worker restart takes longer than that, and after
it the only safe question is "what did operation X produce", never "let me try
again".

**`call_events`** is the durable inbox. Review finding 3 on V01: an Ed25519
signature plus a timestamp tolerance accepts the *same valid event* again inside
the window, so freshness is not deduplication. The unique provider event id is.
It retains the payload because late and reordered events have to be processable
after the fact, which `fulfilment.InboxMessage` — a dedup marker with no body —
cannot do.

**`calling_client_credentials`** is one credential per device, revocable alone.
Reuse item F3: the retired model gave each *user* one credential, and Telnyx's
own guidance is per device. Sharing one SIP identity across devices means a
revocation either takes out every device or none of them.

Nothing here references an eSIM installation or a carrier line. The calling
amendment requires internet calling to be sellable without either, and a
nullable foreign key would still be a column somebody eventually populates and
then depends on.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now
from app.calling.contract import LegRole, LegState
from app.catalog.tariffs import DestinationKind, OriginKind
from app.money import currency_check, currency_column, money_column, rate_column


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


def _json(nullable: bool = False) -> Column[Any]:
    return Column(JSON().with_variant(JSONB, "postgresql"), nullable=nullable)


class PayerKind(str, Enum):
    """Who the call is billed to, recorded once and never recomputed.

    A member's work calls and their personal calls use the same account and the
    same device. Deriving the payer at settlement time from "is this user in an
    organization" would move a personal call onto a company budget the moment
    somebody joined one, and move it back when they left.
    """

    USER = "user"
    ORGANIZATION = "organization"


class AttemptState(str, Enum):
    """The attempt's own lifecycle, in provider-observable terms.

    The assignment requires accepted, ringing, answered, terminal and unknown to
    be distinguishable, and they are, because each drives a different recovery:

    - `AUTHORIZED` — a grant exists and has been paid for in reserved funds. No
      external effect yet, so expiry is the only cleanup needed.
    - `ACCEPTED` — the provider has the client's call and is holding it. Money is
      still only reserved; nothing is billable yet.
    - `RINGING` / `ANSWERED` — the destination leg exists. From `ANSWERED` there
      is supplier liability whatever happens next.
    - `COMPLETED` / `FAILED` — terminal, and the difference matters to a
      customer: one is a call, the other is not.
    - `UNKNOWN` — we asked for something and lost the answer. The reservation
      stays held (invariant 8) until reconciliation says otherwise. It is never
      a synonym for failure.
    - `EXPIRED` / `CANCELLED` — the grant died unused.
    """

    AUTHORIZED = "authorized"
    ACCEPTED = "accepted"
    RINGING = "ringing"
    ANSWERED = "answered"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


#: Attempt states from which no further provider work is expected. `UNKNOWN` is
#: not here: an unknown attempt has unfinished business by definition.
TERMINAL_ATTEMPT_STATES = frozenset(
    {
        AttemptState.COMPLETED,
        AttemptState.FAILED,
        AttemptState.EXPIRED,
        AttemptState.CANCELLED,
    }
)

#: Convergence ordering, for the same reason legs have one: events arrive late
#: and out of order, and an attempt must not walk backwards from `ANSWERED` to
#: `RINGING` because a delayed event finally showed up (N10).
ATTEMPT_STATE_RANK: dict[AttemptState, int] = {
    AttemptState.UNKNOWN: -1,
    AttemptState.AUTHORIZED: 0,
    AttemptState.ACCEPTED: 1,
    AttemptState.RINGING: 2,
    AttemptState.ANSWERED: 3,
    AttemptState.COMPLETED: 4,
    AttemptState.FAILED: 4,
    AttemptState.EXPIRED: 4,
    AttemptState.CANCELLED: 4,
}


class CredentialState(str, Enum):
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    OUTCOME_UNKNOWN = "outcome_unknown"
    #: Withdrawn by us — logout, membership revocation, or an operator.
    REVOKED = "revoked"


class CallAttempt(SQLModel, table=True):
    """One authorization to make one call. The authority for everything after.

    Immutability is the point of most of these columns. Destination, identity,
    payer, currency, tariff version and the rate snapshot are written once at
    authorization and are never recomputed — not at start, not on a webhook, not
    at settlement. A tariff published mid-call cannot reprice a call that was
    already quoted, and a destination arriving in a provider event cannot replace
    the one that was authorized.

    The rate is *snapshotted* rather than only referenced. `tariff_id` says which
    version applied, and the four rate columns say what that version said at the
    time. Both, because a foreign key alone makes a historical charge depend on a
    join that a later correction can change, and a snapshot alone loses the
    provenance a dispute needs.
    """

    __tablename__ = "call_attempts"
    __table_args__ = (
        currency_check("call_attempts"),
        # Idempotency is per requesting user, not global: two customers may
        # legitimately generate the same client-side key, and a global unique
        # constraint would let one of them silently receive the other's attempt.
        UniqueConstraint(
            "owner_user_id", "idempotency_key", name="uq_call_attempts_idempotency"
        ),
        UniqueConstraint("reservation_id", name="uq_call_attempts_reservation"),
        CheckConstraint(
            "max_seconds > 0 AND max_charge_amount > 0",
            name="ck_call_attempts_positive_bounds",
        ),
        CheckConstraint(
            "expires_at > created_at", name="ck_call_attempts_expiry_after_creation"
        ),
        # An organization payer must name the organization, and a user payer
        # must not. Without this a work call can be billed to a company that is
        # not recorded anywhere on the row.
        CheckConstraint(
            "(payer_kind = 'organization' AND organization_id IS NOT NULL) "
            "OR (payer_kind = 'user' AND organization_id IS NULL)",
            name="ck_call_attempts_payer_matches_scope",
        ),
        # The grant is single-use, and a consumed grant must say when. The
        # conditional UPDATE that sets this column is the atomic consumption.
        CheckConstraint(
            "(state = 'authorized' AND grant_consumed_at IS NULL) "
            "OR state <> 'authorized'",
            name="ck_call_attempts_unconsumed_while_authorized",
        ),
        CheckConstraint(
            "e164_destination ~ '^\\+[1-9][0-9]{6,14}$'",
            name="ck_call_attempts_destination_e164",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "identity_e164 ~ '^\\+[1-9][0-9]{6,14}$'",
            name="ck_call_attempts_identity_e164",
        ).ddl_if(dialect="postgresql"),
        Index("ix_call_attempts_owner_created", "owner_user_id", "created_at"),
        Index(
            "ix_call_attempts_organization_created", "organization_id", "created_at"
        ),
        # Finds grants to expire and calls to reconcile without scanning
        # history. Both are worker queries and both run often.
        Index("ix_call_attempts_open", "state", "expires_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    #: Supplied by the client. Replaying it returns the same attempt and the
    #: same reservation rather than creating a second of either (N1).
    idempotency_key: str = Field(sa_column=Column(String(200), nullable=False))

    # --- who, and on whose money -----------------------------------------
    owner_user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
        )
    )
    #: `NULL` for a personal call. Its presence is what makes a call a work
    #: call, and a membership revocation acts on exactly these (N17).
    organization_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
    )
    payer_kind: PayerKind = Field(sa_column=_enum(PayerKind, "call_payer_kind"))
    #: The entity selling this call. Nullable only because D3 has not selected
    #: one and `legal_entities` is deliberately unseeded; it is not optional in
    #: the product sense, and V03 cannot settle a call without it.
    seller_legal_entity_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("legal_entities.id", ondelete="RESTRICT"), nullable=True
        ),
    )
    currency: str = Field(sa_column=currency_column())
    #: The allowance this call draws on, when the product grants one. Nullable
    #: because an internet call may be funded from ledger credit alone — there
    #: is no eSIM and therefore need not be a package behind it. Never a
    #: carrier-line reference.
    entitlement_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("entitlements.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
    )

    # --- what was authorized ---------------------------------------------
    e164_destination: str = Field(sa_column=Column(String(16), nullable=False))
    destination_country: str = Field(sa_column=Column(String(2), nullable=False))
    destination_kind: DestinationKind = Field(
        sa_column=_enum(DestinationKind, "voice_destination_kind")
    )
    origin_kind: OriginKind = Field(sa_column=_enum(OriginKind, "voice_origin_kind"))
    origin_country: str | None = Field(
        default=None, sa_column=Column(String(2), nullable=True)
    )
    #: The outbound identity the provider is authorized to present. A number we
    #: own, never the customer's own number: own-number presentation is deferred
    #: (VOICE-EXPANSION) and unproven on this route.
    identity_e164: str = Field(sa_column=Column(String(16), nullable=False))
    identity_number_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("assigned_numbers.id", ondelete="RESTRICT"), nullable=True
        ),
    )

    # --- the price this was authorized at, pinned ------------------------
    tariff_id: UUID = Field(
        sa_column=Column(ForeignKey("tariffs.id", ondelete="RESTRICT"), nullable=False)
    )
    tariff_version: int = Field(sa_column=Column(Integer, nullable=False))
    rate_per_minute_amount: Decimal = Field(sa_column=rate_column())
    rate_setup_amount: Decimal = Field(sa_column=money_column())
    rate_minimum_seconds: int = Field(sa_column=Column(Integer, nullable=False))
    rate_increment_seconds: int = Field(sa_column=Column(Integer, nullable=False))

    # --- the bound on exposure -------------------------------------------
    max_seconds: int = Field(sa_column=Column(Integer, nullable=False))
    #: What `max_seconds` costs at the pinned rate. This is the amount reserved,
    #: and it is the customer-facing retail exposure — supplier cost is a
    #: separate reconciliation that V03 owns.
    max_charge_amount: Decimal = Field(sa_column=money_column())
    reservation_id: UUID = Field(
        sa_column=Column(
            ForeignKey("ledger_reservations.id", ondelete="RESTRICT"), nullable=False
        )
    )

    # --- the device that may use this grant -------------------------------
    client_credential_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("calling_client_credentials.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
    )

    # --- lifecycle --------------------------------------------------------
    state: AttemptState = Field(
        default=AttemptState.AUTHORIZED,
        sa_column=_enum(AttemptState, "call_attempt_state", AttemptState.AUTHORIZED),
    )
    #: The single-use latch. `UPDATE … WHERE grant_consumed_at IS NULL` returning
    #: one row is the whole of grant consumption; a second caller gets zero rows
    #: and must not proceed (N3).
    grant_consumed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    answered_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    ended_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    stop_requested_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: Why it ended, in our vocabulary rather than the provider's.
    end_reason: str | None = Field(
        default=None, sa_column=Column(String(100), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class CallLeg(SQLModel, table=True):
    """One provider leg. The authoritative mapping from our attempt to theirs.

    The partial unique index is the important line in this file. One live
    destination leg per attempt, enforced by PostgreSQL, is what makes a lost
    originate response recoverable instead of expensive: the reconciling worker
    may attempt an insert, and if a leg is already out there the database refuses
    rather than the code remembering to check (N11).

    Provider identifiers are stored but never trusted as the only key. V01: the
    documentation does not establish that independently created legs share a
    session id, so `attempt_id` here is the correlation and `session_id` is
    corroboration.
    """

    __tablename__ = "call_legs"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_call_control_id", name="uq_call_legs_control_id"
        ),
        # One live destination leg per attempt. "Live" is everything that might
        # still be running up a bill.
        Index(
            "ux_call_legs_live_destination",
            "attempt_id",
            unique=True,
            postgresql_where=text(
                "role = 'destination' AND state <> 'ended'"
            ),
            sqlite_where=text("role = 'destination' AND state <> 'ended'"),
        ),
        CheckConstraint(
            "time_limit_seconds IS NULL OR time_limit_seconds > 0",
            name="ck_call_legs_time_limit_positive",
        ),
        # A leg that reports an answer must say when it answered, because
        # duration is measured from it and a missing timestamp silently becomes
        # a zero-second call.
        CheckConstraint(
            "(state IN ('answered', 'bridged') AND answered_at IS NOT NULL) "
            "OR state NOT IN ('answered', 'bridged')",
            name="ck_call_legs_answered_at",
        ),
        CheckConstraint(
            "ended_at IS NULL OR answered_at IS NULL OR ended_at >= answered_at",
            name="ck_call_legs_not_negative_duration",
        ),
        Index("ix_call_legs_attempt_role", "attempt_id", "role"),
        Index("ix_call_legs_session", "provider", "provider_call_session_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    attempt_id: UUID = Field(
        sa_column=Column(
            ForeignKey("call_attempts.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
    )
    role: LegRole = Field(sa_column=_enum(LegRole, "call_leg_role"))
    provider: str = Field(sa_column=Column(String(32), nullable=False))
    provider_call_control_id: str = Field(
        sa_column=Column(String(200), nullable=False)
    )
    provider_call_leg_id: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    provider_call_session_id: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    provider_connection_id: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    #: Which device credential the provider says originated this leg. Checked
    #: against the attempt's credential before any destination command (N6).
    provider_credential_id: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    state: LegState = Field(
        default=LegState.CREATED,
        sa_column=_enum(LegState, "call_leg_state", LegState.CREATED),
    )
    #: What we told the provider this leg's maximum duration was. `NULL` on a
    #: leg the client created, because V01 found no documented provider-enforced
    #: bound on a parked leg — recording zero would claim a limit we do not have.
    time_limit_seconds: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    started_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    answered_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    ended_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    hangup_cause: str | None = Field(
        default=None, sa_column=Column(String(100), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class OperationKind(str, Enum):
    ISSUE_CLIENT_SESSION = "issue_client_session"
    CREATE_DESTINATION_LEG = "create_destination_leg"
    BRIDGE = "bridge"
    HANGUP = "hangup"


class OperationOutcome(str, Enum):
    """What we know about one provider command. Three answers, not two.

    Identical in shape to `fulfilment.AttemptOutcome` and for the identical
    reason: collapsing `OUTCOME_UNKNOWN` into `FAILED` makes a lost response look
    retryable, and here the retry dials a second PSTN leg to a destination that
    is already ringing.
    """

    IN_FLIGHT = "in_flight"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    OUTCOME_UNKNOWN = "outcome_unknown"
    HELD_FOR_REVIEW = "held_for_review"


LIVE_OPERATION_OUTCOMES = (
    OperationOutcome.IN_FLIGHT,
    OperationOutcome.ACCEPTED,
    OperationOutcome.OUTCOME_UNKNOWN,
    OperationOutcome.HELD_FOR_REVIEW,
)


class CallOperation(SQLModel, table=True):
    """One command to the provider, written down before it is sent.

    The provider's own `command_id` deduplicates for 60 seconds. A worker restart
    takes longer, and a retry after that window is not deduplicated by anything
    on their side — V01 §5 states this explicitly. So the durable record is ours,
    and reconciliation asks about `id` rather than about elapsed time (N12).

    The partial unique index permits one live operation per attempt and kind. A
    second concurrent `create_destination_leg` is not a retry; it is a second
    call.
    """

    __tablename__ = "call_operations"
    __table_args__ = (
        UniqueConstraint(
            "provider", "operation_key", name="uq_call_operations_key"
        ),
        CheckConstraint("attempt_number >= 1", name="ck_call_operations_number"),
        CheckConstraint(
            "(outcome = 'accepted' AND provider_reference IS NOT NULL) "
            "OR outcome <> 'accepted'",
            name="ck_call_operations_accepted_reference",
        ),
        Index(
            "ux_call_operations_live",
            "attempt_id",
            "kind",
            "target_key",
            unique=True,
            postgresql_where=text(
                "outcome IN ('in_flight', 'accepted', 'outcome_unknown', "
                "'held_for_review')"
            ),
            sqlite_where=text(
                "outcome IN ('in_flight', 'accepted', 'outcome_unknown', "
                "'held_for_review')"
            ),
        ),
        Index("ix_call_operations_outcome", "outcome", "created_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    attempt_id: UUID = Field(
        sa_column=Column(
            ForeignKey("call_attempts.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
    )
    kind: OperationKind = Field(sa_column=_enum(OperationKind, "call_operation_kind"))
    target_key: str = Field(
        default="", sa_column=Column(String(200), nullable=False, server_default="")
    )
    dispatched_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    provider: str = Field(sa_column=Column(String(32), nullable=False))
    #: Ours. Sent to the provider and reused verbatim on every reconciliation,
    #: so "what did this produce" names one request rather than a time range.
    operation_key: str = Field(sa_column=Column(String(200), nullable=False))
    attempt_number: int = Field(
        default=1, sa_column=Column(Integer, nullable=False, server_default="1")
    )
    outcome: OperationOutcome = Field(
        default=OperationOutcome.IN_FLIGHT,
        sa_column=_enum(
            OperationOutcome, "call_operation_outcome", OperationOutcome.IN_FLIGHT
        ),
    )
    provider_reference: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    #: Why it is unknown or rejected, for the operator who has to decide.
    detail: str | None = Field(
        default=None, sa_column=Column(String(1000), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    settled_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class EventDisposition(str, Enum):
    """What happened to a signed event we stored.

    `QUARANTINED` and `UNMATCHED` are kept apart deliberately. Unmatched is
    ordinary — an event for a leg we have not recorded yet arrives during a race
    and is replayed later. Quarantined means the event contradicted our records:
    a credential that is not the attempt's, a connection we do not use. That is a
    security signal and it should never be filed under "arrived early" (N6).
    """

    APPLIED = "applied"
    DUPLICATE = "duplicate"
    #: Stored, no attempt matched yet. Re-processable.
    UNMATCHED = "unmatched"
    #: Stored and deliberately not applied. Needs a human.
    QUARANTINED = "quarantined"
    #: Applied nothing because it described a state we had already passed.
    SUPERSEDED = "superseded"


class CallEvent(SQLModel, table=True):
    """Every authenticated provider event, stored once, with its body.

    The unique constraint is the replay defence. V01 review finding 3: a valid
    signature and a fresh timestamp accept the *same* event again inside the
    tolerance window, so the signature proves origin and this proves novelty
    (N8). Insert happens before any state transition, so a crash between the two
    leaves a stored event to reprocess rather than a transition nobody recorded.

    The payload is retained because late and reordered delivery has to be
    processable after the fact. `fulfilment.InboxMessage` is the same idea
    without a body, and a body-less marker cannot re-apply an event that arrived
    before the leg it refers to.
    """

    __tablename__ = "call_events"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_event_id", name="uq_call_events_provider_event"
        ),
        Index("ix_call_events_attempt", "attempt_id", "occurred_at"),
        Index("ix_call_events_disposition", "disposition", "received_at"),
        # Finds events stored before their leg existed, for replay.
        Index(
            "ix_call_events_replayable",
            "disposition",
            "received_at",
            postgresql_where=text("disposition = 'unmatched'"),
            sqlite_where=text("disposition = 'unmatched'"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    provider: str = Field(sa_column=Column(String(32), nullable=False))
    provider_event_id: str = Field(sa_column=Column(String(200), nullable=False))
    event_type: str = Field(sa_column=Column(String(100), nullable=False))
    #: When the provider says it happened. Ordering evidence, not authority:
    #: `LEG_STATE_RANK` decides what may be applied.
    occurred_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    received_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    attempt_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("call_attempts.id", ondelete="RESTRICT"), nullable=True
        ),
    )
    leg_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("call_legs.id", ondelete="RESTRICT"), nullable=True
        ),
    )
    disposition: EventDisposition = Field(
        sa_column=_enum(EventDisposition, "call_event_disposition")
    )
    #: Why it was quarantined or left unmatched. Read by an operator, so it names
    #: the rule rather than echoing the payload.
    disposition_reason: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    #: The event body as delivered, minus nothing. Kept so a late event can be
    #: applied later and so a dispute can be answered from what we were told.
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=_json())
    #: Provider-neutral fields derived only after signature verification. These
    #: let a worker replay an early event without re-verifying a body whose HTTP
    #: signature headers no longer exist.
    normalized_payload: dict[str, Any] = Field(default_factory=dict, sa_column=_json())


class CallingClientCredential(SQLModel, table=True):
    """One provider credential for one device or browser installation.

    Reuse item F3 and V01 §7: Telnyx recommends a credential per device and warns
    that several clients on one credential share a SIP identity. Sharing makes
    revocation all-or-nothing — signing out one phone would sign out every device
    the customer owns, so in practice nobody revokes at all.

    The live partial unique index is per `(user, device)`, not global: a device
    that was revoked can legitimately be registered again, and the old row has to
    survive to explain which credential originated a call that was already
    billed.
    """

    __tablename__ = "calling_client_credentials"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_credential_id",
            name="uq_calling_credentials_provider_id",
        ),
        Index(
            "ux_calling_credentials_live_device",
            "user_id",
            "device_id",
            unique=True,
            postgresql_where=text("state <> 'revoked'"),
            sqlite_where=text("state <> 'revoked'"),
        ),
        CheckConstraint(
            "(state = 'revoked' AND revoked_at IS NOT NULL) OR state <> 'revoked'",
            name="ck_calling_credentials_revoked_at",
        ),
        Index("ix_calling_credentials_user", "user_id", "state"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
        )
    )
    #: The client's own stable installation identifier. Opaque to us; it names a
    #: device, never a person, and it is not a secret.
    device_id: str = Field(sa_column=Column(String(200), nullable=False))
    #: What to show a customer revoking a session. Free text from the client, so
    #: it is displayed and never matched on.
    device_label: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    provider: str = Field(sa_column=Column(String(32), nullable=False))
    provider_credential_id: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    provider_connection_id: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    #: The SIP identity the provider assigned. Not a secret and not a
    #: credential — the token is, and no token is ever stored.
    sip_identity: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    state: CredentialState = Field(
        default=CredentialState.ACTIVE,
        sa_column=_enum(
            CredentialState, "calling_credential_state", CredentialState.ACTIVE
        ),
    )
    issuance_reference: UUID = Field(default_factory=uuid4, nullable=False)
    issuance_dispatched_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    issuance_detail: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    #: The parent credential's own expiry, as the provider stated it. A client
    #: session can never outlive this.
    expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    revoked_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    revoked_reason: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    #: Rate limiting on session issuance lives here rather than in Redis so a
    #: restart cannot reset it. The amendment requires credential issuance to be
    #: rate limited; a counter that a process restart clears is not a limit.
    sessions_issued: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False, server_default="0")
    )
    last_session_issued_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
