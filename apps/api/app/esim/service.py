from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlmodel import Session, col, select

from app.auth.models import (
    Manifest,
    ManifestOrder,
    ManifestPilgrim,
    Organization,
    Platform,
    PricingTier,
    User,
)
from app.config import Settings
from app.esim.models import (
    DeviceCompatibilityEvent,
    DeviceCompatibilityLog,
    EsimAggregator,
    EsimIssuanceJob,
    EsimProfile,
    EsimProfileStatus,
)
from app.esim.providers import (
    EsimIssueRequest,
    EsimProvider,
    EsimProviderError,
    EsimProviderPending,
)
from app.esim.schemas import DeviceCompatibilityCreate, HtoPilgrimSummary
from app.notifications.service import NotificationError, NotificationService
from app.packages.models import Package, PackageStatus


class EsimError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class EsimIssuanceScheduler(Protocol):
    def schedule(self, package_id: UUID, countdown: int) -> None: ...


class NoopEsimIssuanceScheduler:
    def schedule(self, package_id: UUID, countdown: int) -> None:
        del package_id, countdown


class EsimProfileService:
    RETRY_DELAYS = (60, 300)

    def __init__(
        self,
        settings: Settings,
        providers: Mapping[str, EsimProvider],
        scheduler: EsimIssuanceScheduler,
        notifications: NotificationService,
        clock: Callable[[], datetime],
    ) -> None:
        self.settings = settings
        self.providers = providers
        self.scheduler = scheduler
        self.notifications = notifications
        self.clock = clock

    def issue(self, session: Session, user: User, package_id: UUID) -> EsimProfile:
        # The package row is the concurrency lock. PostgreSQL holds it until
        # commit, so two simultaneous taps cannot both call an aggregator.
        package = session.exec(
            select(Package)
            .where(Package.id == package_id, Package.user_id == user.id)
            .with_for_update()
        ).first()
        if package is None:
            raise EsimError("package_not_found")
        if package.status != PackageStatus.ACTIVE:
            raise EsimError("package_not_active")
        existing = session.exec(
            select(EsimProfile).where(EsimProfile.package_id == package.id)
        ).first()
        if existing is not None:
            job = session.exec(
                select(EsimIssuanceJob).where(EsimIssuanceJob.package_id == package.id)
            ).first()
            if job is not None and job.success_notified_at is None:
                self._notify_success(session, user, existing, job)
            return existing

        request = EsimIssueRequest(
            package_id=package.id,
            user_id=user.id,
            data_gb=package.data_gb_total,
            destination_country=package.destination_country,
        )
        last_error = "No eSIM vendor is configured"
        for vendor_name in self._vendor_order():
            provider = self.providers.get(vendor_name)
            if provider is None:
                last_error = f"{vendor_name} is not configured"
                self._log_attempt(session, user.id, vendor_name, False, last_error)
                continue
            try:
                issued = provider.issue(request)
            except EsimProviderPending as exc:
                last_error = str(exc)
                self._log_attempt(session, user.id, vendor_name, False, last_error)
                # Accepted-but-pending is not an issuance failure. Do not
                # cascade and buy a duplicate profile from another supplier.
                break
            except EsimProviderError as exc:
                last_error = str(exc)
                self._log_attempt(session, user.id, vendor_name, False, last_error)
                continue
            self._log_attempt(session, user.id, vendor_name, True, None)
            profile = EsimProfile(
                package_id=package.id,
                aggregator=EsimAggregator(vendor_name),
                iccid=issued.iccid,
                activation_code_lpa=issued.activation_code_lpa,
                qr_code_url=issued.qr_code_url,
            )
            session.add(profile)
            job = session.exec(
                select(EsimIssuanceJob).where(EsimIssuanceJob.package_id == package.id)
            ).first()
            if job is None:
                job = EsimIssuanceJob(package_id=package.id)
            job.completed_at = self.clock()
            job.next_attempt_at = None
            job.last_error = None
            session.add(job)
            session.commit()
            session.refresh(profile)
            self._notify_success(session, user, profile, job)
            return profile

        self._record_failure(session, package.id, last_error)
        raise EsimError("aggregator_unavailable")

    def get(self, session: Session, user: User, package_id: UUID) -> EsimProfile:
        profile = session.exec(
            select(EsimProfile)
            .join(Package, col(Package.id) == col(EsimProfile.package_id))
            .where(EsimProfile.package_id == package_id, Package.user_id == user.id)
        ).first()
        if profile is None:
            package = session.exec(
                select(Package).where(
                    Package.id == package_id, Package.user_id == user.id
                )
            ).first()
            raise EsimError(
                "esim_profile_not_found" if package is not None else "package_not_found"
            )
        return profile

    def mark_downloaded(
        self, session: Session, user: User, package_id: UUID
    ) -> EsimProfile:
        profile = self.get(session, user, package_id)
        if profile.status == EsimProfileStatus.ISSUED:
            profile.status = EsimProfileStatus.DOWNLOADED
            profile.downloaded_at = self.clock()
            session.add(profile)
            session.commit()
            session.refresh(profile)
        return profile

    def mark_activated(
        self, session: Session, user: User, package_id: UUID
    ) -> EsimProfile:
        profile = self.get(session, user, package_id)
        if profile.status != EsimProfileStatus.ACTIVATED:
            profile.status = EsimProfileStatus.ACTIVATED
            profile.activated_at = self.clock()
            session.add(profile)
            session.commit()
            session.refresh(profile)
        return profile

    def _vendor_order(self) -> tuple[str, str, str]:
        return (
            str(self.settings.esim_vendor_primary),
            str(self.settings.esim_vendor_secondary),
            str(self.settings.esim_vendor_tertiary),
        )

    def _log_attempt(
        self,
        session: Session,
        user_id: UUID,
        vendor_name: str,
        succeeded: bool,
        failure_reason: str | None,
    ) -> None:
        session.add(
            DeviceCompatibilityLog(
                user_id=user_id,
                event_type=DeviceCompatibilityEvent.ISSUANCE_ATTEMPT,
                aggregator=EsimAggregator(vendor_name),
                attempt_succeeded=succeeded,
                failure_reason=(failure_reason or "")[:255] or None,
                checked_at=self.clock(),
            )
        )

    def _record_failure(
        self, session: Session, package_id: UUID, last_error: str
    ) -> None:
        job = session.exec(
            select(EsimIssuanceJob)
            .where(EsimIssuanceJob.package_id == package_id)
            .with_for_update()
        ).first()
        if job is None:
            job = EsimIssuanceJob(package_id=package_id)
        job.attempt_count += 1
        job.last_error = last_error[:255]
        if job.attempt_count >= 3:
            job.admin_queued_at = job.admin_queued_at or self.clock()
            job.next_attempt_at = None
        else:
            delay = self.RETRY_DELAYS[job.attempt_count - 1]
            job.next_attempt_at = self.clock() + timedelta(seconds=delay)
        session.add(job)
        session.commit()
        if job.attempt_count < 3:
            try:
                self.scheduler.schedule(
                    package_id, self.RETRY_DELAYS[job.attempt_count - 1]
                )
            except Exception:
                # Retain next_attempt_at; the periodic scanner will enqueue it
                # when the broker recovers.
                return
            job.next_attempt_at = None
            session.add(job)
            session.commit()

    def _notify_success(
        self,
        session: Session,
        user: User,
        profile: EsimProfile,
        job: EsimIssuanceJob | None,
    ) -> None:
        # Email-first accounts may not have linked a service phone yet. The
        # profile remains available through the authenticated API; there is no
        # WhatsApp destination to notify and no reason to retry provisioning.
        if user.phone_number is None:
            return
        try:
            self.notifications.send_esim_ready(
                user.phone_number, profile.qr_code_url, user.locale.value
            )
        except NotificationError:
            if job is not None:
                job.next_attempt_at = self.clock() + timedelta(seconds=60)
                session.add(job)
                session.commit()
            return
        if job is not None:
            job.success_notified_at = self.clock()
            job.next_attempt_at = None
            session.add(job)
            session.commit()


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
            event_type=DeviceCompatibilityEvent.COMPATIBILITY_CHECK,
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
            # row and nothing to flag. Ordered by id for a deterministic
            # pick in the rare case a user is linked to more than one
            # pilgrim row (e.g. re-added on a different manifest).
            pilgrim = session.exec(
                select(ManifestPilgrim)
                .where(col(ManifestPilgrim.user_id) == user.id)
                .order_by(col(ManifestPilgrim.id))
            ).first()
            if pilgrim is not None:
                pilgrim.esim_incompatible_flag = True
                session.add(pilgrim)
        session.commit()
        session.refresh(entry)
        return entry

    def list_checks(
        self,
        session: Session,
        platform: Platform | None,
        esim_supported: bool | None,
    ) -> list[DeviceCompatibilityLog]:
        # Scoped to compatibility_check rows only (api-spec.md §7.10's
        # "known incompatible devices" list purpose) -- issuance_attempt
        # rows (_log_attempt above) share this table but populate a
        # disjoint set of fields (aggregator/attempt_succeeded, no
        # device_model/platform/esim_supported), so mixing both event
        # types into one admin table would produce rows that don't share
        # a consistent column meaning.
        query = select(DeviceCompatibilityLog).where(
            DeviceCompatibilityLog.event_type
            == DeviceCompatibilityEvent.COMPATIBILITY_CHECK
        )
        if platform is not None:
            query = query.where(DeviceCompatibilityLog.platform == platform)
        if esim_supported is not None:
            query = query.where(DeviceCompatibilityLog.esim_supported == esim_supported)
        return list(
            session.exec(
                query.order_by(col(DeviceCompatibilityLog.checked_at).desc())
            ).all()
        )


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

        manifest_ids = {p.manifest_id for p in pilgrims}
        manifest_names: dict[UUID, str | None] = {
            manifest.id: manifest.name
            for manifest in session.exec(
                select(Manifest).where(col(Manifest.id).in_(manifest_ids))
            ).all()
        }

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

        user_ids = {p.user_id for p in pilgrims if p.user_id is not None}
        esim_statuses: dict[UUID, str] = {}
        if user_ids:
            profiles = session.exec(
                select(EsimProfile)
                .join(Package, col(Package.id) == col(EsimProfile.package_id))
                .where(col(Package.user_id).in_(user_ids))
            ).all()
            package_users = {
                package.id: package.user_id
                for package in session.exec(
                    select(Package).where(col(Package.user_id).in_(user_ids))
                ).all()
            }
            rank = {"issued": 1, "downloaded": 2, "activated": 3}
            for profile in profiles:
                user_id = package_users.get(profile.package_id)
                if user_id is None:
                    continue
                candidate = profile.status.value
                if rank[candidate] > rank.get(esim_statuses.get(user_id, ""), 0):
                    esim_statuses[user_id] = candidate

        return [
            HtoPilgrimSummary(
                id=pilgrim.id,
                name=f"{pilgrim.first_name} {pilgrim.last_name}".strip(),
                manifest_id=pilgrim.manifest_id,
                manifest_name=manifest_names.get(pilgrim.manifest_id),
                phone_number=pilgrim.phone_number,
                tier=(
                    tier_names.get(pilgrim.manifest_order_id)
                    if pilgrim.manifest_order_id
                    else None
                ),
                esim_status=(
                    "incompatible"
                    if pilgrim.esim_incompatible_flag
                    else (
                        esim_statuses.get(pilgrim.user_id, "not_checked")
                        if pilgrim.user_id is not None
                        else "not_checked"
                    )
                ),
                activation_status=(
                    "activated" if pilgrim.user_id is not None else "not_activated"
                ),
            )
            for pilgrim in pilgrims
        ]
