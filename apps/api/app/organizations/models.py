"""Organization memberships (US-29, chunk 07).

The legacy model gave an organization *one* email and *one* password hash on
`organizations`. Everyone who administered the account shared them, so there was
no answer to "who did this", no way to remove one person's access without
changing everyone's, and no way to require a second factor of anybody in
particular.

A membership names an individual. Access is the join between a person and an
organization, held in one row per pair so that revoking it is a state change on
a row that already exists rather than a delete-and-hope. History stays in
`audit_log`; this table answers only "what may this person do here, right now".
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now
from app.identity.models import IdentifierKind


def _enum(
    enum_type: type[Enum], name: str, default: Enum | None = None
) -> "Column[Any]":
    return Column(
        SAEnum(
            enum_type,
            name=name,
            values_callable=lambda choices: [choice.value for choice in choices],
        ),
        nullable=False,
        server_default=None if default is None else default.value,
    )


class OrganizationRole(str, Enum):
    """Ordered by authority. `rank()` is what the escalation rules compare.

    The order is load-bearing, not cosmetic: "may not grant a role above your
    own" is meaningless without it.
    """

    OWNER = "owner"
    ADMINISTRATOR = "administrator"
    BILLING = "billing"
    MEMBER = "member"


_RANK = {
    OrganizationRole.OWNER: 3,
    OrganizationRole.ADMINISTRATOR: 2,
    OrganizationRole.BILLING: 1,
    OrganizationRole.MEMBER: 0,
}


def rank(role: OrganizationRole) -> int:
    return _RANK[role]


class MembershipStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


class OrganizationMember(SQLModel, table=True):
    """One row per (organization, person) pair, for the life of the pair.

    Revocation is a status change, never a delete: a deleted row cannot explain
    why an order placed last month was authorized, and re-adding someone would
    otherwise race with the row that was supposed to be gone.
    """

    __tablename__ = "organization_members"
    __table_args__ = (
        # The database is the last line against a duplicated membership. Two
        # simultaneous invitation acceptances both see "not a member yet"; only
        # one of them can insert.
        UniqueConstraint(
            "organization_id", "user_id", name="uq_organization_members_pair"
        ),
        CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL) "
            "OR (status = 'active' AND revoked_at IS NULL)",
            name="ck_organization_members_revoked_at",
        ),
        Index(
            "ix_organization_members_active",
            "organization_id",
            "status",
        ),
        Index("ix_organization_members_user", "user_id", "status"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(
        sa_column=Column(
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    role: OrganizationRole = Field(
        sa_column=_enum(OrganizationRole, "organization_role")
    )
    status: MembershipStatus = Field(
        default=MembershipStatus.ACTIVE,
        sa_column=_enum(
            MembershipStatus, "organization_membership_status", MembershipStatus.ACTIVE
        ),
    )
    invited_by_user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
    )
    joined_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    revoked_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class InvitationStatus(str, Enum):
    """`expired` is deliberately absent.

    Expiry is a fact about `expires_at` and the current time, so storing it as a
    status would create a second, lagging answer that only a sweeper job keeps
    true -- and a stale `pending` row would then be accepted after its deadline.
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"


class OrganizationInvitation(SQLModel, table=True):
    """An offer of a named role, addressed to one identifier.

    The address is the binding, not the link. A forwarded, leaked or guessed
    invitation is worth nothing to anyone who cannot prove they own the
    identifier it names, which is why acceptance re-checks a *verified*
    `account_identifiers` row rather than trusting possession of the token.
    """

    __tablename__ = "organization_invitations"
    __table_args__ = (
        # At most one live offer per address per organization. Without this, an
        # invite endpoint called twice leaves two roles outstanding and the
        # recipient picks whichever is better.
        Index(
            "ux_organization_invitations_pending",
            "organization_id",
            "invited_kind",
            "invited_value",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
        Index(
            "ix_organization_invitations_recipient",
            "invited_kind",
            "invited_value",
            "status",
        ),
        # A bootstrap invitation carries no token and no deadline: it is created
        # by a migration, which can neither send mail nor know when someone will
        # read it. Every other invitation must expire and must carry a token.
        CheckConstraint(
            "(is_bootstrap AND token_hash IS NULL AND expires_at IS NULL) "
            "OR (NOT is_bootstrap AND token_hash IS NOT NULL "
            "AND expires_at IS NOT NULL)",
            name="ck_organization_invitations_bootstrap",
        ),
        CheckConstraint(
            "(status = 'accepted' AND accepted_at IS NOT NULL "
            "AND accepted_by_user_id IS NOT NULL) "
            "OR (status <> 'accepted' AND accepted_at IS NULL "
            "AND accepted_by_user_id IS NULL)",
            name="ck_organization_invitations_accepted",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(
        sa_column=Column(
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    role: OrganizationRole = Field(
        sa_column=_enum(OrganizationRole, "organization_role")
    )
    invited_kind: IdentifierKind = Field(
        sa_column=_enum(IdentifierKind, "identifier_kind")
    )
    #: Normalized by `app.identity.service.normalize`, so the lookup and the
    #: unique index compare the same thing the verified identifier stores.
    invited_value: str = Field(sa_column=Column(String(320), nullable=False))
    #: Only the hash. A database leak yields no usable invitation links.
    token_hash: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True, unique=True)
    )
    is_bootstrap: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default="false")
    )
    status: InvitationStatus = Field(
        default=InvitationStatus.PENDING,
        sa_column=_enum(
            InvitationStatus, "organization_invitation_status", InvitationStatus.PENDING
        ),
    )
    invited_by_user_id: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    accepted_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    accepted_by_user_id: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    revoked_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
