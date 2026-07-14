from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.auth.models import (
    ManifestOrderStatus,
    ManifestStatus,
    ManifestValidationStatus,
)


class ManifestCreateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ManifestCreateResponse(BaseModel):
    manifest_id: UUID
    status: Literal[ManifestStatus.DRAFT] = ManifestStatus.DRAFT


class ManifestIssue(BaseModel):
    row_number: int
    reason: str


class ManifestPreviewRow(BaseModel):
    id: UUID
    row_number: int
    first_name: str
    last_name: str
    phone_number: str
    passport_number: str | None
    seat_number: str | None
    validation_status: Literal[
        ManifestValidationStatus.VALID, ManifestValidationStatus.DUPLICATE_WARNING
    ]
    warning: str | None = None


class ManifestUploadResponse(BaseModel):
    total_rows: int
    valid_rows: int
    invalid_rows: list[ManifestIssue]
    preview: list[ManifestPreviewRow]


class ManifestConfirmResponse(BaseModel):
    status: Literal[ManifestStatus.VALIDATED] = ManifestStatus.VALIDATED
    pilgrim_count: int


class ManifestSummary(BaseModel):
    id: UUID
    name: str | None
    status: ManifestStatus
    valid_rows: int
    created_at: datetime


class ManifestListResponse(BaseModel):
    manifests: list[ManifestSummary]


class FamilyGroupRequest(BaseModel):
    manifest_pilgrim_ids: list[UUID] = Field(min_length=2)
    group_size: int = Field(ge=2, le=500)


class FamilyGroupResponse(BaseModel):
    family_group_id: UUID


class UnorderedPilgrim(BaseModel):
    id: UUID
    name: str
    phone_number: str
    family_group_id: UUID | None


class UnorderedPilgrimListResponse(BaseModel):
    pilgrims: list[UnorderedPilgrim]


class PricingTierResponse(BaseModel):
    id: UUID
    name: str
    retail_price_ngn: float
    wholesale_price_ngn: float
    estimated_margin_ngn: float
    is_group_tier: bool
    min_group_size: int | None
    max_group_size: int | None


class PricingTierListResponse(BaseModel):
    tiers: list[PricingTierResponse]


class AdminPricingTierResponse(BaseModel):
    id: UUID
    name: str
    ngn_price: float
    is_group_tier: bool


class AdminPricingTierListResponse(BaseModel):
    tiers: list[AdminPricingTierResponse]


class PricingTierUpdateRequest(BaseModel):
    ngn_price: float = Field(gt=0)


class PricingTierUpdateResponse(BaseModel):
    id: UUID
    name: str
    old_ngn_price: float
    new_ngn_price: float
    percent_change: float
    changed_at: datetime


class ManifestOrderRequest(BaseModel):
    pricing_tier_id: UUID
    manifest_pilgrim_ids: list[UUID] = Field(min_length=1)


class ManifestOrderResponse(BaseModel):
    manifest_order_id: UUID
    total_ngn: float
    invoice_url: str


class ManifestOrderDetailResponse(BaseModel):
    id: UUID
    tier_name: str
    pilgrim_count: int
    wholesale_price_ngn: float
    total_ngn: float
    status: ManifestOrderStatus
    invoice_url: str
    payment_confirmed_at: datetime | None


class ManifestOrderSummary(BaseModel):
    id: UUID
    tier_name: str
    pilgrim_count: int
    total_ngn: float
    status: ManifestOrderStatus


class ManifestOrderListResponse(BaseModel):
    orders: list[ManifestOrderSummary]


class AdminManifestOrderSummary(BaseModel):
    id: UUID
    hto_business_name: str
    manifest_name: str | None
    pilgrim_count: int
    total_ngn: float
    invoice_url: str
    days_pending: int


class AdminManifestOrderListResponse(BaseModel):
    orders: list[AdminManifestOrderSummary]


class PaymentConfirmationResponse(BaseModel):
    status: ManifestOrderStatus
