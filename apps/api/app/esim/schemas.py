from datetime import datetime
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
    last_checkin_at: str | None = None
    # "active" | "none" — a two-value signal for the risk-sort/highlight
    # table (US-18 §6.28): AC-18.4 only needs to distinguish an
    # unresolved SOS from everything else, so a pilgrim's past resolved
    # or cancelled alerts are not surfaced here.
    sos_status: str = "none"


class HtoPilgrimListResponse(BaseModel):
    pilgrims: list[HtoPilgrimSummary]


class EsimIssueResponse(BaseModel):
    esim_profile_id: UUID
    iccid: str
    activation_code_lpa: str
    qr_code_url: str
    status: str


class EsimProfileResponse(BaseModel):
    esim_profile_id: UUID
    iccid: str
    qr_code_url: str
    status: str
    downloaded_at: datetime | None = None
    activated_at: datetime | None = None


class EsimDownloadResponse(BaseModel):
    status: str
