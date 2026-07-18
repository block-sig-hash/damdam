from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlmodel import Session, col, select

from app.audit.models import AuditEventType, AuditOutcome
from app.audit.service import AuditLogService
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
from app.packages.service import PackageChainingService


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
        self,
        clock: Callable[[], datetime],
        esim_scheduler: EsimIssuanceScheduler,
        chaining: PackageChainingService,
        audit: AuditLogService,
    ) -> None:
        self.clock = clock
        self.esim_scheduler = esim_scheduler
        self.chaining = chaining
        self.audit = audit

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
            self._log_duplicate_activation(session, user.id, activation_code)
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
            self._log_duplicate_activation(session, user.id, activation_code)
            raise ActivationError("activation_code_already_used")

        window = self.chaining.chain(session, user.id, user.destination_country, tier)
        package = Package(
            user_id=user.id,
            pricing_tier_id=tier.id,
            source=PackageSource.HTO_MANIFEST,
            status=PackageStatus.ACTIVE,
            group_size=1,
            data_gb_total=tier.data_gb,
            data_gb_remaining=Decimal(tier.data_gb) + window.extra_data_gb,
            pstn_minutes_total=tier.pstn_minutes,
            pstn_minutes_remaining=(
                Decimal(tier.pstn_minutes) + window.extra_pstn_minutes
            ),
            purchased_at=self.clock(),
            expires_at=window.expires_at,
            destination_country=user.destination_country,
        )
        session.add(package)
        if window.superseded_package_id is not None:
            self.audit.record(
                session,
                AuditEventType.PACKAGE_PROVISIONING,
                AuditOutcome.PACKAGE_CHAINED_ONTO_ACTIVE_WINDOW,
                user_id=user.id,
                reference=activation_code,
                details=(
                    f"superseded={window.superseded_package_id} "
                    f"rolled_forward_data_gb={window.extra_data_gb} "
                    f"rolled_forward_pstn_minutes={window.extra_pstn_minutes}"
                ),
            )
        # Flush before adding the job row: without an ORM relationship()
        # tying EsimIssuanceJob to Package, SQLAlchemy's flush ordering
        # doesn't infer the FK dependency and may emit the job's INSERT
        # before the package's -- harmless on SQLite (FK enforcement is
        # off by default) but a hard FK violation on real Postgres.
        session.flush()
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

    def _log_duplicate_activation(
        self, session: Session, user_id: UUID, activation_code: str
    ) -> None:
        # Committed here, before the caller raises ActivationError: the
        # route's `with session_factory() as session:` block closes (and
        # rolls back anything uncommitted) once the exception propagates,
        # so the audit write would otherwise be silently lost.
        self.audit.record(
            session,
            AuditEventType.ACTIVATION_REDEMPTION,
            AuditOutcome.DUPLICATE_ACTIVATION_ATTEMPTED,
            user_id=user_id,
            reference=activation_code,
        )
        session.commit()

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
