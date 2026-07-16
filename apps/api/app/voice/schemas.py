import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.voice.models import CallType


def normalize_dialed_number(value: str) -> str:
    compact = re.sub(r"[\s()-]", "", value)
    if re.fullmatch(r"0\d{10}", compact):
        compact = "+234" + compact[1:]
    if not re.fullmatch(r"\+234\d{10}", compact):
        raise ValueError("Enter a Nigerian number in 0XXXXXXXXXX or +234 format")
    return compact


class VoiceEligibilityResponse(BaseModel):
    allowed: bool
    call_type: CallType
    destination: str | None = None
    reason: Literal["cli_not_verified", "pstn_balance_exhausted"] | None = None
    pstn_minutes_remaining: float


class VoiceTokenRequest(BaseModel):
    to_number: str

    _normalize_number = field_validator("to_number")(normalize_dialed_number)


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
