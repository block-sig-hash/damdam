from uuid import UUID

from pydantic import BaseModel


class RetailPricingTierResponse(BaseModel):
    id: UUID
    name: str
    ngn_price: float
    data_gb: int
    pstn_minutes: int
    is_group_tier: bool
    min_group_size: int | None = None
    max_group_size: int | None = None
    per_person_ngn_rate: float | None = None


class RetailPricingTierListResponse(BaseModel):
    tiers: list[RetailPricingTierResponse]
