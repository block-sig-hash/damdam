"""The account area: devices, receipts, support, preferences, export, deletion.

Everything here is scoped to one person by construction. Every read takes a
`User` and filters on it in the query rather than checking ownership after
fetching — `AGENTS.md` calls a cross-tenant read a breach rather than a bug, and
the difference between the two styles is one forgotten `if`.

Two decisions are worth reading before the code:

**A receipt is rendered from history, never from live lookups.** Chunk 14
established it for bank transfers and it holds here: reprinting last year's
receipt must produce last year's numbers, in last year's currency. So the
receipt view reads the order and its items as they were recorded and never
re-prices anything from the catalog, which has moved on.

**Revoking a session revokes the token, not the row.** `account_sessions` is
descriptive; `refresh_tokens` is what authentication checks. Revocation writes
the token first and the description second, so the worst outcome of a failure
between them is a session that still appears in the list after it stopped
working — never one that disappeared from the list and kept working.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlmodel import Session, col, select

from app.account.deletion import DeletionAssessment, assess
from app.account.models import (
    AccountExportJob,
    AccountSession,
    ExportState,
    NotificationCategory,
    NotificationChannel,
    NotificationPreference,
    SessionPlatform,
    SupportCategory,
    SupportRequest,
    SupportState,
)
from app.audit.models import AuditOutcome
from app.auth.models import Locale, RefreshToken, User, utc_now
from app.connectivity.models import CarrierLine
from app.orders.models import Order, OrderItem

#: Everything is on unless somebody turned it off. A product that defaults to
#: silence tells a customer their balance ran out by letting their line stop
#: working — but see `may_notify`: the *absence* of a row is a default, not a
#: decision, and an explicit `false` always wins.
DEFAULT_ENABLED = True

#: An export link is short-lived on purpose. The file is a copy of somebody's
#: account history, and the longer it exists the more places it can be.
EXPORT_TTL_HOURS = 24


class AccountError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ReceiptLine:
    description: str
    quantity: int
    unit_amount: Decimal
    total_amount: Decimal


@dataclass(frozen=True)
class Receipt:
    """One order as it was, with enough on it to be a record of a purchase."""

    order_id: UUID
    reference: str
    placed_at: datetime
    currency: str
    total_amount: Decimal
    payment_state: str
    lines: Sequence[ReceiptLine]
    organization_id: UUID | None = None


class AccountService:
    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self.clock = clock

    # --- sessions and devices ---------------------------------------------

    def record_session(
        self,
        session: Session,
        user: User,
        refresh_token: RefreshToken,
        *,
        platform: SessionPlatform = SessionPlatform.UNKNOWN,
        device_label: str | None = None,
        app_version: str | None = None,
        city: str | None = None,
        country: str | None = None,
    ) -> AccountSession:
        """Describe a token that already exists, so its owner can recognise it.

        Idempotent on the token: a client that retries a sign-in with the same
        refresh token updates the description rather than adding a second device
        to the list. A duplicate here is worse than it looks — a customer who
        sees two identical phones cannot tell which one to revoke.
        """
        existing = session.exec(
            select(AccountSession).where(
                AccountSession.refresh_token_id == refresh_token.id
            )
        ).first()
        now = self.clock()
        if existing is not None:
            existing.device_label = _trim(device_label, 120) or existing.device_label
            existing.app_version = _trim(app_version, 40) or existing.app_version
            existing.last_seen_city = _trim(city, 120) or existing.last_seen_city
            existing.last_seen_country = (
                _trim(country, 2) or existing.last_seen_country
            )
            existing.last_seen_at = now
            session.add(existing)
            session.flush()
            return existing

        record = AccountSession(
            user_id=user.id,
            refresh_token_id=refresh_token.id,
            platform=platform,
            device_label=_trim(device_label, 120),
            app_version=_trim(app_version, 40),
            last_seen_city=_trim(city, 120),
            last_seen_country=_trim(country, 2),
            last_seen_at=now,
            created_at=now,
        )
        session.add(record)
        session.flush()
        return record

    def on_token_issued(
        self,
        session: Session,
        user: User,
        token: RefreshToken,
        now: datetime,
        *,
        platform: str | None,
    ) -> None:
        """Project every real login into the device list.

        This also reconciles bulk revocation performed by account recovery, so
        old descriptive rows cannot look active after their tokens died.
        """
        self._sync_revoked_sessions(session, user, now)
        try:
            session_platform = SessionPlatform(
                platform or getattr(user.platform, "value", user.platform) or "unknown"
            )
        except ValueError:
            session_platform = SessionPlatform.UNKNOWN
        self.record_session(
            session, user, token, platform=session_platform, app_version=None
        )

    def on_token_rotated(
        self,
        session: Session,
        user: User,
        old_token: RefreshToken,
        new_token: RefreshToken,
        now: datetime,
    ) -> None:
        """A refresh is the same device, not a second device."""
        record = session.exec(
            select(AccountSession).where(
                AccountSession.user_id == user.id,
                AccountSession.refresh_token_id == old_token.id,
            )
        ).first()
        if record is None:
            self.on_token_issued(
                session, user, new_token, now, platform=None
            )
            return
        record.refresh_token_id = new_token.id
        record.last_seen_at = now
        session.add(record)
        session.flush()

    def _sync_revoked_sessions(
        self, session: Session, user: User, now: datetime
    ) -> None:
        for record in session.exec(
            select(AccountSession).where(
                AccountSession.user_id == user.id,
                col(AccountSession.revoked_at).is_(None),
            )
        ).all():
            token = session.get(RefreshToken, record.refresh_token_id)
            if token is None:
                record.revoked_at = now
                record.revoked_reason = "token_removed"
                session.add(record)
            elif token.revoked_at is not None or token.expires_at <= now:
                record.revoked_at = token.revoked_at or token.expires_at
                record.revoked_reason = (
                    "account_recovery" if token.revoked_at is not None else "expired"
                )
                session.add(record)

    def sessions(self, session: Session, user: User) -> Sequence[AccountSession]:
        """This account's devices, most recently seen first, revoked ones last."""
        self._sync_revoked_sessions(session, user, self.clock())
        session.flush()
        return session.exec(
            select(AccountSession)
            .where(AccountSession.user_id == user.id)
            .order_by(
                col(AccountSession.revoked_at).is_not(None),
                col(AccountSession.last_seen_at).desc(),
            )
        ).all()

    def revoke_session(
        self,
        session: Session,
        user: User,
        session_id: UUID,
        *,
        reason: str = "revoked_by_owner",
    ) -> AccountSession:
        """Sign one device out. The token goes first.

        Ownership is part of the query, not a check after the fetch. A session
        belonging to another account is `session_not_found` — the same answer as
        one that never existed, because a different answer confirms the id is
        real.
        """
        record = session.exec(
            select(AccountSession).where(
                AccountSession.id == session_id,
                AccountSession.user_id == user.id,
            )
        ).first()
        if record is None:
            raise AccountError("session_not_found")
        if record.revoked_at is not None:
            return record

        now = self.clock()
        token = session.get(RefreshToken, record.refresh_token_id)
        if token is not None and token.revoked_at is None:
            token.revoked_at = now
            token.updated_at = now
            session.add(token)
            session.flush()

        record.revoked_at = now
        record.revoked_reason = _trim(reason, 120)
        session.add(record)
        session.flush()
        return record

    def revoke_all_sessions(
        self, session: Session, user: User, *, except_session_id: UUID | None = None
    ) -> int:
        """Sign every device out, optionally keeping the one asking.

        Used by "sign out everywhere" and by deletion. Keeping the current
        session is the caller's choice: a customer who suspects a compromise
        wants to stay signed in on the phone in their hand.
        """
        revoked = 0
        for record in self.sessions(session, user):
            if record.revoked_at is not None or record.id == except_session_id:
                continue
            self.revoke_session(session, user, record.id, reason="revoked_all")
            revoked += 1
        return revoked

    # --- receipts ---------------------------------------------------------

    def receipts(
        self, session: Session, user: User, *, limit: int = 50
    ) -> Sequence[Receipt]:
        orders = session.exec(
            select(Order)
            .where(Order.payer_user_id == user.id)
            .order_by(col(Order.placed_at).desc())
            .limit(limit)
        ).all()
        return [self._receipt(session, order) for order in orders]

    def receipt(self, session: Session, user: User, order_id: UUID) -> Receipt:
        order = session.exec(
            select(Order).where(
                Order.id == order_id, Order.payer_user_id == user.id
            )
        ).first()
        if order is None:
            raise AccountError("receipt_not_found")
        return self._receipt(session, order)

    def _receipt(self, session: Session, order: Order) -> Receipt:
        """Built from what was recorded, never from what things cost now.

        `order_items` stores a unit amount, quantity and the product description
        captured at purchase. The live lookup is only a compatibility fallback
        for a partially migrated historical row.
        """
        from app.catalog.models import Product

        items = session.exec(
            select(OrderItem).where(OrderItem.order_id == order.id)
        ).all()
        lines: list[ReceiptLine] = []
        for item in items:
            product = session.get(Product, item.product_id)
            total = item.unit_amount * item.quantity
            lines.append(
                ReceiptLine(
                    description=(
                        item.description_snapshot
                        or (product.name if product is not None else "item")
                    ),
                    quantity=item.quantity,
                    unit_amount=item.unit_amount,
                    total_amount=total,
                )
            )
        return Receipt(
            order_id=order.id,
            reference=order.reference,
            placed_at=order.placed_at,
            currency=order.currency,
            total_amount=order.total_amount,
            payment_state=order.payment_state.value,
            organization_id=order.payer_organization_id,
            lines=lines,
        )

    # --- support ----------------------------------------------------------

    def open_support_request(
        self,
        session: Session,
        user: User,
        *,
        category: SupportCategory,
        subject: str,
        body: str,
        locale: Locale | str,
        order_id: UUID | None = None,
        entitlement_id: UUID | None = None,
    ) -> SupportRequest:
        """Take a question, with the thing it is about attached.

        The references are verified against this customer before they are
        stored. An unverified reference would let somebody attach their ticket
        to another customer's order and have an agent open it in good faith.
        """
        summary: str | None = None
        if order_id is not None:
            order = session.exec(
                select(Order).where(
                    Order.id == order_id, Order.payer_user_id == user.id
                )
            ).first()
            if order is None:
                raise AccountError("order_not_found")
            summary = (
                f"order {order.reference} · "
                f"{order.currency} {order.total_amount}"
            )
        if entitlement_id is not None and not self._owns_entitlement(
            session, user, entitlement_id
        ):
            raise AccountError("entitlement_not_found")

        request = SupportRequest(
            user_id=user.id,
            reference=self._support_reference(session),
            category=category,
            state=SupportState.OPEN,
            subject=_trim(subject, 200) or "",
            body=_trim(body, 4000) or "",
            locale=str(getattr(locale, "value", locale)),
            order_id=order_id,
            entitlement_id=entitlement_id,
            subject_summary=_trim(summary, 300),
            created_at=self.clock(),
        )
        session.add(request)
        session.flush()
        return request

    def support_requests(
        self, session: Session, user: User, *, limit: int = 50
    ) -> Sequence[SupportRequest]:
        return session.exec(
            select(SupportRequest)
            .where(SupportRequest.user_id == user.id)
            .order_by(col(SupportRequest.created_at).desc())
            .limit(limit)
        ).all()

    def _support_reference(self, session: Session) -> str:
        """Short, unambiguous and not guessable in sequence.

        A sequential ticket number leaks how many customers have a problem and
        lets anyone who has one reference another. The alphabet omits the
        characters people mistype when reading a reference aloud.
        """
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        for _ in range(10):
            candidate = "S-" + "".join(secrets.choice(alphabet) for _ in range(8))
            clash = session.exec(
                select(SupportRequest).where(SupportRequest.reference == candidate)
            ).first()
            if clash is None:
                return candidate
        raise AccountError(  # pragma: no cover - 32^8 space, ten tries
            "support_reference_unavailable"
        )

    # --- notification preferences -----------------------------------------

    def preferences(
        self, session: Session, user: User
    ) -> Sequence[NotificationPreference]:
        return session.exec(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user.id
            )
        ).all()

    def set_preference(
        self,
        session: Session,
        user: User,
        *,
        category: NotificationCategory,
        channel: NotificationChannel,
        enabled: bool,
    ) -> NotificationPreference:
        existing = session.exec(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user.id,
                NotificationPreference.category == category,
                NotificationPreference.channel == channel,
            )
        ).first()
        if existing is not None:
            existing.enabled = enabled
            existing.updated_at = self.clock()
            session.add(existing)
            session.flush()
            return existing
        record = NotificationPreference(
            user_id=user.id,
            category=category,
            channel=channel,
            enabled=enabled,
            updated_at=self.clock(),
        )
        session.add(record)
        session.flush()
        return record

    def may_notify(
        self,
        session: Session,
        user: User,
        category: NotificationCategory,
        channel: NotificationChannel,
    ) -> bool:
        """The question every sender must ask before sending.

        An absent row means nobody decided, and the default applies. An explicit
        `false` is a decision and always wins — including over a later default
        change, which is the reason the row is stored rather than inferred.
        """
        record = session.exec(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user.id,
                NotificationPreference.category == category,
                NotificationPreference.channel == channel,
            )
        ).first()
        if record is None:
            return DEFAULT_ENABLED
        return record.enabled

    # --- export -----------------------------------------------------------

    def request_export(self, session: Session, user: User) -> AccountExportJob:
        """One live export at a time, enforced by a partial unique index.

        A customer pressing the button twice gets the job they already asked
        for. Building two copies of somebody's account history because they were
        impatient is two copies to protect and two to expire.
        """
        existing = session.exec(
            select(AccountExportJob).where(
                AccountExportJob.user_id == user.id,
                col(AccountExportJob.state).in_(
                    [ExportState.REQUESTED, ExportState.BUILDING]
                ),
            )
        ).first()
        if existing is not None:
            return existing
        job = AccountExportJob(
            user_id=user.id,
            state=ExportState.REQUESTED,
            requested_at=self.clock(),
        )
        session.add(job)
        session.flush()
        return job

    def complete_export(
        self, session: Session, job: AccountExportJob, storage_key: str
    ) -> AccountExportJob:
        now = self.clock()
        job.state = ExportState.READY
        job.storage_key = storage_key
        job.completed_at = now
        job.expires_at = now + timedelta(hours=EXPORT_TTL_HOURS)
        session.add(job)
        session.flush()
        return job

    def build_export(self, session: Session, user: User) -> dict[str, object]:
        """This person's data, as the product holds it.

        Deliberately includes what a customer would be surprised to find missing
        — their support history, their devices, their orders — and deliberately
        excludes anything that is not theirs: another member's lines, an
        organization's other orders, and any activation material, which is a
        secret that happens to be stored near their data rather than part of it.
        """
        from app.calling.models import CallAttempt, CallCharge

        receipts = self.receipts(session, user, limit=1000)
        attempts = session.exec(
            select(CallAttempt)
            .where(CallAttempt.owner_user_id == user.id)
            .order_by(col(CallAttempt.created_at).desc())
        ).all()
        charges = (
            {
                charge.attempt_id: charge
                for charge in session.exec(
                    select(CallCharge).where(
                        col(CallCharge.attempt_id).in_(
                            [attempt.id for attempt in attempts]
                        )
                    )
                ).all()
            }
            if attempts
            else {}
        )
        return {
            "account": {
                "id": str(user.id),
                "phone_number": user.phone_number,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "locale": user.locale.value
                if hasattr(user.locale, "value")
                else str(user.locale),
                "status": user.status.value
                if hasattr(user.status, "value")
                else str(user.status),
                "created_at": user.created_at.isoformat(),
            },
            "orders": [
                {
                    "reference": receipt.reference,
                    "placed_at": receipt.placed_at.isoformat(),
                    "currency": receipt.currency,
                    "total_amount": str(receipt.total_amount),
                    "payment_state": receipt.payment_state,
                    "lines": [
                        {
                            "description": line.description,
                            "quantity": line.quantity,
                            "total_amount": str(line.total_amount),
                        }
                        for line in receipt.lines
                    ],
                }
                for receipt in receipts
            ],
            "support_requests": [
                {
                    "reference": request.reference,
                    "category": request.category.value,
                    "state": request.state.value,
                    "subject": request.subject,
                    "created_at": request.created_at.isoformat(),
                }
                for request in self.support_requests(session, user, limit=1000)
            ],
            "devices": [
                {
                    "label": record.device_label,
                    "platform": record.platform.value,
                    "last_seen_at": record.last_seen_at.isoformat()
                    if record.last_seen_at
                    else None,
                    "revoked_at": record.revoked_at.isoformat()
                    if record.revoked_at
                    else None,
                }
                for record in self.sessions(session, user)
            ],
            "notification_preferences": [
                {
                    "category": preference.category.value,
                    "channel": preference.channel.value,
                    "enabled": preference.enabled,
                }
                for preference in self.preferences(session, user)
            ],
            "calls": [
                {
                    "attempt_id": str(attempt.id),
                    "destination": attempt.e164_destination,
                    "destination_country": attempt.destination_country,
                    "state": attempt.state.value,
                    "created_at": attempt.created_at.isoformat(),
                    "ended_at": (
                        attempt.ended_at.isoformat() if attempt.ended_at else None
                    ),
                    "currency": attempt.currency,
                    "authorized_maximum": str(attempt.max_charge_amount),
                    "charged_amount": (
                        str(charges[attempt.id].charged_amount)
                        if attempt.id in charges
                        else None
                    ),
                    "charge_state": (
                        charges[attempt.id].state.value
                        if attempt.id in charges
                        else None
                    ),
                }
                for attempt in attempts
            ],
        }

    # --- deletion ---------------------------------------------------------

    def assess_deletion(self, session: Session, user: User) -> DeletionAssessment:
        return assess(session, user, self.clock())

    def _owns_entitlement(
        self, session: Session, user: User, entitlement_id: UUID
    ) -> bool:
        """An entitlement is this customer's if the order that bought it was."""
        from app.connectivity.models import Entitlement

        entitlement = session.get(Entitlement, entitlement_id)
        return entitlement is not None and entitlement.holder_user_id == user.id


def _trim(value: str | None, length: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned[:length] if cleaned else None


__all__ = [
    "AccountError",
    "AccountService",
    "AuditOutcome",
    "CarrierLine",
    "Receipt",
    "ReceiptLine",
]
