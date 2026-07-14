from sqlmodel import Session, col, select

from app.auth.models import PricingTier
from app.pricing.schemas import RetailPricingTierResponse

TIER_ORDER = {"Starter": 0, "Basic": 1, "Standard": 2, "Family": 3}


class RetailPricingService:
    def list_active(self, session: Session) -> list[RetailPricingTierResponse]:
        tiers = session.exec(
            select(PricingTier).where(col(PricingTier.active).is_(True))
        ).all()
        ordered = sorted(
            tiers,
            key=lambda tier: (TIER_ORDER.get(tier.name, len(TIER_ORDER)), tier.name),
        )
        return [
            RetailPricingTierResponse(
                id=tier.id,
                name=tier.name,
                ngn_price=float(tier.ngn_price),
                data_gb=tier.data_gb,
                pstn_minutes=tier.pstn_minutes,
                is_group_tier=tier.is_group_tier,
                min_group_size=tier.min_group_size,
                max_group_size=tier.max_group_size,
                per_person_ngn_rate=(
                    float(tier.ngn_price) if tier.is_group_tier else None
                ),
            )
            for tier in ordered
        ]
