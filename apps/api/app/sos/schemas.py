from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.sos.models import SOSStatus


class SOSCreate(BaseModel):
    client_generated_id: UUID
    timestamp: datetime
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def location_pair(self) -> "SOSCreate":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class SOSCreateResponse(BaseModel):
    id: UUID
    status: SOSStatus


class SOSStatusResponse(BaseModel):
    status: SOSStatus


class HtoSOSAlertResponse(BaseModel):
    id: UUID
    pilgrim_name: str
    pilgrim_phone: str
    timestamp: datetime
    latitude: float | None
    longitude: float | None
    status: SOSStatus


class HtoSOSAlertsResponse(BaseModel):
    alerts: list[HtoSOSAlertResponse]
