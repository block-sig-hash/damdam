"""Offboarding, as a durable record of what was done and what is still pending.

Chunk 24 (US-40). Two tables, and both exist because **offboarding is not one
action.** Somebody leaves an organization, and what has to happen is: their
dashboard access ends, their ability to spend the organization's money ends,
their unclaimed invitations are withdrawn, their work lines are suspended — and
their *personal* service, which the organization never paid for, is left
completely alone.

Some of those we can do ourselves and instantly. Others are requests to a
carrier whose answer arrives later, or never. A boolean "offboarded" column
would have to lie about the difference, and the lie is expensive in both
directions: an administrator who thinks a line is suspended when the carrier
never confirmed it, or who thinks nothing happened when access was in fact
revoked ten minutes ago.

So `offboarding_actions` records one row per thing attempted, each with its own
outcome — including `pending_carrier`, which is the honest state for a request
that has been made and not answered. The assignment requires exactly that:
*make limits and pending carrier actions clear to administrators.*

## What is deliberately not here

A column that reassigns a line to somebody else. The assignment is explicit —
*do not silently transfer a live profile to another person* — and an eSIM
profile on a departing employee's handset cannot be moved by us changing a row.
Reassignment is a new line for the new holder and a suspension for the old one,
which is two decisions with a person in the middle of them.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
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


class OffboardingState(str, Enum):
    """Where an offboarding run is, in terms an administrator can act on."""

    REQUESTED = "requested"
    IN_PROGRESS = "in_progress"
    #: Everything we could do is done and everything we asked for was answered.
    COMPLETED = "completed"
    #: Everything we could do is done; at least one carrier request has not been
    #: answered. **Not** a failure, and not "completed" either — the difference
    #: is the whole reason this state exists.
    COMPLETED_WITH_PENDING = "completed_with_pending"


class OffboardingActionKind(str, Enum):
    """Each of the separate things "somebody left" actually means."""

    #: Dashboard access. Ours to end, immediately.
    REVOKE_MEMBERSHIP = "revoke_membership"
    #: Unclaimed invitations to work lines. Ours, immediately.
    REVOKE_ACTIVATION_REQUEST = "revoke_activation_request"
    #: A bulk line funded but not yet provisioned: cancel it and release its
    #: hold, because nobody is going to claim it now.
    CANCEL_PENDING_LINE = "cancel_pending_line"
    #: A live work line. A *request* to the carrier, whose answer arrives later.
    SUSPEND_LINE = "suspend_line"
    #: An internet call in progress on the organization's money.
    END_ACTIVE_CALL = "end_active_call"
    #: A top-up the organization authorized and has not spent.
    CANCEL_PENDING_TOP_UP = "cancel_pending_top_up"


class OffboardingActionState(str, Enum):
    REQUESTED = "requested"
    #: Done, by us, and verified in our own tables.
    CONFIRMED = "confirmed"
    #: Asked of a carrier; no answer yet. Visible to an administrator as
    #: outstanding rather than quietly counted as done.
    PENDING_CARRIER = "pending_carrier"
    #: There was nothing of this kind to do. Recorded rather than omitted, so
    #: the record answers "was their line suspended?" with "they had none".
    NOT_APPLICABLE = "not_applicable"
    FAILED = "failed"


class OrganizationOffboarding(SQLModel, table=True):
    """One person leaving one organization."""

    __tablename__ = "organization_offboardings"
    __table_args__ = (
        # One open offboarding per person. Pressing the button twice is the same
        # departure, and two runs would race each other's suspensions.
        Index(
            "ux_organization_offboardings_open",
            "person_id",
            unique=True,
            postgresql_where=text("state IN ('requested', 'in_progress')"),
            sqlite_where=text("state IN ('requested', 'in_progress')"),
        ),
        Index("ix_organization_offboardings_org", "organization_id", "requested_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(
        sa_column=Column(
            ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
    )
    #: `RESTRICT`: chunk 22 archives people rather than deleting them, and the
    #: record of their departure is part of why.
    person_id: UUID = Field(
        sa_column=Column(
            ForeignKey("organization_people.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
    )
    requested_by_user_id: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    state: OffboardingState = Field(
        default=OffboardingState.REQUESTED,
        sa_column=_enum(
            OffboardingState, "offboarding_state", OffboardingState.REQUESTED
        ),
    )
    reason: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    requested_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class OffboardingAction(SQLModel, table=True):
    """One thing attempted, and how it went.

    `target_reference` is a string rather than a foreign key because the targets
    are of different kinds — a membership, an invitation, a line, a call — and a
    nullable column per kind would be five columns, four of them always empty,
    and a sixth kind later.
    """

    __tablename__ = "offboarding_actions"
    __table_args__ = (
        Index("ix_offboarding_actions_run", "offboarding_id", "state"),
        CheckConstraint(
            "(state = 'failed' AND detail IS NOT NULL) OR state <> 'failed'",
            name="ck_offboarding_actions_failure_reason",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    offboarding_id: UUID = Field(
        sa_column=Column(
            ForeignKey("organization_offboardings.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    kind: OffboardingActionKind = Field(
        sa_column=_enum(OffboardingActionKind, "offboarding_action_kind")
    )
    state: OffboardingActionState = Field(
        default=OffboardingActionState.REQUESTED,
        sa_column=_enum(
            OffboardingActionState,
            "offboarding_action_state",
            OffboardingActionState.REQUESTED,
        ),
    )
    #: What it was about: `membership:<id>`, `line:<entitlement id>`,
    #: `activation_request:<id>`, `call:<attempt id>`.
    target_reference: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    detail: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    requested_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    confirmed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
