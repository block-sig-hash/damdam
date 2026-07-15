from uuid import UUID

from pydantic import BaseModel

from app.auth.models import Platform


class DeviceCompatibilityCreate(BaseModel):
    platform: Platform
    device_model: str
    os_version: str | None = None
    esim_supported: bool


class DeviceCompatibilityResponse(BaseModel):
    logged: bool = True


class HtoPilgrimSummary(BaseModel):
    id: UUID
    name: str
    phone_number: str
    tier: str | None
    # Deliberately a two-value signal for MVP, not a full lifecycle
    # (issued/downloaded/activated, which belongs to US-11's
    # esim_profiles once that's built): "incompatible" is the only
    # state AC-10.7 requires the HTO dashboard to act on, so
    # "compatible" and "never checked" are both reported as
    # "not_checked" rather than distinguished.
    esim_status: str
    activation_status: str
    # Both literal, honest placeholders — US-15 (check-in) and US-16
    # (SOS) aren't built yet, so "no check-in ever recorded" and "no
    # active SOS" are simply true, not fabricated data.
    last_checkin_at: str | None = None
    sos_status: str = "none"


class HtoPilgrimListResponse(BaseModel):
    pilgrims: list[HtoPilgrimSummary]
