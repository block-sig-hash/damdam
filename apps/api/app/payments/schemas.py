from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class PurchaseRequest(BaseModel):
    pricing_tier_id: UUID
    group_size: int | None = None


class PurchaseResponse(BaseModel):
    package_id: UUID
    processor: Literal["paystack", "flutterwave"]
    processor_reference: str
    checkout_url: str


class PackageStatusResponse(BaseModel):
    status: Literal["pending", "active", "expired"]
    data_gb_total: int
    data_gb_remaining: float
    pstn_minutes_total: int
    pstn_minutes_remaining: float


class WebhookResponse(BaseModel):
    processed: bool
