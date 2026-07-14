from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from app.activation.schemas import (
    ActivationPreviewResponse,
    ActivationRedeemRequest,
    ActivationRedeemResponse,
)
from app.activation.service import ActivationService
from app.auth.dependencies import get_current_user
from app.auth.models import PricingTier, User

router = APIRouter(tags=["pilgrim-activation"])


def _service(request: Request) -> ActivationService:
    return cast(ActivationService, request.app.state.activation_service)


@router.get("/activation/{activation_code}", response_model=ActivationPreviewResponse)
def preview_activation(
    activation_code: str, request: Request
) -> ActivationPreviewResponse:
    with request.app.state.session_factory() as session:
        preview = _service(request).preview(session, activation_code.strip().upper())
    return ActivationPreviewResponse(
        valid=preview.valid,
        reason=preview.reason,
        organization_name=preview.organization_name,
        pricing_tier_name=preview.pricing_tier_name,
    )


@router.post("/me/activation/redeem", response_model=ActivationRedeemResponse)
def redeem_activation(
    payload: ActivationRedeemRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> ActivationRedeemResponse:
    with request.app.state.session_factory() as session:
        package = _service(request).redeem(session, user, payload.activation_code)
        tier = session.get(PricingTier, package.pricing_tier_id)
        assert tier is not None  # redeem() already validated the tier exists
        return ActivationRedeemResponse(
            package_id=package.id,
            pricing_tier_name=tier.name,
            data_gb_total=package.data_gb_total,
            pstn_minutes_total=package.pstn_minutes_total,
            status=package.status.value,
        )
