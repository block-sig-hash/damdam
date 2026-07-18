from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlmodel import Session, col, select

from app.audit.models import AuditEventType, AuditOutcome
from app.audit.service import AuditLogService
from app.auth.models import PricingTier, User
from app.config import Settings
from app.esim.models import EsimIssuanceJob, EsimProfile
from app.esim.service import EsimIssuanceScheduler
from app.notifications.service import NotificationError, NotificationService
from app.packages.models import (
    Package,
    PackageSource,
    PackageStatus,
    PaymentMethod,
    PaymentProcessor,
    Transaction,
    TransactionStatus,
)
from app.packages.service import PackageChainingService
from app.payments.providers import (
    PaymentCheckout,
    PaymentInitialization,
    PaymentProvider,
    PaymentProviderError,
)

RETAIL_CHANNELS = ("card", "bank_transfer", "ussd", "mobile_money")


class PaymentError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PurchaseResult:
    package_id: UUID
    checkout: PaymentCheckout


class PaymentService:
    def __init__(
        self,
        settings: Settings,
        providers: Mapping[str, PaymentProvider],
        notifications: NotificationService,
        clock: Callable[[], datetime],
        esim_scheduler: EsimIssuanceScheduler,
        chaining: PackageChainingService,
        audit: AuditLogService,
    ) -> None:
        self.settings = settings
        self.providers = providers
        self.notifications = notifications
        self.clock = clock
        self.esim_scheduler = esim_scheduler
        self.chaining = chaining
        self.audit = audit

    def initialize(
        self,
        session: Session,
        user: User,
        pricing_tier_id: UUID,
        group_size: int | None,
    ) -> PurchaseResult:
        tier = session.get(PricingTier, pricing_tier_id)
        if tier is None or not tier.active:
            raise PaymentError("pricing_tier_not_found")
        resolved_group_size = self._group_size(tier, group_size)
        amount = (tier.ngn_price * resolved_group_size).quantize(Decimal("0.01"))
        package = Package(
            user_id=user.id,
            pricing_tier_id=tier.id,
            source=PackageSource.RETAIL,
            status=PackageStatus.PENDING,
            group_size=resolved_group_size,
            data_gb_total=tier.data_gb,
            data_gb_remaining=Decimal("0.00"),
            pstn_minutes_total=tier.pstn_minutes,
            pstn_minutes_remaining=Decimal("0.00"),
            purchased_at=self.clock(),
            destination_country=user.destination_country,
        )
        reference = str(uuid4())
        initialization = PaymentInitialization(
            reference=reference,
            amount_ngn=amount,
            customer_email=user.email or f"pilgrim-{user.id}@payments.damdam.app",
            channels=RETAIL_CHANNELS,
            callback_url=self.settings.payment_callback_url,
            metadata={
                "package_id": str(package.id),
                "user_id": str(user.id),
                "tier_name": tier.name,
            },
        )
        checkout = self._initialize_with_failover(initialization)
        transaction = Transaction(
            package_id=package.id,
            processor=PaymentProcessor(checkout.processor),
            processor_reference=checkout.processor_reference,
            amount_ngn=amount,
            status=TransactionStatus.PENDING,
        )
        session.add(package)
        # Flush before adding the transaction row: without an ORM
        # relationship() tying Transaction to Package, SQLAlchemy's flush
        # ordering doesn't infer the FK dependency, so nothing guarantees
        # the package's INSERT happens before the transaction's -- the
        # same class of bug found and fixed in ActivationService.redeem()
        # (US-25). Harmless on SQLite (FK enforcement off by default), a
        # potential FK violation on real Postgres. Defensive hardening: a
        # direct real-Postgres test of this path did not reproduce an
        # ordering failure, but nothing here guarantees insert order
        # either, so this costs nothing and removes the dependency on
        # SQLAlchemy's unspecified default behavior.
        session.flush()
        session.add(transaction)
        session.commit()
        return PurchaseResult(package.id, checkout)

    def process_webhook(
        self,
        session: Session,
        processor: str,
        body: bytes,
        headers: Mapping[str, str],
    ) -> bool:
        provider = self.providers.get(processor)
        if provider is None:
            raise PaymentError("invalid_processor")
        try:
            event = provider.parse_webhook(body, headers)
        except PaymentProviderError as exc:
            code = (
                "invalid_webhook_signature"
                if "signature" in str(exc)
                else "invalid_webhook_payload"
            )
            raise PaymentError(code) from exc
        if event is None:
            return False

        transaction = session.exec(
            select(Transaction).where(
                Transaction.processor_reference == event.processor_reference,
            )
        ).first()
        if transaction is None or transaction.amount_ngn != event.amount_ngn:
            return False

        payment_method = self._payment_method(event.payment_method)
        result = cast(
            CursorResult[Any],
            session.execute(
                update(Transaction)
                .where(
                    col(Transaction.id) == transaction.id,
                    col(Transaction.status) == TransactionStatus.PENDING,
                )
                .values(
                    status=TransactionStatus.SUCCESS,
                    processor=PaymentProcessor(processor),
                    payment_method=payment_method,
                    webhook_payload=event.payload,
                )
            ),
        )
        processed = result.rowcount == 1
        if processed:
            package = session.get(Package, transaction.package_id)
            if package is None:
                session.rollback()
                raise PaymentError("package_not_found")
            tier = session.get(PricingTier, package.pricing_tier_id)
            if tier is None:
                session.rollback()
                raise PaymentError("package_not_found")
            # destination_country is the immutable snapshot initialize()
            # already took at the true purchase moment (data-model.md
            # §6.32) -- reusing it here, rather than re-deriving from the
            # user's *current* value at webhook-processing time, means a
            # future change to users.destination_country between checkout
            # and webhook confirmation can never silently overwrite the
            # correct purchase-time snapshot with a later value.
            window = self.chaining.chain(
                session, package.user_id, package.destination_country, tier
            )
            package.status = PackageStatus.ACTIVE
            package.data_gb_remaining = (
                Decimal(package.data_gb_total) + window.extra_data_gb
            )
            package.pstn_minutes_remaining = (
                Decimal(package.pstn_minutes_total) + window.extra_pstn_minutes
            )
            package.expires_at = window.expires_at
            session.add(package)
            session.add(
                EsimIssuanceJob(package_id=package.id, next_attempt_at=self.clock())
            )
            if window.superseded_package_id is not None:
                self.audit.record(
                    session,
                    AuditEventType.PACKAGE_PROVISIONING,
                    AuditOutcome.PACKAGE_CHAINED_ONTO_ACTIVE_WINDOW,
                    user_id=package.user_id,
                    reference=str(package.id),
                    details=(
                        f"superseded={window.superseded_package_id} "
                        f"rolled_forward_data_gb={window.extra_data_gb} "
                        f"rolled_forward_pstn_minutes={window.extra_pstn_minutes}"
                    ),
                )
            session.commit()
            session.refresh(transaction)
        else:
            session.rollback()
            self.audit.record(
                session,
                AuditEventType.PAYMENT_WEBHOOK,
                AuditOutcome.DUPLICATE_WEBHOOK_ABSORBED,
                reference=event.processor_reference,
                details=f"processor={processor}",
            )
            session.commit()
            transaction = session.exec(
                select(Transaction).where(
                    Transaction.processor_reference == event.processor_reference,
                )
            ).first()

        if transaction is not None and transaction.status == TransactionStatus.SUCCESS:
            self._schedule_esim_if_needed(session, transaction)
            self._send_receipt_if_needed(session, transaction)
        return processed

    def _schedule_esim_if_needed(
        self, session: Session, transaction: Transaction
    ) -> None:
        if transaction.package_id is None:
            return
        profile = session.exec(
            select(EsimProfile).where(EsimProfile.package_id == transaction.package_id)
        ).first()
        job = session.exec(
            select(EsimIssuanceJob).where(
                EsimIssuanceJob.package_id == transaction.package_id
            )
        ).first()
        if (
            profile is not None
            or job is None
            or job.completed_at is not None
            or job.next_attempt_at is None
        ):
            return
        try:
            self.esim_scheduler.schedule(transaction.package_id, 0)
        except Exception:
            # Payment is already durable. The job remains visible/due so a
            # duplicate webhook or operations worker can safely enqueue it.
            return
        job.next_attempt_at = None
        session.add(job)
        session.commit()

    def package_status(self, session: Session, user: User, package_id: UUID) -> Package:
        package = session.exec(
            select(Package).where(
                Package.id == package_id,
                Package.user_id == user.id,
            )
        ).first()
        if package is None:
            raise PaymentError("package_not_found")
        return package

    def _initialize_with_failover(
        self, initialization: PaymentInitialization
    ) -> PaymentCheckout:
        for processor in (
            self.settings.payment_processor_primary,
            self.settings.payment_processor_secondary,
        ):
            provider = self.providers.get(processor)
            if provider is None:
                continue
            try:
                return provider.initialize(initialization)
            except PaymentProviderError:
                continue
        raise PaymentError("payment_unavailable")

    @staticmethod
    def _group_size(tier: PricingTier, requested: int | None) -> int:
        if tier.is_group_tier:
            if (
                requested is None
                or tier.min_group_size is None
                or tier.max_group_size is None
                or not tier.min_group_size <= requested <= tier.max_group_size
            ):
                raise PaymentError("invalid_group_size")
            return requested
        if requested not in (None, 1):
            raise PaymentError("invalid_group_size")
        return 1

    @staticmethod
    def _payment_method(value: str) -> PaymentMethod:
        normalized = value.lower().replace(" ", "_")
        aliases = {
            "bank": PaymentMethod.BANK_TRANSFER,
            "banktransfer": PaymentMethod.BANK_TRANSFER,
            "mobile_money": PaymentMethod.BANK_TRANSFER,
            "mobilemoney": PaymentMethod.BANK_TRANSFER,
            "opay": PaymentMethod.BANK_TRANSFER,
            "palmpay": PaymentMethod.BANK_TRANSFER,
        }
        if normalized in aliases:
            return aliases[normalized]
        try:
            return PaymentMethod(normalized)
        except ValueError:
            return PaymentMethod.CARD

    def _send_receipt_if_needed(
        self, session: Session, transaction: Transaction
    ) -> None:
        if transaction.receipt_sent_at is not None or transaction.package_id is None:
            return
        package = session.get(Package, transaction.package_id)
        if package is None:
            return
        user = session.get(User, package.user_id)
        tier = session.get(PricingTier, package.pricing_tier_id)
        if user is None or tier is None or transaction.processor_reference is None:
            return
        delivered = True
        if user.email:
            try:
                self.notifications.send_receipt_email(
                    user.email,
                    tier.name,
                    transaction.amount_ngn,
                    transaction.processor_reference,
                )
            except NotificationError:
                delivered = False
        try:
            self.notifications.send_receipt_whatsapp(
                user.phone_number,
                tier.name,
                transaction.amount_ngn,
                transaction.processor_reference,
            )
        except NotificationError:
            delivered = False
        if delivered:
            transaction.receipt_sent_at = self.clock()
            session.add(transaction)
            session.commit()
