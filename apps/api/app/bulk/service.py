"""Buying, assigning and provisioning for many recipients at once (US-40, chunk 23).

Four rules run through everything here, and each one exists because the
alternative charges a customer for something they did not receive.

**Money is held per line.** Fifty recipients means fifty reservations, not one
for the total. A line that cannot be funded fails alone; a line that is
cancelled releases its own hold; and a partial refund does not have to
reconstruct which fiftieth of a lump sum belonged to whom.

**A lost supplier answer is never retried.** Chunk 11 settled this and this
module obeys it: an item whose outcome is `UNKNOWN` is reconciled against the
same idempotency key before anything else happens to it. `resume` is written so
that reaching the provisioning path with an unreconciled unknown is not
possible — not unlikely, *not possible* — because the alternative is a second
eSIM purchased for somebody who already has one.

**Progress is the items.** The job's counters are written in the same
transaction as the item they describe, so a worker that dies mid-run leaves a
job whose numbers are exactly as true as its rows. Resuming reads the rows.

**Nothing is provisioned to a recipient who cannot receive it.** A person who
has left, or who has no email and no phone, is marked invalid at planning time
and never funded. The alternative is a paid line nobody can be told about.

## Internet-only assignment

The calling amendment: *for internet-only assignment, provision the service
grant without purchasing a carrier profile.* A `VOICE` product takes the
entitlement path and stops — no supplier call, no eSIM, no installation. That is
not a shortcut; there is nothing to buy from a carrier, and asking one would
produce a profile nobody installs.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.auth.models import User, utc_now
from app.bulk.models import (
    FUNDED_ITEM_STATES,
    TERMINAL_ITEM_STATES,
    ActivationRequest,
    ActivationRequestState,
    BulkItemState,
    BulkJob,
    BulkJobItem,
    BulkJobState,
)
from app.catalog.models import Product, ProductKind
from app.connectivity.service import ConnectivityService
from app.ledger.models import AccountKind, LedgerAccount, OwnerKind, Reservation
from app.ledger.service import LedgerError, LedgerService
from app.money import round_money
from app.orders.models import Order, OrderItem, PaymentState, ProvisioningState
from app.people.models import OrganizationPerson, PersonStatus

#: How long a recipient has to claim their line before the invitation lapses.
#: Long enough to survive a holiday; short enough that a leaver's unclaimed
#: line does not sit redeemable for a year.
ACTIVATION_TTL_DAYS = 30


class BulkError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class JobProgress:
    """What a job has actually done, for a screen that must not round it off."""

    job_id: UUID
    state: BulkJobState
    recipient_count: int
    reserved: int
    provisioned: int
    failed: int
    unknown: int
    invalid: int
    cancelled: int

    @property
    def outstanding(self) -> int:
        return self.recipient_count - (
            self.provisioned + self.failed + self.invalid + self.cancelled
        )


class BulkProvisioningService:
    def __init__(
        self,
        ledger: LedgerService,
        connectivity: ConnectivityService | None = None,
        clock: Callable[[], datetime] = utc_now,
        activation_ttl_days: int = ACTIVATION_TTL_DAYS,
    ) -> None:
        self.ledger = ledger
        self.connectivity = connectivity
        self.clock = clock
        self.activation_ttl_days = activation_ttl_days

    # --- planning ----------------------------------------------------------

    def plan(
        self,
        session: Session,
        organization_id: UUID,
        *,
        idempotency_key: str,
        product: Product,
        sales_market_id: UUID,
        person_ids: Sequence[UUID],
        currency: str,
        unit_amount: Decimal,
        created_by_user_id: UUID | None = None,
    ) -> BulkJob:
        """Choose recipients and validate them. Holds no money and buys nothing.

        Replaying the key returns the job that already exists. A double-clicked
        "buy for these fifty people" is one job, and without that it is a second
        fifty lines and a second fifty charges.
        """
        bind = session.get_bind()
        if bind.dialect.name == "postgresql":
            # The unique constraint is the invariant; this transaction lock
            # turns a concurrent read-then-insert into the same idempotent
            # response instead of exposing the losing insert as a 500.
            session.execute(
                select(
                    func.pg_advisory_xact_lock(
                        func.hashtextextended(
                            f"bulk:{organization_id}:{idempotency_key}", 0
                        )
                    )
                )
            )
        existing = session.exec(
            select(BulkJob).where(
                BulkJob.organization_id == organization_id,
                BulkJob.idempotency_key == idempotency_key,
            )
        ).first()
        if existing is not None:
            existing_people = set(
                session.exec(
                    select(BulkJobItem.person_id).where(
                        BulkJobItem.job_id == existing.id
                    )
                ).all()
            )
            requested_people = set(person_ids)
            requested_currency = currency.upper()
            requested_amount = round_money(unit_amount, requested_currency)
            if (
                existing.product_id != product.id
                or existing.sales_market_id != sales_market_id
                or existing.currency != requested_currency
                or existing.unit_amount != requested_amount
                or existing_people != requested_people
            ):
                raise BulkError("idempotency_conflict")
            return existing
        if not person_ids:
            raise BulkError("no_recipients")

        now = self.clock()
        normalized_currency = currency.upper()
        job = BulkJob(
            organization_id=organization_id,
            created_by_user_id=created_by_user_id,
            idempotency_key=idempotency_key,
            product_id=product.id,
            sales_market_id=sales_market_id,
            state=BulkJobState.PLANNED,
            currency=normalized_currency,
            unit_amount=round_money(unit_amount, normalized_currency),
            recipient_count=len(set(person_ids)),
            created_at=now,
            updated_at=now,
        )
        session.add(job)
        session.flush()

        invalid = 0
        for person_id in dict.fromkeys(person_ids):  # de-duplicated, order kept
            person = session.exec(
                select(OrganizationPerson).where(
                    OrganizationPerson.id == person_id,
                    # Tenant scope in the query. A recipient from another
                    # organization simply does not exist here, which is what
                    # stops a bulk job being a cross-tenant read.
                    OrganizationPerson.organization_id == organization_id,
                )
            ).first()
            error = self._recipient_problem(person)
            item = BulkJobItem(
                job_id=job.id,
                person_id=person_id,
                state=BulkItemState.INVALID if error else BulkItemState.PENDING,
                error_code=error,
                updated_at=now,
            )
            session.add(item)
            invalid += 1 if error else 0
        job.invalid_count = invalid
        session.add(job)
        session.flush()
        return job

    def _recipient_problem(self, person: OrganizationPerson | None) -> str | None:
        """Why this recipient cannot be served, in one stable code."""
        if person is None:
            # Includes "belongs to another organization". Indistinguishable on
            # purpose: a different answer would confirm the id is real.
            return "recipient_not_found"
        if person.status is not PersonStatus.ACTIVE:
            return "recipient_archived"
        if not person.email and not person.phone_number:
            # Nothing to send an invitation to. Buying the line anyway produces
            # a paid service nobody can be told about.
            return "recipient_unreachable"
        return None

    # --- funding -----------------------------------------------------------

    def fund(self, session: Session, job: BulkJob) -> JobProgress:
        """Take one hold per line, from the organization's own credit.

        Under-funding is **partial, not fatal**: the lines that fit are funded
        and the rest are marked, because an organization that can afford forty
        of fifty lines would rather have forty than an error message.
        """
        self._lock_job(session, job)
        if job.state not in {BulkJobState.PLANNED, BulkJobState.FUNDED}:
            raise BulkError("job_not_fundable")

        account = self._organization_credit(session, job)
        reserved = job.reserved_count
        for item in self._items(session, job, states={BulkItemState.PENDING}):
            if not self._ensure_hold(session, job, item, account):
                item.state = BulkItemState.FAILED
                item.error_code = "insufficient_funds"
                item.updated_at = self.clock()
                session.add(item)
                job.failed_count += 1
                session.add(job)
                session.flush()
                continue
            item.state = BulkItemState.RESERVED
            item.updated_at = self.clock()
            session.add(item)
            reserved += 1
            job.reserved_count = reserved
            session.add(job)
            session.flush()

        job.state = BulkJobState.FUNDED
        job.updated_at = self.clock()
        session.add(job)
        session.flush()
        return self.progress(session, job)

    def _ensure_hold(
        self, session: Session, job: BulkJob, item: BulkJobItem, account: LedgerAccount
    ) -> bool:
        """Make sure this line has money held against it right now.

        The subtle case, and the one the fifty-recipient scenario caught: a
        definitively failed line has already had its hold **released**, so a
        retry that reused `reservation_id` would provision a line the
        organization is not holding a naira for. An outstanding balance is the
        only thing that counts as funded, and a fresh attempt takes a fresh
        hold under its own event id — reusing the old one would hand back the
        closed reservation through the ledger's own idempotency.
        """
        if item.reservation_id is not None:
            existing = session.get(Reservation, item.reservation_id)
            if existing is not None:
                outstanding = (
                    existing.amount
                    - existing.settled_amount
                    - existing.released_amount
                )
                if outstanding > 0:
                    return True
        try:
            reservation = self.ledger.reserve(
                session,
                account,
                job.unit_amount,
                f"bulk:{job.id}:item:{item.id}:attempt:{item.attempts}",
            )
        except LedgerError as error:
            if error.code != "insufficient_available_balance":
                raise
            return False
        item.reservation_id = reservation.id
        session.add(item)
        session.flush()
        return True

    # --- ordering and provisioning ----------------------------------------

    def provision(
        self,
        session: Session,
        job: BulkJob,
        *,
        seller_legal_entity_id: UUID,
    ) -> JobProgress:
        """Create one order line per funded recipient and grant what was bought.

        Every funded item gets its own `order_items` row — chunk 05's
        quantity-one invariant, which is exactly right here: fifty recipients
        are fifty order items, and each one can be cancelled, refunded and
        provisioned without touching the other forty-nine.
        """
        self._lock_job(session, job)
        if job.state in {
            BulkJobState.COMPLETED,
            BulkJobState.PARTIALLY_COMPLETED,
        }:
            # Already done. A worker that lost the response to this call and
            # retried it is asking a question, not making a second purchase —
            # and answering with an error would have it treat success as
            # failure. Chunk 11's rule, applied to the call itself.
            return self.progress(session, job)
        if job.state not in {BulkJobState.FUNDED, BulkJobState.PROVISIONING}:
            raise BulkError("job_not_provisionable")

        order = self._order_for(session, job, seller_legal_entity_id)
        job.state = BulkJobState.PROVISIONING
        session.add(job)
        session.flush()

        for item in self._items(session, job, states={BulkItemState.RESERVED}):
            self._provision_item(session, job, item, order)

        return self._settle_state(session, job)

    def _provision_item(
        self,
        session: Session,
        job: BulkJob,
        item: BulkJobItem,
        order: Order,
    ) -> None:
        order_item = self._order_item_for(session, job, item, order)
        item.order_item_id = order_item.id
        item.state = BulkItemState.ORDERED
        item.attempts += 1
        item.updated_at = self.clock()
        session.add(item)
        session.flush()

        product = session.get(Product, job.product_id)
        if product is None:  # pragma: no cover - FK guarantees this
            raise BulkError("product_not_found")

        if product.kind is ProductKind.VOICE:
            # Internet-only: the grant *is* the service. Asking a carrier for a
            # profile here would buy something nobody installs.
            self._grant(session, order_item)
            self._mark_provisioned(session, job, item)
            return

        # Carrier products need a supplier, and this chunk does not have one
        # wired: chunk 15 owns the adapter and its evidence gates are unchanged.
        # Leaving the item ORDERED is the honest state — it is funded, it has a
        # line, and nothing has been bought yet.
        if self.connectivity is None:
            return
        self._grant(session, order_item)
        self._mark_provisioned(session, job, item)

    def _grant(self, session: Session, order_item: OrderItem) -> None:
        if self.connectivity is None:
            return
        self.connectivity.grant_entitlement(session, order_item)

    def _mark_provisioned(
        self, session: Session, job: BulkJob, item: BulkJobItem
    ) -> None:
        now = self.clock()
        item.state = BulkItemState.PROVISIONED
        item.provisioned_at = now
        item.updated_at = now
        session.add(item)
        if item.order_item_id is not None:
            order_item = session.get(OrderItem, item.order_item_id)
            if order_item is not None:
                order_item.provisioning_state = ProvisioningState.PROVISIONED
                session.add(order_item)
        job.provisioned_count += 1
        job.updated_at = now
        session.add(job)
        session.flush()

    def mark_unknown(
        self, session: Session, job: BulkJob, item: BulkJobItem, reason: str
    ) -> BulkJobItem:
        """We lost the supplier's answer for one line.

        The hold stays. The item is not retried by `resume` — it is reconciled
        first — and until that happens this line is unfinished rather than
        failed, which is the difference between "ask again" and "buy again".
        """
        self._lock_job(session, job)
        self._lock_item(session, item)
        if item.state is BulkItemState.UNKNOWN:
            return item
        now = self.clock()
        item.state = BulkItemState.UNKNOWN
        item.error_code = reason[:64]
        item.updated_at = now
        session.add(item)
        if item.order_item_id is not None:
            order_item = session.get(OrderItem, item.order_item_id)
            if order_item is not None:
                order_item.provisioning_state = ProvisioningState.OUTCOME_UNKNOWN
                session.add(order_item)
        job.unknown_count += 1
        job.updated_at = now
        session.add(job)
        session.flush()
        return item

    def mark_failed(
        self, session: Session, job: BulkJob, item: BulkJobItem, reason: str
    ) -> BulkJobItem:
        """The supplier refused, definitively. Safe to retry; hold released."""
        self._lock_job(session, job)
        self._lock_item(session, item)
        if item.state is BulkItemState.FAILED:
            return item
        now = self.clock()
        item.state = BulkItemState.FAILED
        item.error_code = reason[:64]
        item.updated_at = now
        session.add(item)
        self._release(session, item)
        job.failed_count += 1
        job.updated_at = now
        session.add(job)
        session.flush()
        return item

    # --- resumption --------------------------------------------------------

    def resumable(
        self, session: Session, job: BulkJob
    ) -> tuple[Sequence[BulkJobItem], Sequence[BulkJobItem]]:
        """What a resume may touch, split by what must happen first.

        Returns `(to_reconcile, to_retry)`. The split is the whole safety
        property: an `UNKNOWN` item is never in the second list, so a caller
        cannot retry one by accident even by ignoring the first.
        """
        to_reconcile = self._items(session, job, states={BulkItemState.UNKNOWN})
        to_retry = self._items(session, job, states={BulkItemState.FAILED})
        return to_reconcile, to_retry

    def resume(
        self,
        session: Session,
        job: BulkJob,
        *,
        seller_legal_entity_id: UUID,
        reconcile: Callable[[BulkJobItem], bool | None] | None = None,
    ) -> JobProgress:
        """Continue a job, reconciling before retrying anything.

        `reconcile` is supplied by the caller because reconciliation talks to a
        supplier and this module does not. It returns `True` if the supplier
        confirms the work was done, `False` if it confirms it was not, and
        `None` if it still cannot say — in which case the item **stays
        unknown** and keeps its hold. Silence is not permission.
        """
        self._lock_job(session, job)
        to_reconcile, to_retry = self.resumable(session, job)

        for item in to_reconcile:
            outcome = reconcile(item) if reconcile else None
            if outcome is True:
                job.unknown_count = max(0, job.unknown_count - 1)
                self._mark_provisioned(session, job, item)
            elif outcome is False:
                job.unknown_count = max(0, job.unknown_count - 1)
                item.state = BulkItemState.RESERVED
                item.error_code = None
                item.updated_at = self.clock()
                session.add(item)
                session.flush()
            # `None`: left alone, hold intact, still unknown.

        if to_retry:
            order = self._order_for(session, job, seller_legal_entity_id)
            account = self._organization_credit(session, job)
            for item in to_retry:
                # Every retried line needs a live hold, whatever failed it: a
                # supplier rejection released the original, so reusing it would
                # provision a line nobody is holding money for.
                if not self._ensure_hold(session, job, item, account):
                    continue
                job.failed_count = max(0, job.failed_count - 1)
                item.state = BulkItemState.RESERVED
                item.error_code = None
                session.add(item)
                session.flush()
                self._provision_item(session, job, item, order)

        # Anything reserved but never ordered — a crash between funding and
        # provisioning — is picked up here rather than left for a human.
        if job.state is BulkJobState.PROVISIONING:
            order = self._order_for(session, job, seller_legal_entity_id)
            for item in self._items(session, job, states={BulkItemState.RESERVED}):
                self._provision_item(session, job, item, order)

        return self._settle_state(session, job)

    # --- cancellation ------------------------------------------------------

    def cancel_item(
        self, session: Session, job: BulkJob, item: BulkJobItem, *, reason: str
    ) -> BulkJobItem:
        """Withdraw one line, without touching the other forty-nine.

        A **provisioned** line is refused. The service exists; releasing its
        hold would be giving money back for something the customer has, and
        unwinding it is a refund under chunk 14's policy, with a human and a
        reason — not a cancellation.
        """
        self._lock_job(session, job)
        self._lock_item(session, item)
        if item.state is BulkItemState.PROVISIONED:
            raise BulkError(
                "item_already_provisioned",
                "a provisioned line is refunded under policy, not cancelled",
            )
        if item.state is BulkItemState.UNKNOWN:
            raise BulkError(
                "item_outcome_unknown",
                "reconcile before cancelling; the supplier may have provisioned it",
            )
        if item.state is BulkItemState.CANCELLED:
            return item

        now = self.clock()
        self._release(session, item)
        was_counted_failed = item.state is BulkItemState.FAILED
        item.state = BulkItemState.CANCELLED
        item.error_code = reason[:64]
        item.updated_at = now
        session.add(item)
        if item.order_item_id is not None:
            order_item = session.get(OrderItem, item.order_item_id)
            if order_item is not None:
                order_item.provisioning_state = ProvisioningState.CANCELLED
                session.add(order_item)
        if was_counted_failed:
            job.failed_count = max(0, job.failed_count - 1)
        job.cancelled_count += 1
        job.updated_at = now
        session.add(job)
        session.flush()
        return item

    def cancel_job(
        self, session: Session, job: BulkJob, *, reason: str
    ) -> JobProgress:
        """Stop everything that has not happened yet, and nothing that has."""
        self._lock_job(session, job)
        for item in self._items(
            session,
            job,
            states={
                BulkItemState.PENDING,
                BulkItemState.RESERVED,
                BulkItemState.FAILED,
            },
        ):
            self.cancel_item(session, job, item, reason=reason)
        job.state = BulkJobState.CANCELLED
        job.updated_at = self.clock()
        session.add(job)
        session.flush()
        return self.progress(session, job)

    # --- activation requests ----------------------------------------------

    def issue_activation_request(
        self, session: Session, job: BulkJob, item: BulkJobItem
    ) -> tuple[ActivationRequest, str]:
        """Invite one recipient to claim one line. Returns the token **once**.

        The token is returned to the caller and stored only as a hash. A table
        of live invitation tokens is a table of credentials, and this one is
        readable by every administrator of the tenant.
        """
        self._lock_job(session, job)
        self._lock_item(session, item)
        if item.state is not BulkItemState.PROVISIONED:
            raise BulkError(
                "line_not_ready",
                "invite somebody once their line exists, not before",
            )
        existing = session.exec(
            select(ActivationRequest).where(
                ActivationRequest.bulk_job_item_id == item.id,
                col(ActivationRequest.state).in_(
                    [ActivationRequestState.PENDING, ActivationRequestState.SENT]
                ),
            )
        ).first()
        if existing is not None:
            raise BulkError("activation_request_exists")

        person = session.get(OrganizationPerson, item.person_id)
        if person is None:  # pragma: no cover - FK guarantees this
            raise BulkError("recipient_not_found")

        token = secrets.token_urlsafe(32)
        now = self.clock()
        request = ActivationRequest(
            organization_id=job.organization_id,
            bulk_job_item_id=item.id,
            person_id=item.person_id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            state=ActivationRequestState.PENDING,
            delivered_to=person.email or person.phone_number,
            expires_at=now + timedelta(days=self.activation_ttl_days),
            created_at=now,
        )
        session.add(request)
        session.flush()
        return request, token

    def redeem_activation_request(
        self, session: Session, token: str, user: User
    ) -> ActivationRequest:
        """Claim a line, once, and bind it to the account doing the claiming.

        This is the moment a recipient becomes a user of ours: the order item
        and the entitlement both gain a holder, and the request is spent.
        """
        digest = hashlib.sha256(token.encode()).hexdigest()
        request = session.exec(
            select(ActivationRequest)
            .where(ActivationRequest.token_hash == digest)
            .with_for_update()
        ).first()
        if request is None:
            raise BulkError("activation_request_not_found")
        if request.state is ActivationRequestState.REDEEMED:
            raise BulkError("activation_request_spent")
        if request.state is ActivationRequestState.REVOKED:
            raise BulkError("activation_request_revoked")
        now = self.clock()
        if now >= _aware(request.expires_at):
            request.state = ActivationRequestState.EXPIRED
            session.add(request)
            session.flush()
            raise BulkError("activation_request_expired")

        item = session.get(BulkJobItem, request.bulk_job_item_id)
        if item is not None and item.order_item_id is not None:
            order_item = session.get(OrderItem, item.order_item_id)
            if order_item is not None:
                order_item.recipient_user_id = user.id
                session.add(order_item)
                if self.connectivity is not None:
                    entitlement = self.connectivity.grant_entitlement(
                        session, order_item
                    )
                    entitlement.holder_user_id = user.id
                    session.add(entitlement)
        request.state = ActivationRequestState.REDEEMED
        request.redeemed_by_user_id = user.id
        request.redeemed_at = now
        session.add(request)
        session.flush()
        return request

    def revoke_activation_request(
        self, session: Session, request: ActivationRequest, *, reason: str
    ) -> ActivationRequest:
        """Somebody left before they claimed it."""
        if request.state is ActivationRequestState.REDEEMED:
            raise BulkError("activation_request_spent")
        request.state = ActivationRequestState.REVOKED
        request.revoked_reason = reason[:120]
        session.add(request)
        session.flush()
        return request

    # --- reads -------------------------------------------------------------

    def progress(self, session: Session, job: BulkJob) -> JobProgress:
        return JobProgress(
            job_id=job.id,
            state=job.state,
            recipient_count=job.recipient_count,
            reserved=job.reserved_count,
            provisioned=job.provisioned_count,
            failed=job.failed_count,
            unknown=job.unknown_count,
            invalid=job.invalid_count,
            cancelled=job.cancelled_count,
        )

    def job(
        self, session: Session, organization_id: UUID, job_id: UUID
    ) -> BulkJob:
        found = session.exec(
            select(BulkJob).where(
                BulkJob.id == job_id, BulkJob.organization_id == organization_id
            )
        ).first()
        if found is None:
            raise BulkError("job_not_found")
        return found

    def items(
        self, session: Session, job: BulkJob, *, limit: int = 500
    ) -> Sequence[BulkJobItem]:
        return session.exec(
            select(BulkJobItem)
            .where(BulkJobItem.job_id == job.id)
            .order_by(col(BulkJobItem.updated_at))
            .limit(limit)
        ).all()

    # --- internals ---------------------------------------------------------

    def _lock_job(self, session: Session, job: BulkJob) -> None:
        """Serialize every state and counter transition for one bulk job."""
        session.refresh(job, with_for_update=True)

    def _lock_item(self, session: Session, item: BulkJobItem) -> None:
        """Refresh an item under a row lock before testing its transition."""
        session.refresh(item, with_for_update=True)

    def _items(
        self, session: Session, job: BulkJob, *, states: set[BulkItemState]
    ) -> Sequence[BulkJobItem]:
        return session.exec(
            select(BulkJobItem)
            .where(
                BulkJobItem.job_id == job.id,
                col(BulkJobItem.state).in_(list(states)),
            )
            .order_by(col(BulkJobItem.id))
        ).all()

    def _release(self, session: Session, item: BulkJobItem) -> None:
        """Give back this line's hold, if it still has one."""
        if item.reservation_id is None:
            return
        reservation = session.get(Reservation, item.reservation_id)
        if reservation is None:  # pragma: no cover - FK guarantees this
            return
        outstanding = (
            reservation.amount
            - reservation.settled_amount
            - reservation.released_amount
        )
        if outstanding > 0:
            self.ledger.release(session, reservation, outstanding)

    def _organization_credit(
        self, session: Session, job: BulkJob
    ) -> LedgerAccount:
        return self.ledger.account(
            session,
            job.currency,
            AccountKind.SERVICE_CREDIT,
            OwnerKind.ORGANIZATION,
            owner_organization_id=job.organization_id,
        )

    def _order_for(
        self, session: Session, job: BulkJob, seller_legal_entity_id: UUID
    ) -> Order:
        """One order per job, created once and found thereafter."""
        if job.order_id is not None:
            order = session.get(Order, job.order_id)
            if order is not None:
                return order
        order = Order(
            reference=f"BULK-{job.id.hex[:10].upper()}",
            seller_legal_entity_id=seller_legal_entity_id,
            payer_organization_id=job.organization_id,
            currency=job.currency,
            total_amount=round_money(
                job.unit_amount * job.recipient_count, job.currency
            ),
            payment_state=PaymentState.AUTHORIZED,
            placed_at=self.clock(),
        )
        session.add(order)
        session.flush()
        job.order_id = order.id
        session.add(job)
        session.flush()
        return order

    def _order_item_for(
        self, session: Session, job: BulkJob, item: BulkJobItem, order: Order
    ) -> OrderItem:
        """One order item per recipient, created once.

        Re-entrant by lookup rather than by memory: a resumed run finds the row
        it already wrote instead of writing a second line for the same person.
        """
        if item.order_item_id is not None:
            existing = session.get(OrderItem, item.order_item_id)
            if existing is not None:
                return existing
        order_item = OrderItem(
            order_id=order.id,
            product_id=job.product_id,
            # Null until somebody claims it. An organization may buy for a
            # person who has no account with us, and inventing one here would
            # bind a line to an identity nobody authenticated.
            recipient_user_id=None,
            quantity=1,
            unit_currency=job.currency,
            unit_amount=job.unit_amount,
            provisioning_state=ProvisioningState.REQUESTED,
        )
        session.add(order_item)
        session.flush()
        return order_item

    def _settle_state(self, session: Session, job: BulkJob) -> JobProgress:
        """Decide whether the job is finished, and how well."""
        outstanding = session.exec(
            select(BulkJobItem).where(
                BulkJobItem.job_id == job.id,
                col(BulkJobItem.state).notin_(list(TERMINAL_ITEM_STATES)),
            )
        ).all()
        if not outstanding:
            everything_worked = job.provisioned_count == job.recipient_count
            job.state = (
                BulkJobState.COMPLETED
                if everything_worked
                else BulkJobState.PARTIALLY_COMPLETED
            )
            job.completed_at = self.clock()
        job.updated_at = self.clock()
        session.add(job)
        session.flush()
        return self.progress(session, job)


def _aware(moment: datetime) -> datetime:
    """Treat a stored timestamp as UTC when the driver hands it back naive.

    The same helper `app/catalog/service.py` carries, for the same reason: a
    value written through one session and read through another can lose its
    tzinfo, and comparing it to an aware `now` raises rather than returning
    the wrong answer — which is at least loud, and is how this one was found.
    """
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


__all__ = [
    "FUNDED_ITEM_STATES",
    "BulkError",
    "BulkProvisioningService",
    "JobProgress",
]
