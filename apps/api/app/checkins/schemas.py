from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CheckInCreate(BaseModel):
    client_generated_id: UUID
    timestamp: datetime
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def location_is_a_pair(self) -> "CheckInCreate":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class CheckInCreateResponse(BaseModel):
    id: UUID
    received_at: datetime


class CheckInResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    timestamp: datetime
    latitude: float | None
    longitude: float | None


class CheckInHistoryResponse(BaseModel):
    checkins: list[CheckInResponse]


class MetaWebhookResponse(BaseModel):
    processed: int
