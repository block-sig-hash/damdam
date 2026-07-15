from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlmodel import Session, col, select

from app.auth.models import (
    Manifest,
    ManifestOrder,
    ManifestPilgrim,
    Organization,
    PricingTier,
    User,
)
from app.esim.models import DeviceCompatibilityLog
from app.esim.schemas import DeviceCompatibilityCreate, HtoPilgrimSummary


class DeviceCompatibilityService:
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self.clock = clock

    def log_check(
        self,
        session: Session,
        user: User,
        payload: DeviceCompatibilityCreate,
    ) -> DeviceCompatibilityLog:
        entry = DeviceCompatibilityLog(
            user_id=user.id,
            platform=payload.platform,
            device_model=payload.device_model,
            os_version=payload.os_version,
            esim_supported=payload.esim_supported,
            checked_at=self.clock(),
        )
        session.add(entry)
        if not payload.esim_supported:
            # Sticky by design: this is an operational follow-up flag
            # for the HTO, not a live compatibility indicator, so a
            # later recheck reporting "compatible" does not clear it
            # (AC-10.6's "shown once" already means the mobile client
            # won't send a second unsupported check for the same
            # device anyway). Only applies to HTO-manifest-sourced
            # pilgrims — a direct/retail pilgrim has no manifest_pilgrims
            # row and nothing to flag.
            pilgrim = session.exec(
                select(ManifestPilgrim).where(
                    col(ManifestPilgrim.user_id) == user.id
                )
            ).first()
            if pilgrim is not None:
                pilgrim.esim_incompatible_flag = True
                session.add(pilgrim)
        session.commit()
        session.refresh(entry)
        return entry


class HtoPilgrimService:
    def list_pilgrims(
        self,
        session: Session,
        organization: Organization,
        manifest_id: UUID | None,
    ) -> list[HtoPilgrimSummary]:
        query = (
            select(ManifestPilgrim)
            .join(Manifest, col(ManifestPilgrim.manifest_id) == col(Manifest.id))
            .where(col(Manifest.organization_id) == organization.id)
        )
        if manifest_id is not None:
            query = query.where(col(ManifestPilgrim.manifest_id) == manifest_id)
        pilgrims = session.exec(query.order_by(col(ManifestPilgrim.last_name))).all()

        tier_names: dict[UUID, str] = {}
        order_ids = {p.manifest_order_id for p in pilgrims if p.manifest_order_id}
        if order_ids:
            orders = session.exec(
                select(ManifestOrder).where(col(ManifestOrder.id).in_(order_ids))
            ).all()
            tier_ids = {order.pricing_tier_id for order in orders}
            tiers = {
                tier.id: tier.name
                for tier in session.exec(
                    select(PricingTier).where(col(PricingTier.id).in_(tier_ids))
                ).all()
            }
            tier_names = {
                order.id: tiers[order.pricing_tier_id]
                for order in orders
                if order.pricing_tier_id in tiers
            }

        return [
            HtoPilgrimSummary(
                id=pilgrim.id,
                name=f"{pilgrim.first_name} {pilgrim.last_name}".strip(),
                phone_number=pilgrim.phone_number,
                tier=(
                    tier_names.get(pilgrim.manifest_order_id)
                    if pilgrim.manifest_order_id
                    else None
                ),
                esim_status=(
                    "incompatible" if pilgrim.esim_incompatible_flag else "not_checked"
                ),
                activation_status=(
                    "activated" if pilgrim.user_id is not None else "not_activated"
                ),
            )
            for pilgrim in pilgrims
        ]
