from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlmodel import Session, col, select

from app.auth.models import (
    Manifest,
    ManifestOrder,
    ManifestPilgrim,
    Organization,
    PricingTier,
    User,
)
from app.esim.models import EsimIssuanceJob
from app.esim.service import EsimIssuanceScheduler
from app.packages.models import Package, PackageSource, PackageStatus


class ActivationError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass
class ActivationPreview:
    valid: bool
    reason: str | None
    organization_name: str | None
    pricing_tier_name: str | None


class ActivationService:
    def __init__(
        self, clock: Callable[[], datetime], esim_scheduler: EsimIssuanceScheduler
    ) -> None:
        self.clock = clock
        self.esim_scheduler = esim_scheduler

    def preview(self, session: Session, activation_code: str) -> ActivationPreview:
        pilgrim = self._find(session, activation_code)
        organization_name = self._organization_name(session, pilgrim)
        tier_name = self._tier_name(session, pilgrim)
        if pilgrim.activation_code_used:
            return ActivationPreview(
                valid=False,
                reason="activation_code_already_used",
                organization_name=organization_name,
                pricing_tier_name=tier_name,
            )
        if self._is_expired(pilgrim):
            return ActivationPreview(
                valid=False,
                reason="activation_code_expired",
                organization_name=organization_name,
                pricing_tier_name=tier_name,
            )
        return ActivationPreview(
            valid=True,
            reason=None,
            organization_name=organization_name,
            pricing_tier_name=tier_name,
        )

    def redeem(self, session: Session, user: User, activation_code: str) -> Package:
        pilgrim = self._find(session, activation_code)
        if pilgrim.activation_code_used:
            raise ActivationError("activation_code_already_used")
        if self._is_expired(pilgrim):
            raise ActivationError("activation_code_expired")
        if pilgrim.phone_number != user.phone_number:
            raise ActivationError("activation_code_phone_mismatch")
        tier = self._tier(session, pilgrim)
        if tier is None:
            raise ActivationError("activation_code_invalid")

        # Atomic conditional update closes the race between two
        # concurrent redemptions of the same single-use code: only the
        # request that actually flips activation_code_used False->True
        # proceeds to create a package.
        result = cast(
            CursorResult[Any],
            session.execute(
                update(ManifestPilgrim)
                .where(
                    col(ManifestPilgrim.id) == pilgrim.id,
                    col(ManifestPilgrim.activation_code_used).is_(False),
                )
                .values(user_id=user.id, activation_code_used=True)
            ),
        )
        if result.rowcount == 0:
            raise ActivationError("activation_code_already_used")

        package = Package(
            user_id=user.id,
            pricing_tier_id=tier.id,
            source=PackageSource.HTO_MANIFEST,
            status=PackageStatus.ACTIVE,
            group_size=1,
            data_gb_total=tier.data_gb,
            data_gb_remaining=tier.data_gb,
            pstn_minutes_total=tier.pstn_minutes,
            pstn_minutes_remaining=tier.pstn_minutes,
            purchased_at=self.clock(),
        )
        session.add(package)
        session.add(
            EsimIssuanceJob(package_id=package.id, next_attempt_at=self.clock())
        )
        session.commit()
        session.refresh(package)
        try:
            self.esim_scheduler.schedule(package.id, 0)
        except Exception:
            return package
        job = session.exec(
            select(EsimIssuanceJob).where(EsimIssuanceJob.package_id == package.id)
        ).one()
        job.next_attempt_at = None
        session.add(job)
        session.commit()
        return package

    def _is_expired(self, pilgrim: ManifestPilgrim) -> bool:
        expires_at = pilgrim.activation_code_expires_at
        if expires_at is None:
            return True
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= self.clock()

    @staticmethod
    def _find(session: Session, activation_code: str) -> ManifestPilgrim:
        pilgrim = session.exec(
            select(ManifestPilgrim).where(
                ManifestPilgrim.activation_code == activation_code
            )
        ).first()
        if pilgrim is None:
            raise ActivationError("activation_code_invalid")
        return pilgrim

    @staticmethod
    def _organization_name(session: Session, pilgrim: ManifestPilgrim) -> str | None:
        manifest = session.get(Manifest, pilgrim.manifest_id)
        if manifest is None:
            return None
        organization = session.get(Organization, manifest.organization_id)
        return organization.name if organization else None

    @staticmethod
    def _tier(session: Session, pilgrim: ManifestPilgrim) -> PricingTier | None:
        if pilgrim.manifest_order_id is None:
            return None
        order = session.get(ManifestOrder, pilgrim.manifest_order_id)
        if order is None:
            return None
        return session.get(PricingTier, order.pricing_tier_id)

    @classmethod
    def _tier_name(cls, session: Session, pilgrim: ManifestPilgrim) -> str | None:
        tier = cls._tier(session, pilgrim)
        return tier.name if tier else None
