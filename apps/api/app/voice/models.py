from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Numeric, String, text
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel


class CallDirection(str, Enum):
    OUTBOUND = "outbound"


class CallType(str, Enum):
    PSTN = "pstn"
    APP_TO_APP = "app_to_app"


class CallProvider(str, Enum):
    TELNYX = "telnyx"
    IDT = "idt"


class VerifiedCallerIdentityStatus(str, Enum):
    UNVERIFIED = "unverified"
    PHONE_VERIFICATION_PENDING = "phone_verification_pending"
    PHONE_VERIFIED = "phone_verified"
    IDENTITY_VERIFICATION_PENDING = "identity_verification_pending"
    IDENTITY_VERIFIED = "identity_verified"
    CONSENT_REQUIRED = "consent_required"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    REVOKED = "revoked"


class PhoneVerificationProviderName(str, Enum):
    TELNYX = "telnyx"


class PhoneVerificationStatus(str, Enum):
    NOT_STARTED = "not_started"
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    EXPIRED = "expired"


class IdentityProviderName(str, Enum):
    MOCK = "mock"


class IdentityVerificationStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class NinMsisdnMatchStatus(str, Enum):
    NOT_CHECKED = "not_checked"
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    UNAVAILABLE = "unavailable"


class CallerIdentityRiskStatus(str, Enum):
    NORMAL = "normal"
    ELEVATED = "elevated"
    BLOCKED = "blocked"


class CallerIdRevocationReason(str, Enum):
    USER_REVOKED = "user_revoked"
    LOST_SIM = "lost_sim"
    ADMIN_SUSPENDED = "admin_suspended"
    ADMIN_FRAUD_HOLD = "admin_fraud_hold"


def _enum_column(enum_cls: type[Enum], name: str, *, nullable: bool) -> Column[Any]:
    return Column(
        SAEnum(
            enum_cls,
            name=name,
            values_callable=lambda choices: [choice.value for choice in choices],
        ),
        nullable=nullable,
    )


class VerifiedCallerIdentity(SQLModel, table=True):
    __tablename__ = "verified_caller_identities"
    __table_args__ = (
        Index(
            "ux_verified_caller_identities_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "ux_verified_caller_identities_active_number",
            "phone_number",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    phone_number: str = Field(
        sa_column=Column(String(14), nullable=False, index=True)
    )
    detected_country: str = Field(sa_column=Column(String(2), nullable=False))
    detected_carrier: str | None = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )
    phone_verification_provider: PhoneVerificationProviderName = Field(
        sa_column=_enum_column(
            PhoneVerificationProviderName, "phone_verification_provider", nullable=False
        )
    )
    phone_verification_reference: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    phone_verification_status: PhoneVerificationStatus = Field(
        default=PhoneVerificationStatus.NOT_STARTED,
        sa_column=_enum_column(
            PhoneVerificationStatus, "phone_verification_status", nullable=False
        ),
    )
    phone_verified_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    identity_provider: IdentityProviderName | None = Field(
        default=None,
        sa_column=_enum_column(
            IdentityProviderName, "identity_provider", nullable=True
        ),
    )
    identity_verification_reference: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    identity_verification_status: IdentityVerificationStatus = Field(
        default=IdentityVerificationStatus.NOT_REQUIRED,
        sa_column=_enum_column(
            IdentityVerificationStatus, "identity_verification_status", nullable=False
        ),
    )
    nin_msisdn_match_status: NinMsisdnMatchStatus = Field(
        default=NinMsisdnMatchStatus.NOT_CHECKED,
        sa_column=_enum_column(
            NinMsisdnMatchStatus, "nin_msisdn_match_status", nullable=False
        ),
    )
    status: VerifiedCallerIdentityStatus = Field(
        default=VerifiedCallerIdentityStatus.UNVERIFIED,
        sa_column=_enum_column(
            VerifiedCallerIdentityStatus,
            "verified_caller_identity_status",
            nullable=False,
        ),
    )
    consent_version: str | None = Field(
        default=None, sa_column=Column(String(20), nullable=True)
    )
    consent_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_reverified_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    risk_status: CallerIdentityRiskStatus = Field(
        default=CallerIdentityRiskStatus.NORMAL,
        sa_column=_enum_column(
            CallerIdentityRiskStatus, "caller_identity_risk_status", nullable=False
        ),
    )
    suspension_reason: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class CallerIdConsent(SQLModel, table=True):
    __tablename__ = "caller_id_consents"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    verified_caller_identity_id: UUID = Field(
        sa_column=Column(
            ForeignKey("verified_caller_identities.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    consent_version: str = Field(sa_column=Column(String(20), nullable=False))
    consented_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    ip_address: str | None = Field(
        default=None, sa_column=Column(String(45), nullable=True)
    )
    device_session_id: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    revoked_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    revocation_reason: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )


class VoiceCredential(SQLModel, table=True):
    __tablename__ = "voice_credentials"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        )
    )
    telnyx_telephony_credential_id: str = Field(
        sa_column=Column(String(64), unique=True, nullable=False)
    )
    sip_username: str = Field(
        sa_column=Column(String(128), unique=True, nullable=False, index=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class CallLog(SQLModel, table=True):
    __tablename__ = "call_logs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
        )
    )
    telnyx_call_leg_id: str = Field(
        sa_column=Column(String(64), unique=True, nullable=False, index=True)
    )
    direction: CallDirection = Field(
        default=CallDirection.OUTBOUND,
        sa_column=Column(
            SAEnum(
                CallDirection,
                name="call_direction",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        ),
    )
    call_type: CallType = Field(
        sa_column=Column(
            SAEnum(
                CallType,
                name="call_type",
                values_callable=lambda choices: [choice.value for choice in choices],
            ),
            nullable=False,
        )
    )
    to_number: str | None = Field(default=None, max_length=14)
    duration_seconds: int = Field(default=0)
    pstn_minutes_charged: Decimal = Field(
        default=Decimal("0.00"),
        sa_column=Column(Numeric(6, 2), nullable=False),
    )
    started_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    ended_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    verified_caller_identity_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("verified_caller_identities.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    idempotency_key: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True, index=True)
    )
    requested_provider: CallProvider | None = Field(
        default=None,
        sa_column=_enum_column(CallProvider, "call_provider", nullable=True),
    )
    failure_code: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    failure_description: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
