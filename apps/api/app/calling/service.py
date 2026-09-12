"""Call authorization: the durable grant, and the single-use consumption of it.

Everything in this chunk exists to make one sentence true — *a destination leg
starts only from an unused, unexpired, owner-scoped grant whose reservation
committed first* (V01 invariant 1) — and this module is where that sentence is
enforced.

The shape follows from one finding. V01 established that a client telephony
credential authenticates an **endpoint**, with no documented per-destination
scope: a copied token can do whatever its connection permits. So the client is
never trusted with a decision. It supplies a destination *claim* at authorize
time, the server normalizes, prices and binds it into a row, and every later
step compares against that row rather than against anything the client or the
provider sends. `authorize` is the only place a destination is chosen; nothing
downstream may substitute one.

Three operations, three different atomicity requirements:

- **authorize** takes a hold on money. It must be idempotent against a retried
  request (N1) and correct against a concurrent one (N16). Both are the ledger's
  job, and both are delegated to it rather than reimplemented.
- **start** hands the client what it needs. It must converge: the same request
  twice returns the same instruction, and never a second grant.
- **consume** spends the grant exactly once. It is a conditional UPDATE, not a
  read-then-write, because a read-then-write under two concurrent webhooks
  authorizes two calls from one grant.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, update
from sqlmodel import Session, col, select

from app.auth.models import User, utc_now
from app.calling.models import (
    ATTEMPT_STATE_RANK,
    TERMINAL_ATTEMPT_STATES,
    AttemptState,
    CallAttempt,
    CallingClientCredential,
    CredentialState,
    PayerKind,
)
from app.calling.policy import (
    DestinationDecision,
    DestinationRefused,
    classify_destination,
)
from app.calling.pricing import estimate_max_charge
from app.catalog.market import PublicationStatus
from app.catalog.models import Product, ProductKind
from app.catalog.tariffs import (
    OriginKind,
    RateNotFoundError,
    Tariff,
    TariffRate,
    select_rate,
)
from app.connectivity.models import Entitlement
from app.ledger.models import AccountKind, LedgerAccount, OwnerKind, Reservation
from app.ledger.service import LedgerError, LedgerService
from app.organizations.models import MembershipStatus, OrganizationMember


class CallAuthorizationError(Exception):
    """A call will not be authorized, started or stopped, and this is why.

    Distinct from `contract.CallingError`, which is a *provider* refusal. This
    one is ours, decided from our own records, and it is the only kind a client
    can provoke by asking for something it is not entitled to.
    """

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


@dataclass(frozen=True)
class CallPreview:
    """What a call would cost and whether it could start, without committing.

    Deliberately reserves nothing. A customer scrolling a contact list would
    otherwise take and release a hold per contact, and a preview that moved money
    would make the balance flicker for no reason.
    """

    destination: DestinationDecision
    currency: str
    max_seconds: int
    max_charge_amount: Decimal
    rate_per_minute_amount: Decimal
    setup_amount: Decimal
    available_amount: Decimal
    fundable: bool
    #: True only when a provider route is actually enabled. A preview that said
    #: "yes" on a disabled route would be an availability claim the product
    #: cannot honour, and the amendment forbids exactly that.
    route_enabled: bool


@dataclass(frozen=True)
class StartInstruction:
    """Everything the client needs for one attempt, and nothing more.

    Note what is absent: no provider token, no connection id, no account
    reference. The client already holds a device-scoped session from
    `ClientSessionService`; this adds only the correlation that ties its call to
    this grant.

    `correlation` is echoed back by the provider in later events. It is an
    opaque pointer, and V01 §4 is explicit that such a value carries no integrity
    of its own — it may *name* an attempt but never authorize one, so the event
    path looks the attempt up and re-validates ownership (N7).
    """

    attempt_id: UUID
    destination_e164: str
    correlation: str
    max_seconds: int
    expires_at: datetime


class CallAuthorizationService:
    """Authorize, start, consume and stop. One session per call, always.

    `supported_countries` is passed in rather than read from a module constant so
    that the set of destinations this deployment sells is configuration, not a
    code change, and so a test can narrow it without monkeypatching policy.
    """

    def __init__(
        self,
        ledger: LedgerService,
        *,
        clock: Callable[[], datetime] = utc_now,
        supported_countries: frozenset[str] = frozenset({"NG"}),
        grant_ttl_seconds: int = 120,
        max_call_seconds: int = 3600,
        route_enabled: bool = False,
    ) -> None:
        self.ledger = ledger
        self.clock = clock
        self.supported_countries = supported_countries
        # Short by design. The grant is the window in which a copied token could
        # be used, and the client needs it only long enough to place one call.
        self.grant_ttl_seconds = grant_ttl_seconds
        self.max_call_seconds = max_call_seconds
        self.route_enabled = route_enabled

    # --- preview ----------------------------------------------------------

    def preview(
        self,
        session: Session,
        user: User,
        raw_destination: str,
        *,
        currency: str,
        organization_id: UUID | None = None,
        requested_seconds: int | None = None,
    ) -> CallPreview:
        """Price a call and report whether it could be funded. Commits nothing."""
        destination = self._classify(raw_destination)
        scope = self._resolve_scope(session, user, organization_id)
        rate, _tariff = self._rate_for(session, destination, currency)
        seconds = self._bounded_seconds(requested_seconds)
        max_charge = estimate_max_charge(
            seconds=seconds,
            per_minute_amount=rate.per_minute_amount,
            setup_amount=rate.setup_amount,
            minimum_seconds=rate.minimum_seconds,
            increment_seconds=rate.increment_seconds,
            currency=currency,
        )
        account = self._funding_account(session, scope, currency)
        available = self.ledger.available(session, account)
        return CallPreview(
            destination=destination,
            currency=currency,
            max_seconds=seconds,
            max_charge_amount=max_charge,
            rate_per_minute_amount=rate.per_minute_amount,
            setup_amount=rate.setup_amount,
            available_amount=available,
            fundable=available >= max_charge,
            route_enabled=self.route_enabled,
        )

    # --- authorize --------------------------------------------------------

    def authorize(
        self,
        session: Session,
        user: User,
        raw_destination: str,
        *,
        idempotency_key: str,
        currency: str,
        identity_e164: str,
        organization_id: UUID | None = None,
        identity_number_id: UUID | None = None,
        seller_legal_entity_id: UUID | None = None,
        entitlement_id: UUID | None = None,
        client_credential_id: UUID | None = None,
        origin_country: str | None = None,
        requested_seconds: int | None = None,
    ) -> CallAttempt:
        """Create exactly one durable grant, with the money already held.

        The ordering here is the whole safety argument and it is not negotiable:
        classify the destination, resolve who pays, pin the rate, **reserve**,
        then write the attempt. Reserving last would mean a grant existed for a
        moment that no money backed, and a crash in that moment leaves a row a
        client can start a billable call from.

        Replaying the same `idempotency_key` returns the original attempt
        unchanged — including its original destination. A replay that carried a
        *different* destination is refused rather than silently answered with the
        first one, because the two requests are not the same request and telling
        the caller otherwise hides a client bug that would eventually dial the
        wrong number.
        """
        existing = session.exec(
            select(CallAttempt).where(
                CallAttempt.owner_user_id == user.id,
                CallAttempt.idempotency_key == idempotency_key,
            )
        ).first()
        destination = self._classify(raw_destination)
        if existing is not None:
            if (
                existing.e164_destination != destination.e164
                or existing.currency != currency
                or existing.organization_id != organization_id
            ):
                raise CallAuthorizationError(
                    "idempotency_conflict",
                    "this key already authorized a different call",
                )
            return existing

        scope = self._resolve_scope(session, user, organization_id)
        rate, tariff = self._rate_for(session, destination, currency)
        seconds = self._bounded_seconds(requested_seconds)
        max_charge = estimate_max_charge(
            seconds=seconds,
            per_minute_amount=rate.per_minute_amount,
            setup_amount=rate.setup_amount,
            minimum_seconds=rate.minimum_seconds,
            increment_seconds=rate.increment_seconds,
            currency=currency,
        )
        if max_charge <= 0:
            # `ck_call_attempts_positive_bounds` would reject this anyway. Failing
            # here names the cause — a zero or missing rate — instead of surfacing
            # a constraint violation.
            raise CallAuthorizationError(
                "rate_unusable",
                "the published rate produces a zero maximum charge, so no "
                "meaningful exposure can be reserved",
            )
        credential = self._resolve_credential(session, user, client_credential_id)
        now = self.clock()
        expires_at = now + timedelta(seconds=self.grant_ttl_seconds)

        account = self._funding_account(session, scope, currency)
        try:
            reservation = self.ledger.reserve(
                session,
                account,
                max_charge,
                # Namespaced by attempt intent rather than by call, so a
                # top-up's business event and a call's can never collide.
                business_event_id=f"call-authorize:{user.id}:{idempotency_key}",
                expires_at=expires_at,
            )
        except LedgerError as exc:
            if exc.code == "insufficient_available_balance":
                raise CallAuthorizationError(
                    "insufficient_funds",
                    f"{max_charge} {currency} could not be reserved",
                ) from exc
            raise CallAuthorizationError("reservation_failed", exc.code) from exc

        attempt = CallAttempt(
            idempotency_key=idempotency_key,
            owner_user_id=user.id,
            organization_id=organization_id,
            payer_kind=(
                PayerKind.ORGANIZATION if organization_id else PayerKind.USER
            ),
            seller_legal_entity_id=seller_legal_entity_id,
            currency=currency,
            entitlement_id=self._validated_entitlement(session, scope, entitlement_id),
            e164_destination=destination.e164,
            destination_country=destination.country,
            destination_kind=destination.kind,
            origin_kind=OriginKind.INTERNET,
            origin_country=origin_country,
            identity_e164=identity_e164,
            identity_number_id=identity_number_id,
            tariff_id=tariff.id,
            tariff_version=tariff.version,
            rate_per_minute_amount=rate.per_minute_amount,
            rate_setup_amount=rate.setup_amount,
            rate_minimum_seconds=rate.minimum_seconds,
            rate_increment_seconds=rate.increment_seconds,
            max_seconds=seconds,
            max_charge_amount=max_charge,
            reservation_id=reservation.id,
            client_credential_id=None if credential is None else credential.id,
            state=AttemptState.AUTHORIZED,
            expires_at=expires_at,
            created_at=now,
        )
        session.add(attempt)
        session.flush()
        return attempt

    # --- start ------------------------------------------------------------

    def start(
        self,
        session: Session,
        user: User,
        attempt_id: UUID,
        *,
        device_id: str | None = None,
    ) -> StartInstruction:
        """Hand the client its instruction, or refuse. Converges on repetition.

        Every refusal here is one of V01's negative cases, and each is checked
        against the stored row rather than against the request: ownership (N2),
        expiry and prior consumption (N3), and the device the grant was bound to
        (N2 again, from the other direction — a second device of the same user
        presenting somebody else's attempt).
        """
        attempt = self._owned(session, user, attempt_id)
        if attempt.state in TERMINAL_ATTEMPT_STATES:
            raise CallAuthorizationError(
                "attempt_not_startable", f"attempt is {attempt.state.value}"
            )
        # A consumed grant is deliberately *not* refused here. The client that
        # already started this call and lost the response asks again, and the
        # honest answer is the same instruction — the grant is spent either way,
        # and a refusal would make an ordinary retry look like an error. A grant
        # spent on a call that has since ended is caught by the terminal-state
        # check above.
        if _aware(attempt.expires_at) <= self.clock():
            raise CallAuthorizationError(
                "attempt_expired", "this authorization has expired"
            )
        if attempt.client_credential_id is not None:
            credential = session.get(
                CallingClientCredential, attempt.client_credential_id
            )
            if (
                credential is None
                or credential.state is not CredentialState.ACTIVE
                or (device_id is not None and credential.device_id != device_id)
            ):
                raise CallAuthorizationError(
                    "device_not_authorized",
                    "this grant is bound to a different device credential",
                )
        if not self.route_enabled:
            # The honest refusal. V01's go/no-go is NO-GO for a live route until
            # B1–B5 close, and returning a startable instruction would let a
            # client believe otherwise.
            raise CallAuthorizationError(
                "calling_route_disabled",
                "outbound internet calling is not enabled on this deployment",
            )
        return StartInstruction(
            attempt_id=attempt.id,
            destination_e164=attempt.e164_destination,
            correlation=str(attempt.id),
            max_seconds=attempt.max_seconds,
            expires_at=attempt.expires_at,
        )

    # --- consume ----------------------------------------------------------

    def consume_grant(self, session: Session, attempt_id: UUID) -> bool:
        """Spend the grant, exactly once, atomically. Returns whether we won.

        A conditional UPDATE and not a read-then-write. Two webhooks for the same
        parked call arriving on two workers would both read `grant_consumed_at IS
        NULL`, both decide to proceed, and both dial — one grant, two funded
        calls. Here the second one updates zero rows and is told so.

        Expiry is part of the same predicate rather than a separate check before
        it, because a check-then-update leaves a window in which the grant
        expires between the two statements.
        """
        now = self.clock()
        result = cast(
            "CursorResult[Any]",
            session.execute(
                update(CallAttempt)
                .where(
                    col(CallAttempt.id) == attempt_id,
                    col(CallAttempt.grant_consumed_at).is_(None),
                    col(CallAttempt.state) == AttemptState.AUTHORIZED,
                    col(CallAttempt.expires_at) > now,
                )
                .values(grant_consumed_at=now, state=AttemptState.ACCEPTED)
            ),
        )
        return result.rowcount == 1

    # --- state convergence -------------------------------------------------

    def advance(
        self,
        session: Session,
        attempt: CallAttempt,
        target: AttemptState,
        *,
        end_reason: str | None = None,
        answered_at: datetime | None = None,
    ) -> bool:
        """Move an attempt forward only. Returns whether anything changed.

        Provider events are duplicated, delayed and reordered (V01 §4), so a
        transition is applied only if it ranks above the current state. A
        `call.answered` that overtakes a `call.hangup` would otherwise resurrect a
        finished call and produce a negative duration (N10).

        `UNKNOWN` is the exception in the other direction: it ranks below
        everything, so a real observation always supersedes it, and it is set by
        the reconciliation path rather than by this method.
        """
        if ATTEMPT_STATE_RANK[target] <= ATTEMPT_STATE_RANK[attempt.state]:
            return False
        attempt.state = target
        if answered_at is not None and attempt.answered_at is None:
            attempt.answered_at = answered_at
        if target in TERMINAL_ATTEMPT_STATES:
            attempt.ended_at = attempt.ended_at or self.clock()
            attempt.end_reason = end_reason or attempt.end_reason
        session.add(attempt)
        session.flush()
        return True

    def mark_unknown(
        self, session: Session, attempt: CallAttempt, reason: str
    ) -> CallAttempt:
        """Record that we lost track of a call, without releasing anything.

        Invariant 8: a reservation stays held until every known supplier
        liability is final. An unknown outcome is the case where liability is
        least known, so this deliberately does not touch the hold — releasing it
        here is how a call that is still connected stops being funded.
        """
        if attempt.state not in TERMINAL_ATTEMPT_STATES:
            attempt.state = AttemptState.UNKNOWN
            attempt.end_reason = reason
            session.add(attempt)
            session.flush()
        return attempt

    # --- stop and scoped reads --------------------------------------------

    def stop(
        self, session: Session, user: User, attempt_id: UUID, *, reason: str = "stopped"
    ) -> CallAttempt:
        """Ask for an attempt to end. Always permitted, even on a closed route.

        Termination is deliberately not gated on `route_enabled`. The assignment
        is explicit: *disabling new calling must not disable termination or
        financial recovery.* A deployment that switched the route off mid-call
        would otherwise be unable to hang up the calls it had already started.

        This records intent; the provider hangup is issued by the lifecycle
        service against a durable operation, so a lost hangup response
        reconciles rather than retries.
        """
        attempt = self._owned(session, user, attempt_id)
        if attempt.state in TERMINAL_ATTEMPT_STATES:
            return attempt
        attempt.end_reason = reason
        session.add(attempt)
        session.flush()
        return attempt

    def get(self, session: Session, user: User, attempt_id: UUID) -> CallAttempt:
        return self._owned(session, user, attempt_id)

    def history(
        self,
        session: Session,
        user: User,
        *,
        organization_id: UUID | None = None,
        limit: int = 50,
    ) -> list[CallAttempt]:
        """Calls this caller may see, in this scope, newest first.

        Scope is a filter on the query, never a check applied to results. An
        organization's history is its own calls, and a personal history excludes
        work calls rather than showing them unlabelled — the same call must not
        appear in both, because the payer differs and so does who may read it.
        """
        statement = select(CallAttempt).where(CallAttempt.owner_user_id == user.id)
        if organization_id is None:
            statement = statement.where(col(CallAttempt.organization_id).is_(None))
        else:
            self._resolve_scope(session, user, organization_id)
            statement = statement.where(
                CallAttempt.organization_id == organization_id
            )
        return list(
            session.exec(
                statement.order_by(col(CallAttempt.created_at).desc()).limit(limit)
            ).all()
        )

    def organization_history(
        self, session: Session, organization_id: UUID, *, limit: int = 50
    ) -> list[CallAttempt]:
        """Every member's work calls in one organization, for an authorized admin.

        Separate from `history` because the authorization is different: this one
        is a tenant-wide read and its caller must have been authorized as an
        administrator by `app/organizations` before reaching here.
        """
        return list(
            session.exec(
                select(CallAttempt)
                .where(CallAttempt.organization_id == organization_id)
                .order_by(col(CallAttempt.created_at).desc())
                .limit(limit)
            ).all()
        )

    # --- internals ---------------------------------------------------------

    def _classify(self, raw_destination: str) -> DestinationDecision:
        try:
            return classify_destination(
                raw_destination, supported_countries=self.supported_countries
            )
        except DestinationRefused as exc:
            raise CallAuthorizationError(exc.code, exc.detail) from exc

    def _bounded_seconds(self, requested: int | None) -> int:
        seconds = self.max_call_seconds if requested is None else requested
        if seconds <= 0:
            raise CallAuthorizationError("invalid_duration")
        return min(seconds, self.max_call_seconds)

    def _resolve_scope(
        self, session: Session, user: User, organization_id: UUID | None
    ) -> _Scope:
        """Establish who pays before anything is priced or held.

        A personal call needs no membership at all — the calling amendment
        requires internet calling to work for a customer who belongs to no
        organization, and requiring one here would make browser calling an
        enterprise privilege.
        """
        if organization_id is None:
            return _Scope(user_id=user.id, organization_id=None)
        membership = session.exec(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user.id,
            )
        ).first()
        if membership is None or membership.status is not MembershipStatus.ACTIVE:
            # Identical refusal for "no such organization" and "not yours", so
            # the response cannot be used to discover that an organization
            # exists (the rule chunk 07 established in AC-29.4).
            raise CallAuthorizationError(
                "not_a_member", "no active membership for this organization"
            )
        return _Scope(user_id=user.id, organization_id=organization_id)

    def _funding_account(
        self, session: Session, scope: _Scope, currency: str
    ) -> LedgerAccount:
        if scope.organization_id is not None:
            return self.ledger.account(
                session,
                currency,
                AccountKind.SERVICE_CREDIT,
                OwnerKind.ORGANIZATION,
                owner_organization_id=scope.organization_id,
            )
        return self.ledger.account(
            session,
            currency,
            AccountKind.SERVICE_CREDIT,
            OwnerKind.USER,
            owner_user_id=scope.user_id,
        )

    def _rate_for(
        self, session: Session, destination: DestinationDecision, currency: str
    ) -> tuple[TariffRate, Tariff]:
        """Find the one published internet-voice rate that covers this call.

        `OriginKind.INTERNET` is passed explicitly and `select_rate` never falls
        back across origin kinds, so a carrier roaming rate can never price an
        internet call. Chunk 09 documents why: the two cost us different amounts,
        and substituting one prices a call at a number describing a different
        call.
        """
        now = self.clock()
        tariffs = session.exec(
            select(Tariff)
            .join(Product, Product.id == Tariff.product_id)  # type: ignore[arg-type]
            .where(
                Tariff.currency == currency,
                Tariff.status == PublicationStatus.PUBLISHED,
                Product.active.is_(True),  # type: ignore[attr-defined]
                Product.kind != ProductKind.DATA,
            )
        ).all()
        live = [
            tariff
            for tariff in tariffs
            if _aware(tariff.effective_from) <= now
            and (tariff.effective_to is None or _aware(tariff.effective_to) > now)
        ]
        for tariff in sorted(live, key=lambda item: -item.version):
            rates = list(
                session.exec(
                    select(TariffRate).where(TariffRate.tariff_id == tariff.id)
                ).all()
            )
            try:
                rate = select_rate(
                    rates,
                    OriginKind.INTERNET,
                    None,
                    destination.country,
                    destination.kind,
                )
            except RateNotFoundError:
                continue
            return rate, tariff
        raise CallAuthorizationError(
            "rate_unavailable",
            f"no published {currency} internet rate covers "
            f"{destination.country}/{destination.kind.value}",
        )

    def _resolve_credential(
        self, session: Session, user: User, credential_id: UUID | None
    ) -> CallingClientCredential | None:
        if credential_id is None:
            return None
        credential = session.get(CallingClientCredential, credential_id)
        if (
            credential is None
            or credential.user_id != user.id
            or credential.state is not CredentialState.ACTIVE
        ):
            raise CallAuthorizationError(
                "device_not_authorized", "no active credential for this device"
            )
        return credential

    def _validated_entitlement(
        self, session: Session, scope: _Scope, entitlement_id: UUID | None
    ) -> UUID | None:
        """Bind an allowance only if it is this caller's to draw on.

        Nullable on purpose: an internet call can be funded from ledger credit
        with no allowance behind it, because there is no eSIM and therefore need
        not be a package. What is refused is naming *somebody else's*
        entitlement, which is the ownership half of N2.
        """
        if entitlement_id is None:
            return None
        entitlement = session.get(Entitlement, entitlement_id)
        if entitlement is None or entitlement.holder_user_id != scope.user_id:
            raise CallAuthorizationError(
                "entitlement_not_available", "that allowance is not yours to use"
            )
        return entitlement.id

    def _owned(self, session: Session, user: User, attempt_id: UUID) -> CallAttempt:
        """Load an attempt that belongs to this caller, or refuse identically.

        `not_found` for somebody else's attempt as well as for one that does not
        exist. A distinct "forbidden" would confirm that an id is real, which is
        enough to enumerate other customers' calls.
        """
        attempt = session.get(CallAttempt, attempt_id)
        if attempt is None or attempt.owner_user_id != user.id:
            raise CallAuthorizationError("attempt_not_found")
        return attempt


@dataclass(frozen=True)
class _Scope:
    user_id: UUID
    organization_id: UUID | None


def _aware(moment: datetime) -> datetime:
    """SQLite hands back naive datetimes; PostgreSQL does not. Compare safely."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def reservation_for(session: Session, attempt: CallAttempt) -> Reservation:
    reservation = session.get(Reservation, attempt.reservation_id)
    if reservation is None:  # pragma: no cover - FK guarantees this
        raise CallAuthorizationError("reservation_missing")
    return reservation
