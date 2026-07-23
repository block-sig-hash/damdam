from __future__ import annotations

import secrets
import string
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol
from urllib.parse import urlencode
from uuid import UUID, uuid4

from sqlalchemy import func, or_
from sqlmodel import Session, col, select

from app.auth.models import (
    AdminUser,
    Manifest,
    ManifestOrder,
    ManifestOrderStatus,
    ManifestPilgrim,
    ManifestStatus,
    ManifestValidationStatus,
    Organization,
    PricingTier,
    PricingTierPriceChange,
)
from app.config import Settings
from app.manifests.invoices import (
    InvoiceDetails,
    InvoicePDFGenerator,
    InvoiceStorage,
    InvoiceStorageError,
)
from app.manifests.schemas import (
    AdminManifestOrderSummary,
    ManifestOrderDetailResponse,
    ManifestOrderResponse,
    ManifestOrderSummary,
    PricingTierResponse,
    UnorderedPilgrim,
)
from app.manifests.service import ManifestError
from app.notifications.service import NotificationError, NotificationService
from app.packages.models import PaymentMethod, Transaction, TransactionStatus

ACCEPTED_VALIDATION_STATUSES = (
    ManifestValidationStatus.VALID,
    ManifestValidationStatus.DUPLICATE_WARNING,
)
MONEY = Decimal("0.01")
ACTIVATION_ALPHABET = string.ascii_uppercase + string.digits


class ProvisioningScheduler(Protocol):
    def schedule(self, order_id: UUID) -> None: ...


class ManifestOrderService:
    def __init__(
        self,
        settings: Settings,
        notifications: NotificationService,
        invoice_storage: InvoiceStorage,
        scheduler: ProvisioningScheduler,
        clock: Callable[[], datetime],
        pdf_generator: InvoicePDFGenerator | None = None,
    ) -> None:
        self.settings = settings
        self.notifications = notifications
        self.invoice_storage = invoice_storage
        self.scheduler = scheduler
        self.clock = clock
        self.pdf_generator = pdf_generator or InvoicePDFGenerator()

    def list_pricing(
        self, session: Session, destination_country: str | None = None
    ) -> list[PricingTierResponse]:
        statement = select(PricingTier).where(col(PricingTier.active).is_(True))
        if destination_country is not None:
            statement = statement.where(
                PricingTier.destination_country == destination_country
            )
        tiers = session.exec(statement.order_by(col(PricingTier.name))).all()
        result: list[PricingTierResponse] = []
        for tier in tiers:
            retail = self._latest_price(tier)
            wholesale = self._wholesale_price(tier, retail)
            result.append(
                PricingTierResponse(
                    id=tier.id,
                    name=tier.name,
                    retail_price_ngn=float(retail),
                    wholesale_price_ngn=float(wholesale),
                    estimated_margin_ngn=float(retail - wholesale),
                    is_group_tier=tier.is_group_tier,
                    min_group_size=tier.min_group_size,
                    max_group_size=tier.max_group_size,
                )
            )
        return result

    def list_admin_pricing_tiers(
        self, session: Session, destination_country: str | None = None
    ) -> list[PricingTier]:
        statement = select(PricingTier).where(col(PricingTier.active).is_(True))
        if destination_country is not None:
            statement = statement.where(
                PricingTier.destination_country == destination_country
            )
        return list(session.exec(statement.order_by(col(PricingTier.name))).all())

    def update_tier_price(
        self,
        session: Session,
        tier_id: UUID,
        new_ngn_price: Decimal,
        admin: AdminUser,
    ) -> tuple[PricingTier, PricingTierPriceChange]:
        tier = session.get(PricingTier, tier_id)
        if tier is None:
            raise ManifestError("pricing_tier_not_found")
        change = PricingTierPriceChange(
            pricing_tier_id=tier.id,
            admin_id=admin.id,
            old_ngn_price=tier.ngn_price,
            new_ngn_price=new_ngn_price,
            changed_at=self.clock(),
        )
        tier.ngn_price = new_ngn_price
        session.add(tier)
        session.add(change)
        session.commit()
        session.refresh(tier)
        session.refresh(change)
        return tier, change

    def list_unordered(
        self, session: Session, organization_id: UUID, manifest_id: UUID
    ) -> list[UnorderedPilgrim]:
        self._owned_orderable_manifest(session, organization_id, manifest_id)
        rows = session.exec(
            select(ManifestPilgrim)
            .where(
                ManifestPilgrim.manifest_id == manifest_id,
                col(ManifestPilgrim.manifest_order_id).is_(None),
                col(ManifestPilgrim.validation_status).in_(
                    ACCEPTED_VALIDATION_STATUSES
                ),
            )
            .order_by(col(ManifestPilgrim.row_number))
        ).all()
        return [
            UnorderedPilgrim(
                id=row.id,
                name=f"{row.first_name} {row.last_name}",
                phone_number=row.phone_number,
                family_group_id=row.family_group_id,
            )
            for row in rows
        ]

    def create_group(
        self,
        session: Session,
        organization_id: UUID,
        manifest_id: UUID,
        pilgrim_ids: list[UUID],
        group_size: int,
    ) -> UUID:
        rows = self._selected_unordered_rows(
            session, organization_id, manifest_id, pilgrim_ids
        )
        if any(row.family_group_id is not None for row in rows):
            raise ManifestError("pilgrims_already_grouped")
        self._validate_group_size(session, rows, group_size)
        group_id = uuid4()
        for row in rows:
            row.family_group_id = group_id
            session.add(row)
        session.commit()
        return group_id

    def update_group(
        self,
        session: Session,
        organization_id: UUID,
        manifest_id: UUID,
        group_id: UUID,
        pilgrim_ids: list[UUID],
        group_size: int,
    ) -> UUID:
        self._owned_orderable_manifest(session, organization_id, manifest_id)
        current = list(
            session.exec(
                select(ManifestPilgrim)
                .where(
                    ManifestPilgrim.manifest_id == manifest_id,
                    ManifestPilgrim.family_group_id == group_id,
                    col(ManifestPilgrim.manifest_order_id).is_(None),
                )
                .with_for_update()
            ).all()
        )
        if not current:
            raise ManifestError("family_group_not_found")
        selected = self._selected_unordered_rows(
            session, organization_id, manifest_id, pilgrim_ids
        )
        if any(
            row.family_group_id not in (None, group_id) for row in selected
        ):
            raise ManifestError("pilgrims_already_grouped")
        self._validate_group_size(session, selected, group_size)
        for row in current:
            row.family_group_id = None
            session.add(row)
        for row in selected:
            row.family_group_id = group_id
            session.add(row)
        session.commit()
        return group_id

    def delete_group(
        self,
        session: Session,
        organization_id: UUID,
        manifest_id: UUID,
        group_id: UUID,
    ) -> None:
        self._owned_orderable_manifest(session, organization_id, manifest_id)
        rows = session.exec(
            select(ManifestPilgrim).where(
                ManifestPilgrim.manifest_id == manifest_id,
                ManifestPilgrim.family_group_id == group_id,
                col(ManifestPilgrim.manifest_order_id).is_(None),
            ).with_for_update()
        ).all()
        if not rows:
            raise ManifestError("family_group_not_found")
        for row in rows:
            row.family_group_id = None
            session.add(row)
        session.commit()

    def place_order(
        self,
        session: Session,
        organization_id: UUID,
        manifest_id: UUID,
        pricing_tier_id: UUID,
        pilgrim_ids: list[UUID],
    ) -> ManifestOrderResponse:
        manifest = self._owned_orderable_manifest(
            session, organization_id, manifest_id
        )
        organization = session.get(Organization, organization_id)
        assert organization is not None
        tier = session.get(PricingTier, pricing_tier_id)
        if tier is None or not tier.active:
            raise ManifestError("pricing_tier_not_found")
        if not pilgrim_ids or len(set(pilgrim_ids)) != len(pilgrim_ids):
            raise ManifestError("invalid_pilgrim_selection")
        rows = list(
            session.exec(
                select(ManifestPilgrim)
                .where(
                    ManifestPilgrim.manifest_id == manifest_id,
                    col(ManifestPilgrim.id).in_(pilgrim_ids),
                    col(ManifestPilgrim.validation_status).in_(
                        ACCEPTED_VALIDATION_STATUSES
                    ),
                )
                .with_for_update()
            ).all()
        )
        if len(rows) != len(pilgrim_ids):
            raise ManifestError("invalid_pilgrim_selection")

        existing_ids = {row.manifest_order_id for row in rows}
        if existing_ids != {None}:
            existing = self._resumable_order(
                session, existing_ids, tier.id, rows, pilgrim_ids
            )
            if existing is None:
                ordered = [row.id for row in rows if row.manifest_order_id]
                raise ManifestError(
                    "pilgrims_already_ordered", {"pilgrim_ids": ordered}
                )
            return self._finalize_invoice(
                session, existing, manifest, organization, tier
            )

        self._validate_order_selection(session, manifest_id, tier, rows)
        retail = self._latest_price(tier)
        wholesale = self._wholesale_price(tier, retail)
        order = ManifestOrder(
            id=uuid4(),
            manifest_id=manifest.id,
            pricing_tier_id=tier.id,
            pilgrim_count=len(rows),
            wholesale_price_ngn=wholesale,
            total_ngn=(wholesale * len(rows)).quantize(MONEY),
            created_at=self.clock(),
        )
        session.add(order)
        session.flush()
        for row in rows:
            row.manifest_order_id = order.id
            session.add(row)
        session.flush()
        unordered_count = session.exec(
            select(func.count())
            .select_from(ManifestPilgrim)
            .where(
                ManifestPilgrim.manifest_id == manifest.id,
                col(ManifestPilgrim.manifest_order_id).is_(None),
                col(ManifestPilgrim.validation_status).in_(
                    ACCEPTED_VALIDATION_STATUSES
                ),
            )
        ).one()
        manifest.status = (
            ManifestStatus.PROVISIONED
            if unordered_count == 0
            else ManifestStatus.PARTIALLY_ORDERED
        )
        session.add(manifest)
        session.commit()
        session.refresh(order)
        return self._finalize_invoice(
            session, order, manifest, organization, tier
        )

    def get_order(
        self,
        session: Session,
        organization_id: UUID,
        manifest_id: UUID,
        order_id: UUID,
    ) -> ManifestOrderDetailResponse:
        order, tier = self._owned_order(
            session, organization_id, manifest_id, order_id
        )
        return ManifestOrderDetailResponse(
            id=order.id,
            tier_name=tier.name,
            pilgrim_count=order.pilgrim_count,
            wholesale_price_ngn=float(order.wholesale_price_ngn),
            total_ngn=float(order.total_ngn),
            status=order.status,
            invoice_url=order.invoice_url or "",
            payment_confirmed_at=order.payment_confirmed_at,
        )

    def list_orders(
        self, session: Session, organization_id: UUID, manifest_id: UUID
    ) -> list[ManifestOrderSummary]:
        self._owned_orderable_manifest(session, organization_id, manifest_id)
        records = session.exec(
            select(ManifestOrder, PricingTier)
            .join(PricingTier, col(PricingTier.id) == ManifestOrder.pricing_tier_id)
            .where(ManifestOrder.manifest_id == manifest_id)
            .order_by(col(ManifestOrder.created_at).desc())
        ).all()
        return [
            ManifestOrderSummary(
                id=order.id,
                tier_name=tier.name,
                pilgrim_count=order.pilgrim_count,
                total_ngn=float(order.total_ngn),
                status=order.status,
            )
            for order, tier in records
        ]

    def get_invoice(
        self,
        session: Session,
        organization_id: UUID,
        manifest_id: UUID,
        order_id: UUID,
    ) -> bytes:
        order, _ = self._owned_order(
            session, organization_id, manifest_id, order_id
        )
        if order.invoice_object_key is None:
            raise ManifestError("invoice_unavailable")
        try:
            return self.invoice_storage.get(order.invoice_object_key)
        except InvoiceStorageError as exc:
            raise ManifestError("invoice_unavailable") from exc

    def get_admin_invoice(self, session: Session, order_id: UUID) -> bytes:
        order = session.get(ManifestOrder, order_id)
        if order is None:
            raise ManifestError("manifest_order_not_found")
        if order.invoice_object_key is None:
            raise ManifestError("invoice_unavailable")
        try:
            return self.invoice_storage.get(order.invoice_object_key)
        except InvoiceStorageError as exc:
            raise ManifestError("invoice_unavailable") from exc

    def list_admin_orders(
        self,
        session: Session,
        status: ManifestOrderStatus,
        search: str | None,
    ) -> list[AdminManifestOrderSummary]:
        statement = (
            select(ManifestOrder, Manifest, Organization)
            .join(Manifest, col(Manifest.id) == ManifestOrder.manifest_id)
            .join(Organization, col(Organization.id) == Manifest.organization_id)
        )
        if status == ManifestOrderStatus.AWAITING_PAYMENT:
            statement = statement.where(
                or_(
                    col(ManifestOrder.status) == status,
                    (
                        (
                            col(ManifestOrder.status)
                            == ManifestOrderStatus.PROVISIONING
                        )
                        & col(ManifestOrder.provisioning_enqueued_at).is_(None)
                    ),
                )
            )
        else:
            statement = statement.where(col(ManifestOrder.status) == status)
        if search:
            statement = statement.where(
                col(Organization.name).ilike(f"%{search.strip()}%")
            )
        now = self.clock()
        result: list[AdminManifestOrderSummary] = []
        for order, manifest, organization in session.exec(
            statement.order_by(col(ManifestOrder.created_at))
        ).all():
            created_at = order.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            result.append(
                AdminManifestOrderSummary(
                    id=order.id,
                    hto_business_name=organization.name,
                    manifest_name=manifest.name,
                    pilgrim_count=order.pilgrim_count,
                    total_ngn=float(order.total_ngn),
                    invoice_url=order.invoice_url or "",
                    days_pending=max(0, (now - created_at).days),
                )
            )
        return result

    def confirm_payment(
        self, session: Session, order_id: UUID, admin: AdminUser
    ) -> ManifestOrder:
        order = session.exec(
            select(ManifestOrder)
            .where(ManifestOrder.id == order_id)
            .with_for_update()
        ).first()
        if order is None:
            raise ManifestError("manifest_order_not_found")
        if order.status == ManifestOrderStatus.AWAITING_PAYMENT:
            confirmed_at = self.clock()
            order.status = ManifestOrderStatus.PROVISIONING
            order.payment_confirmed_at = confirmed_at
            order.payment_confirmed_by = admin.id
            session.add(order)
        elif order.status not in (
            ManifestOrderStatus.PROVISIONING,
            ManifestOrderStatus.PROVISIONED,
        ):
            raise ManifestError("invalid_payment_transition")

        transaction = session.exec(
            select(Transaction).where(Transaction.manifest_order_id == order.id)
        ).first()
        if transaction is None:
            confirmed_at = order.payment_confirmed_at or self.clock()
            confirmed_by = order.payment_confirmed_by or admin.id
            transaction = Transaction(
                manifest_order_id=order.id,
                processor=None,
                processor_reference=f"hto-{order.id}",
                amount_ngn=order.total_ngn,
                payment_method=PaymentMethod.INVOICE,
                status=TransactionStatus.SUCCESS,
                webhook_payload={
                    "confirmation_source": "admin",
                    "confirmed_by_admin_id": str(confirmed_by),
                    "confirmed_at": confirmed_at.isoformat(),
                },
                created_at=confirmed_at,
            )
            session.add(transaction)
        session.commit()
        session.refresh(order)

        if (
            order.status == ManifestOrderStatus.PROVISIONING
            and order.provisioning_enqueued_at is None
        ):
            try:
                self.scheduler.schedule(order.id)
            except Exception as exc:
                raise ManifestError("provisioning_unavailable") from exc
            order.provisioning_enqueued_at = self.clock()
            session.add(order)
            session.commit()
            session.refresh(order)
        return order

    def provision(self, session: Session, order_id: UUID) -> ManifestOrder:
        order = session.exec(
            select(ManifestOrder)
            .where(ManifestOrder.id == order_id)
            .with_for_update()
        ).first()
        if order is None:
            raise ManifestError("manifest_order_not_found")
        if order.status == ManifestOrderStatus.PROVISIONED:
            return order
        if order.status != ManifestOrderStatus.PROVISIONING:
            raise ManifestError("payment_not_confirmed")
        tier = session.get(PricingTier, order.pricing_tier_id)
        assert tier is not None
        rows = session.exec(
            select(ManifestPilgrim)
            .where(ManifestPilgrim.manifest_order_id == order.id)
            .order_by(col(ManifestPilgrim.row_number))
        ).all()
        now = self.clock()
        for row in rows:
            if row.activation_code is None:
                row.activation_code = self._activation_code(session)
                row.activation_code_expires_at = now + timedelta(days=30)
                session.add(row)
        session.commit()
        for row_id in (row.id for row in rows):
            row = session.exec(
                select(ManifestPilgrim)
                .where(ManifestPilgrim.id == row_id)
                .with_for_update()
            ).one()
            if row.activation_link_sent_at is not None:
                session.rollback()
                continue
            query = urlencode({"code": row.activation_code})
            url = f"{self.settings.activation_base_url}?{query}"
            self.notifications.send_activation(
                row.phone_number,
                f"{row.first_name} {row.last_name}",
                tier.name,
                url,
            )
            row.activation_link_sent_at = self.clock()
            session.add(row)
            session.commit()
        order = session.exec(
            select(ManifestOrder)
            .where(ManifestOrder.id == order_id)
            .with_for_update()
        ).one()
        unsent_count = session.exec(
            select(func.count())
            .select_from(ManifestPilgrim)
            .where(
                ManifestPilgrim.manifest_order_id == order.id,
                col(ManifestPilgrim.activation_link_sent_at).is_(None),
            )
        ).one()
        if unsent_count:
            raise ManifestError("activation_delivery_incomplete")
        order.status = ManifestOrderStatus.PROVISIONED
        session.add(order)
        session.commit()
        session.refresh(order)
        return order

    def _owned_orderable_manifest(
        self, session: Session, organization_id: UUID, manifest_id: UUID
    ) -> Manifest:
        manifest = session.exec(
            select(Manifest).where(
                Manifest.id == manifest_id,
                Manifest.organization_id == organization_id,
            )
        ).first()
        if manifest is None:
            raise ManifestError("manifest_not_found")
        if manifest.status == ManifestStatus.DRAFT:
            raise ManifestError("manifest_not_confirmed")
        return manifest

    def _selected_unordered_rows(
        self,
        session: Session,
        organization_id: UUID,
        manifest_id: UUID,
        pilgrim_ids: list[UUID],
    ) -> list[ManifestPilgrim]:
        self._owned_orderable_manifest(session, organization_id, manifest_id)
        if len(set(pilgrim_ids)) != len(pilgrim_ids):
            raise ManifestError("invalid_pilgrim_selection")
        rows = list(
            session.exec(
                select(ManifestPilgrim)
                .where(
                    ManifestPilgrim.manifest_id == manifest_id,
                    col(ManifestPilgrim.id).in_(pilgrim_ids),
                    col(ManifestPilgrim.manifest_order_id).is_(None),
                    col(ManifestPilgrim.validation_status).in_(
                        ACCEPTED_VALIDATION_STATUSES
                    ),
                )
                .with_for_update()
            ).all()
        )
        if len(rows) != len(pilgrim_ids):
            raise ManifestError("invalid_pilgrim_selection")
        return rows

    def _group_tier(self, session: Session) -> PricingTier:
        tier = session.exec(
            select(PricingTier).where(
                col(PricingTier.active).is_(True),
                col(PricingTier.is_group_tier).is_(True),
            )
        ).first()
        if tier is None:
            raise ManifestError("pricing_unavailable")
        return tier

    def _validate_group_size(
        self, session: Session, rows: list[ManifestPilgrim], group_size: int
    ) -> None:
        tier = self._group_tier(session)
        if (
            group_size != len(rows)
            or tier.min_group_size is None
            or tier.max_group_size is None
            or not tier.min_group_size <= group_size <= tier.max_group_size
        ):
            raise ManifestError("invalid_family_group_size")

    def _validate_order_selection(
        self,
        session: Session,
        manifest_id: UUID,
        tier: PricingTier,
        rows: list[ManifestPilgrim],
    ) -> None:
        group_ids = {row.family_group_id for row in rows}
        if tier.is_group_tier:
            if len(group_ids) != 1 or None in group_ids:
                raise ManifestError("family_group_required")
            group_id = next(iter(group_ids))
            full_group = session.exec(
                select(ManifestPilgrim).where(
                    ManifestPilgrim.manifest_id == manifest_id,
                    ManifestPilgrim.family_group_id == group_id,
                    col(ManifestPilgrim.manifest_order_id).is_(None),
                )
            ).all()
            if {row.id for row in full_group} != {row.id for row in rows}:
                raise ManifestError("complete_family_group_required")
            if (
                tier.min_group_size is None
                or tier.max_group_size is None
                or not tier.min_group_size <= len(rows) <= tier.max_group_size
            ):
                raise ManifestError("invalid_family_group_size")
        elif group_ids != {None}:
            raise ManifestError("individual_pilgrims_required")

    @staticmethod
    def _latest_price(tier: PricingTier) -> Decimal:
        return tier.ngn_price

    @staticmethod
    def _wholesale_price(tier: PricingTier, retail_price_ngn: Decimal) -> Decimal:
        if tier.usd_reference_price <= 0:
            raise ManifestError("pricing_unavailable")
        return (
            retail_price_ngn
            * tier.wholesale_usd_price
            / tier.usd_reference_price
        ).quantize(MONEY, rounding=ROUND_HALF_UP)

    def _resumable_order(
        self,
        session: Session,
        existing_ids: set[UUID | None],
        tier_id: UUID,
        rows: list[ManifestPilgrim],
        requested_ids: list[UUID],
    ) -> ManifestOrder | None:
        if len(existing_ids) != 1 or None in existing_ids:
            return None
        order_id = next(iter(existing_ids))
        assert order_id is not None
        order = session.get(ManifestOrder, order_id)
        if order is None or order.pricing_tier_id != tier_id:
            return None
        order_rows = session.exec(
            select(ManifestPilgrim).where(
                ManifestPilgrim.manifest_order_id == order.id
            )
        ).all()
        if {row.id for row in order_rows} != set(requested_ids):
            return None
        if {row.id for row in rows} != set(requested_ids):
            return None
        return order

    def _finalize_invoice(
        self,
        session: Session,
        order: ManifestOrder,
        manifest: Manifest,
        organization: Organization,
        tier: PricingTier,
    ) -> ManifestOrderResponse:
        locked_order = session.exec(
            select(ManifestOrder)
            .where(ManifestOrder.id == order.id)
            .with_for_update()
        ).one()
        order = locked_order
        pdf: bytes | None = None
        created_invoice = False
        if order.invoice_object_key is None:
            pdf = self.pdf_generator.render(
                InvoiceDetails(
                    order_id=order.id,
                    organization_name=organization.name,
                    manifest_name=manifest.name or "Untitled manifest",
                    tier_name=tier.name,
                    pilgrim_count=order.pilgrim_count,
                    per_pilgrim_ngn=order.wholesale_price_ngn,
                    total_ngn=order.total_ngn,
                    bank_name=self.settings.invoice_bank_name,
                    account_name=self.settings.invoice_account_name,
                    account_number=self.settings.invoice_account_number,
                )
            )
            key = f"invoices/{organization.id}/{order.id}.pdf"
            try:
                self.invoice_storage.put(key, pdf)
            except InvoiceStorageError as exc:
                raise ManifestError("invoice_unavailable") from exc
            order.invoice_object_key = key
            order.invoice_url = (
                f"/v1/hto/manifests/{manifest.id}/order/{order.id}/invoice"
            )
            session.add(order)
            created_invoice = True
        if order.invoice_email_sent_at is None:
            try:
                pdf = pdf or self.invoice_storage.get(order.invoice_object_key or "")
                self.notifications.send_invoice(
                    organization.email,
                    organization.primary_contact_name,
                    str(order.id),
                    order.total_ngn,
                    pdf,
                )
            except (InvoiceStorageError, NotificationError) as exc:
                if created_invoice:
                    session.commit()
                else:
                    session.rollback()
                raise ManifestError("invoice_email_unavailable") from exc
            order.invoice_email_sent_at = self.clock()
            session.add(order)
        session.commit()
        session.refresh(order)
        assert order.invoice_url is not None
        return ManifestOrderResponse(
            manifest_order_id=order.id,
            total_ngn=float(order.total_ngn),
            invoice_url=order.invoice_url,
        )

    def _owned_order(
        self,
        session: Session,
        organization_id: UUID,
        manifest_id: UUID,
        order_id: UUID,
    ) -> tuple[ManifestOrder, PricingTier]:
        record = session.exec(
            select(ManifestOrder, PricingTier)
            .join(Manifest, col(Manifest.id) == ManifestOrder.manifest_id)
            .join(PricingTier, col(PricingTier.id) == ManifestOrder.pricing_tier_id)
            .where(
                ManifestOrder.id == order_id,
                ManifestOrder.manifest_id == manifest_id,
                Manifest.organization_id == organization_id,
            )
        ).first()
        if record is None:
            raise ManifestError("manifest_order_not_found")
        return record

    def _activation_code(self, session: Session) -> str:
        for _ in range(10):
            code = "".join(secrets.choice(ACTIVATION_ALPHABET) for _ in range(8))
            existing = session.exec(
                select(ManifestPilgrim.id).where(
                    ManifestPilgrim.activation_code == code
                )
            ).first()
            if existing is None:
                return code
        raise ManifestError("activation_code_unavailable")
