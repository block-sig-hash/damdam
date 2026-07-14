from typing import cast

from fastapi import APIRouter, Request

from app.pricing.schemas import RetailPricingTierListResponse
from app.pricing.service import RetailPricingService

router = APIRouter(prefix="/pricing", tags=["pricing"])


def _service(request: Request) -> RetailPricingService:
    return cast(RetailPricingService, request.app.state.retail_pricing_service)


@router.get(
    "/tiers",
    response_model=RetailPricingTierListResponse,
    response_model_exclude_none=True,
)
def list_retail_pricing_tiers(request: Request) -> RetailPricingTierListResponse:
    with request.app.state.session_factory() as session:
        tiers = _service(request).list_active(session)
    return RetailPricingTierListResponse(tiers=tiers)
