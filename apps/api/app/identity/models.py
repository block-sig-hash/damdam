"""Account identifiers and purpose-bound identity tokens (US-29).

Email is the adopted launch identity and recovery channel. Identifier kind
remains explicit so verified phone numbers can support service-specific flows
without becoming a required account key.
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, text
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.auth.models import utc_now


def _enum(enum_type: type[Enum], name: str) -> "Column[Any]":
    return Column(
        SAEnum(
            enum_type,
            name=name,
            values_callable=lambda choices: [choice.value for choice in choices],
        ),
        nullable=False,
    )


class IdentifierKind(str, Enum):
    EMAIL = "email"
    PHONE = "phone"


class IdentityTokenPurpose(str, Enum):
    """Purpose is bound into the token row, not inferred from the endpoint.

    A verification token and a recovery token grant different things. If one
    could be presented where the other is expected, proving you can read a
    mailbox would become proof you may take over the account it belongs to.
    """

    VERIFY_IDENTIFIER = "verify_identifier"
    RECOVER_ACCOUNT = "recover_account"
    AUTHENTICATE = "authenticate"


class AccountIdentifier(SQLModel, table=True):
    """A login identity claimed by an account, verified or not.

    A row is a *claim* until `verified_at` is set. Unverified claims grant
    nothing and never block anyone else -- uniqueness is enforced only over
    verified rows, so squatting cannot deny service to the real owner.
    """

    __tablename__ = "account_identifiers"
    __table_args__ = (
        # One verified owner per identifier. Partial, so any number of accounts
        # may hold the same *unverified* claim.
        Index(
            "ux_account_identifiers_verified_value",
            "kind",
            "value",
            unique=True,
            postgresql_where=text("verified_at IS NOT NULL"),
            sqlite_where=text("verified_at IS NOT NULL"),
        ),
        Index(
            "ux_account_identifiers_primary_user",
            "user_id",
            unique=True,
            postgresql_where=text("is_primary = true"),
            sqlite_where=text("is_primary = 1"),
        ),
        Index("ix_account_identifiers_user_kind", "user_id", "kind"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    kind: IdentifierKind = Field(sa_column=_enum(IdentifierKind, "identifier_kind"))
    # Stored normalized: lower-cased email, E.164 phone. Normalisation happens
    # in the service so the comparison the unique index performs is the same
    # comparison the lookup performs.
    value: str = Field(sa_column=Column(String(320), nullable=False))
    verified_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    is_primary: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class IdentityToken(SQLModel, table=True):
    """A single-use, expiring, purpose-bound credential sent out of band.

    Only the hash is stored. A database leak therefore yields no usable links.
    """

    __tablename__ = "identity_tokens"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
        )
    )
    identifier_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("account_identifiers.id", ondelete="CASCADE"), nullable=True
        ),
    )
    purpose: IdentityTokenPurpose = Field(
        sa_column=_enum(IdentityTokenPurpose, "identity_token_purpose")
    )
    target_kind: IdentifierKind = Field(
        sa_column=_enum(IdentifierKind, "identifier_kind")
    )
    target_value: str = Field(sa_column=Column(String(320), nullable=False))
    requested_locale: str = Field(
        default="en", sa_column=Column(String(2), nullable=False)
    )
    token_hash: str = Field(
        sa_column=Column(String(64), nullable=False, unique=True, index=True)
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    consumed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
