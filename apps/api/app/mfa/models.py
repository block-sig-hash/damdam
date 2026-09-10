"""Second-factor credentials and step-up elevations (US-29, AC-29.5).

Two tables, answering two different questions:

- `user_mfa_credentials` -- *can* this person prove a second factor? One per
  account, because a second authenticator that nobody remembers enrolling is a
  second way in.
- `organization_elevations` -- *have* they proved it, for this tenant, recently?
  Elevation is a row, not a token claim, which is what makes AC-29.5's
  "immediately" achievable: revoking a membership or disabling a credential
  updates rows inside the same transaction, and the next request reads the new
  state rather than waiting for a JWT to expire.

The elevation is scoped to (person, organization) on purpose. Someone who
administers two tenants proves themselves for the one they are acting on;
proving it once would otherwise silently authorize privileged work in the
other.
"""

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


class MfaStatus(str, Enum):
    """`PENDING` grants nothing.

    An enrollment that was started and never confirmed must not authorize
    anything: otherwise beginning enrollment would itself be the bypass.
    """

    PENDING = "pending"
    ACTIVE = "active"
    DISABLED = "disabled"


class UserMfaCredential(SQLModel, table=True):
    __tablename__ = "user_mfa_credentials"
    __table_args__ = (
        # One live credential per account. A second active secret is a second
        # key to the same door, and nobody audits keys they did not know about.
        Index(
            "ux_user_mfa_credentials_live",
            "user_id",
            unique=True,
            postgresql_where=text("status <> 'disabled'"),
            sqlite_where=text("status <> 'disabled'"),
        ),
        CheckConstraint(
            "failed_attempts >= 0", name="ck_user_mfa_credentials_attempts"
        ),
        CheckConstraint(
            "(status = 'active' AND confirmed_at IS NOT NULL) "
            "OR (status <> 'active' AND TRUE)",
            name="ck_user_mfa_credentials_confirmed",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    # The shared secret. `security.md` §10.14 puts application-managed secret
    # material behind envelope encryption, which chunk 26 owns end to end
    # (KMS, key rotation, the decrypting service role). Until that lands this
    # column holds the raw secret and is called out as an open gap in the
    # handoff rather than being quietly encrypted with a key stored beside it,
    # which would look like protection and provide none.
    secret: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    status: MfaStatus = Field(
        default=MfaStatus.PENDING,
        sa_column=_enum(MfaStatus, "mfa_status", MfaStatus.PENDING),
    )
    #: The highest TOTP counter already spent. A code is good once, not for the
    #: whole thirty seconds it remains arithmetically valid.
    last_used_counter: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    failed_attempts: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    locked_until: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    confirmed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    disabled_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class MfaRecoveryCode(SQLModel, table=True):
    """Single-use fallbacks for a lost authenticator. Hashes only."""

    __tablename__ = "mfa_recovery_codes"
    __table_args__ = (
        UniqueConstraint("code_hash", name="uq_mfa_recovery_codes_hash"),
        Index("ix_mfa_recovery_codes_credential", "credential_id", "used_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    credential_id: UUID = Field(
        sa_column=Column(
            ForeignKey("user_mfa_credentials.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    code_hash: str = Field(sa_column=Column(String(64), nullable=False))
    used_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class OrganizationElevation(SQLModel, table=True):
    """A recent second-factor proof, for one person in one organization."""

    __tablename__ = "organization_elevations"
    __table_args__ = (
        Index(
            "ix_organization_elevations_live",
            "user_id",
            "organization_id",
            "revoked_at",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    organization_id: UUID = Field(
        sa_column=Column(
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    credential_id: UUID = Field(
        sa_column=Column(
            ForeignKey("user_mfa_credentials.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    revoked_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
