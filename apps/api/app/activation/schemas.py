from uuid import UUID

from pydantic import BaseModel, field_validator


class ActivationPreviewResponse(BaseModel):
    valid: bool
    reason: str | None
    organization_name: str | None
    pricing_tier_name: str | None


class ActivationRedeemRequest(BaseModel):
    activation_code: str

    @field_validator("activation_code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("activation_code is required")
        return normalized


class ActivationRedeemResponse(BaseModel):
    package_id: UUID
    pricing_tier_name: str
    data_gb_total: int
    pstn_minutes_total: int
    status: str
