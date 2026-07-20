import csv
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from io import StringIO
from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.auth.models import (
    Manifest,
    ManifestOrder,
    ManifestOrderStatus,
    ManifestPilgrim,
    Organization,
    PricingTier,
)
from app.checkins.models import CheckIn
from app.esim.models import EsimProfile
from app.packages.models import Package
from app.sos.models import SOSAlert

CSV_HEADER = (
    "name",
    "phone",
    "tier",
    "purchase_date",
    "esim_status",
    "check_in_count",
    "sos_events",
)

_ESIM_STATUS_RANK = {"issued": 1, "downloaded": 2, "activated": 3}

# Pilgrim names/phone numbers originate from an HTO-uploaded manifest CSV --
# untrusted input -- and this report is meant to be opened in Excel/Sheets
# by an HTO operator or NAHCON auditor. A value starting with =, +, -, or @
# is interpreted as a formula by spreadsheet software (CSV/formula
# injection, OWASP). Prefixing with a single quote defuses it the same way
# spreadsheet apps themselves do for a manually-typed leading apostrophe,
# without changing the visible text.
_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@")


def _csv_safe(value: str) -> str:
    if value.startswith(_FORMULA_TRIGGER_CHARS):
        return f"'{value}"
    return value


@dataclass(frozen=True)
class ProvisioningReportRow:
    name: str
    phone_number: str
    tier: str | None
    purchase_date: date | None
    esim_status: str
    check_in_count: int
    sos_event_count: int


class ProvisioningReportService:
    """AC-20.1-20.4 (prd.md US-20): a per-pilgrim CSV export for an HTO
    operator's own records and NAHCON compliance.

    Scope decision (no per-screen spec existed for this report before --
    see frontend-dashboard.md Screen 12 gap flagged in the PR): a row only
    appears once its `manifest_order` has reached
    `ManifestOrderStatus.PROVISIONED` -- data-model.md §6.14 defines that
    status as "every selected pilgrim has a delivered activation link,"
    i.e. genuinely provisioned, not merely ordered or paid. "Purchase
    date" is `manifest_orders.payment_confirmed_at`, the only per-pilgrim
    date this report has, and AC-20.3's date-range filter applies to it.

    Cross-tenant isolation follows the same pattern as
    HtoPilgrimService.list_pilgrims (app/esim/service.py): scoped at the
    query level via `Manifest.organization_id`, never at the response or
    UI layer.
    """

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self.clock = clock

    def generate_rows(
        self,
        session: Session,
        organization: Organization,
        manifest_id: UUID | None,
        date_from: date | None,
        date_to: date | None,
    ) -> list[ProvisioningReportRow]:
        query = (
            select(ManifestPilgrim, ManifestOrder, PricingTier)
            .join(Manifest, col(ManifestPilgrim.manifest_id) == col(Manifest.id))
            .join(
                ManifestOrder,
                col(ManifestPilgrim.manifest_order_id) == col(ManifestOrder.id),
            )
            .join(
                PricingTier, col(ManifestOrder.pricing_tier_id) == col(PricingTier.id)
            )
            .where(
                col(Manifest.organization_id) == organization.id,
                ManifestOrder.status == ManifestOrderStatus.PROVISIONED,
            )
        )
        if manifest_id is not None:
            query = query.where(col(ManifestPilgrim.manifest_id) == manifest_id)
        if date_from is not None:
            query = query.where(
                func.date(col(ManifestOrder.payment_confirmed_at)) >= date_from
            )
        if date_to is not None:
            query = query.where(
                func.date(col(ManifestOrder.payment_confirmed_at)) <= date_to
            )
        rows = session.exec(
            query.order_by(
                col(ManifestPilgrim.last_name), col(ManifestPilgrim.first_name)
            )
        ).all()

        user_ids = {
            pilgrim.user_id for pilgrim, _, _ in rows if pilgrim.user_id is not None
        }
        checkin_counts: dict[UUID, int] = {}
        sos_counts: dict[UUID, int] = {}
        esim_statuses: dict[UUID, str] = {}
        if user_ids:
            checkin_counts = {
                user_id: count
                for user_id, count in session.exec(
                    select(CheckIn.user_id, func.count())
                    .where(col(CheckIn.user_id).in_(user_ids))
                    .group_by(col(CheckIn.user_id))
                ).all()
                if user_id is not None
            }
            sos_counts = {
                user_id: count
                for user_id, count in session.exec(
                    select(SOSAlert.user_id, func.count())
                    .where(col(SOSAlert.user_id).in_(user_ids))
                    .group_by(col(SOSAlert.user_id))
                ).all()
                if user_id is not None
            }
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
            for profile in profiles:
                user_id = package_users.get(profile.package_id)
                if user_id is None:
                    continue
                candidate = profile.status.value
                if _ESIM_STATUS_RANK[candidate] > _ESIM_STATUS_RANK.get(
                    esim_statuses.get(user_id, ""), 0
                ):
                    esim_statuses[user_id] = candidate

        result: list[ProvisioningReportRow] = []
        for pilgrim, order, tier in rows:
            esim_status = (
                "incompatible"
                if pilgrim.esim_incompatible_flag
                else (
                    esim_statuses.get(pilgrim.user_id, "not_checked")
                    if pilgrim.user_id is not None
                    else "not_checked"
                )
            )
            purchase_date = (
                order.payment_confirmed_at.date()
                if order.payment_confirmed_at is not None
                else None
            )
            result.append(
                ProvisioningReportRow(
                    name=f"{pilgrim.first_name} {pilgrim.last_name}".strip(),
                    phone_number=pilgrim.phone_number,
                    tier=tier.name,
                    purchase_date=purchase_date,
                    esim_status=esim_status,
                    check_in_count=(
                        checkin_counts.get(pilgrim.user_id, 0)
                        if pilgrim.user_id is not None
                        else 0
                    ),
                    sos_event_count=(
                        sos_counts.get(pilgrim.user_id, 0)
                        if pilgrim.user_id is not None
                        else 0
                    ),
                )
            )
        return result

    def generate_csv(
        self,
        session: Session,
        organization: Organization,
        manifest_id: UUID | None,
        date_from: date | None,
        date_to: date | None,
    ) -> str:
        rows = self.generate_rows(
            session, organization, manifest_id, date_from, date_to
        )
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(CSV_HEADER)
        for row in rows:
            writer.writerow(
                [
                    _csv_safe(row.name),
                    # Not guarded: a pilgrim only reaches this report via a
                    # PROVISIONED manifest_order, which only ever accepts
                    # ManifestValidationStatus.VALID/DUPLICATE_WARNING rows
                    # (app/manifests/orders.py ACCEPTED_VALIDATION_STATUSES)
                    # -- phone_number is always the validated E.164 form
                    # here, always starting with the digit-safe "+", so
                    # guarding it would prefix every single legitimate row
                    # for no real protection.
                    row.phone_number,
                    _csv_safe(row.tier or ""),
                    row.purchase_date.isoformat() if row.purchase_date else "",
                    row.esim_status,
                    row.check_in_count,
                    row.sos_event_count,
                ]
            )
        return buffer.getvalue()
