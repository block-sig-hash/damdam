from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel


class CallDirection(str, Enum):
    OUTBOUND = "outbound"


class CallType(str, Enum):
    PSTN = "pstn"
    APP_TO_APP = "app_to_app"


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
    user_id: UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
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
