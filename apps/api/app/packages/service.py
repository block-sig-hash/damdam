from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlmodel import Session, select

from app.audit.models import AuditEventType, AuditOutcome
from app.audit.service import AuditLogService
from app.auth.models import AdminUser, PricingTier
from app.packages.models import Package, PackageStatus


class PackageError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ChainedWindow:
    """The window and rolled-forward balance a new package should use.
    See prd.md US-25 AC-25.3 implementation note and data-model.md §6.30."""

    expires_at: datetime
    extra_data_gb: Decimal
    extra_pstn_minutes: Decimal
    superseded_package_id: UUID | None


class PackageChainingService:
    """AC-25.3: a pilgrim buying a new package while one is already active
    does not get blocked or end up with two concurrently-active packages.
    The purchase supersedes the current one -- the new package's window
    starts when the current one's validity would have ended (not from the
    purchase moment), and any unused balance rolls forward so nothing
    paid-for is stranded. This keeps "exactly one ACTIVE package per user"
    true as an invariant, so nothing that reads "the active package"
    elsewhere in the codebase (e.g. PSTN balance lookup in
    app/voice/service.py) needed to change."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self.clock = clock

    def chain(
        self, session: Session, user_id: UUID, tier: PricingTier
    ) -> ChainedWindow:
        now = self.clock()
        current = session.exec(
            select(Package)
            .where(Package.user_id == user_id, Package.status == PackageStatus.ACTIVE)
            .with_for_update()
        ).first()
        if current is None:
            return ChainedWindow(
                expires_at=now + timedelta(days=tier.validity_days),
                extra_data_gb=Decimal("0.00"),
                extra_pstn_minutes=Decimal("0.00"),
                superseded_package_id=None,
            )

        current_expires_at = current.expires_at
        if current_expires_at is not None and current_expires_at.tzinfo is None:
            current_expires_at = current_expires_at.replace(tzinfo=timezone.utc)

        if current_expires_at is not None and current_expires_at > now:
            # Genuine rebuy while still valid: chain onto it and roll the
            # unused balance forward.
            window = ChainedWindow(
                expires_at=current_expires_at + timedelta(days=tier.validity_days),
                extra_data_gb=Decimal(current.data_gb_remaining),
                extra_pstn_minutes=Decimal(current.pstn_minutes_remaining),
                superseded_package_id=current.id,
            )
            current.status = PackageStatus.SUPERSEDED
            session.add(current)
            return window

        # A package with status=ACTIVE whose window has already passed --
        # nothing sweeps packages to EXPIRED automatically in this system,
        # so this can happen if the pilgrim's last trip's package was never
        # renewed. This is a genuinely separate, unrelated future trip, not
        # a rebuy: don't roll its stale balance forward, don't chain off an
        # already-past expiry. Lazily correct its status to EXPIRED now,
        # since we've just discovered the truth of it.
        current.status = PackageStatus.EXPIRED
        session.add(current)
        return ChainedWindow(
            expires_at=now + timedelta(days=tier.validity_days),
            extra_data_gb=Decimal("0.00"),
            extra_pstn_minutes=Decimal("0.00"),
            superseded_package_id=None,
        )


class PackageAdminService:
    """AC-25.3 (prd.md US-25 implementation note, data-model.md §6.30): a
    pilgrim who mistakenly buys twice needs a way for an admin to undo one
    purchase. Deliberately cancel-only, mirroring the same MVP-scope
    precedent api-spec.md §7.13 already sets for refund processing and
    manual package editing ("a direct database action for MVP"): no
    balance reversal, chain re-linking, or payment refund/credit here --
    an automatic reversal is explicitly future work, tied to the
    payment-abstraction refund capability scaling-infrastructure.md
    already lists as post-MVP, which doesn't exist yet."""

    def __init__(self, audit: AuditLogService) -> None:
        self.audit = audit

    def cancel(self, session: Session, package_id: UUID, admin: AdminUser) -> Package:
        package = session.get(Package, package_id)
        if package is None:
            raise PackageError("package_not_found")
        if package.status == PackageStatus.CANCELLED:
            return package
        package.status = PackageStatus.CANCELLED
        session.add(package)
        self.audit.record(
            session,
            AuditEventType.ADMIN_ACTION,
            AuditOutcome.PACKAGE_CANCELLED_BY_ADMIN,
            user_id=package.user_id,
            reference=str(package.id),
            details=f"cancelled_by_admin={admin.id}",
        )
        session.commit()
        session.refresh(package)
        return package
