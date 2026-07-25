from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.voice.models import CallType
from app.voice.nigerian_numbers import normalize_nigerian_number


class VoiceEligibilityResponse(BaseModel):
    allowed: bool
    call_type: CallType
    destination: str | None = None
    reason: Literal["cli_not_verified", "pstn_balance_exhausted"] | None = None
    pstn_minutes_remaining: float


class VoiceTokenRequest(BaseModel):
    to_number: str

    _normalize_number = field_validator("to_number")(normalize_nigerian_number)


class VoiceTokenResponse(BaseModel):
    token: str
    sip_username: str
    expires_at: datetime
    call_type: CallType
    destination: str


class CallResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    call_type: CallType
    to_number: str | None
    duration_seconds: int
    pstn_minutes_charged: float
    started_at: datetime


class CallHistoryResponse(BaseModel):
    calls: list[CallResponse]


class WebhookResponse(BaseModel):
    processed: bool
