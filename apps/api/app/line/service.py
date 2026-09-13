"""Assembling My Line, and guarding who may see it (US-38, chunk 20).

Chunks 15–17 built the connectivity lifecycle, usage reconciliation and spending
controls as services with no HTTP surface. This joins them into the one view a
customer actually asks for — *what is my number, does it work, how much is left,
and what do I do next* — without inventing a single fact along the way.

Two things this module refuses to do, both of which would be easy and wrong:

**It never derives a state from a neighbouring one.** Network attachment is not
inferred from activation, voice capability is not inferred from the plan having
voice in it, and "installed" is only ever what a device reported. Chunk 05 split
these columns apart precisely because they disagree in the field, and a view
layer that recombines them undoes that at exactly the moment a support agent is
reading it.

**It never widens ownership.** Every entry point resolves the entitlement
through `holder_user_id` and answers `line_not_found` for somebody else's line,
rather than 403 — the difference between "does not exist" and "is not yours" is
an oracle for whether an id is real. Chunk 19's review found this exact class of
defect in the checkout routes; it is not repeated here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlmodel import Session, col, select

from app.auth.models import User
from app.catalog.market import (
    DeviceEligibilityRule,
    NumberAssignment,
    NumberPolicy,
    NumberType,
    PublicationStatus,
)
from app.catalog.models import Product
from app.catalog.tariffs import OriginKind, Tariff, TariffRate
from app.connectivity.credentials import CredentialVault
from app.connectivity.models import (
    ActivationState,
    AssignedNumber,
    CarrierLine,
    Entitlement,
    EsimActivationCredential,
    EsimInstallation,
    InstallationState,
)
from app.connectivity.service import ConnectivityService
from app.controls.models import (
    SPENDABLE_TOP_UP_STATES,
    EntitlementTopUp,
    SpendingControl,
    TopUpState,
)
from app.controls.service import ControlService
from app.line.schemas import (
    AssignedNumberView,
    CallDestinationView,
    CallingView,
    InstallationView,
    LineDelivery,
    LineDetailResponse,
    LineStateView,
    LineSummary,
    NumberStatus,
    RestrictionView,
    TariffView,
    TopUpView,
    UsageView,
)
from app.money import format_money
from app.orders.models import Order, OrderItem
from app.usage.service import UsageService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class LineError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


@dataclass(frozen=True)
class LineContext:
    """One line and everything hanging off it, resolved once.

    Assembled in a single place so that the detail view, the grant endpoint and
    the installation confirmation all agree about what they are looking at — and
    all pass through the same ownership check on the way in.
    """

    entitlement: Entitlement
    item: OrderItem
    order: Order
    product: Product
    installation: EsimInstallation | None
    carrier_line: CarrierLine | None
    number: AssignedNumber | None
    requires_esim: bool
    #: Whether the *plan* includes a number at all. The carrier line's voice
    #: flag is a weaker proxy: a voice-capable line on a data-only plan is still
    #: a plan with no number, and the policy is where that is recorded.
    includes_number: bool


class LineViewService:
    def __init__(
        self,
        usage: UsageService,
        controls: ControlService | None = None,
        vault: CredentialVault | None = None,
        connectivity: ConnectivityService | None = None,
        clock: Callable[[], datetime] = utc_now,
        internet_dialer_enabled: bool = False,
    ) -> None:
        self.usage = usage
        self.controls = controls
        self.vault = vault
        self.connectivity = connectivity
        self.clock = clock
        self.internet_dialer_enabled = internet_dialer_enabled

    # --- resolution and ownership -----------------------------------------

    def context(
        self, session: Session, entitlement_id: UUID, user: User
    ) -> LineContext:
        """Resolve one line, for its holder only.

        `holder_user_id` rather than the order's payer: an organization buys for
        somebody, and the person holding the line is the one who installs it.
        The payer seeing another person's activation material would be exactly
        the leak chunk 15's vault exists to prevent.
        """
        entitlement = session.get(Entitlement, entitlement_id)
        if entitlement is None or entitlement.holder_user_id != user.id:
            raise LineError("line_not_found")
        return self._context_for(session, entitlement)

    def _context_for(
        self, session: Session, entitlement: Entitlement
    ) -> LineContext:
        item = session.get(OrderItem, entitlement.order_item_id)
        if item is None:  # pragma: no cover - FK guarantees this
            raise LineError("line_not_found")
        order = session.get(Order, item.order_id)
        product = session.get(Product, entitlement.product_id)
        if order is None or product is None:  # pragma: no cover - FK guarantees
            raise LineError("line_not_found")

        installation = session.exec(
            select(EsimInstallation).where(
                EsimInstallation.entitlement_id == entitlement.id
            )
        ).first()
        carrier_line = session.exec(
            select(CarrierLine).where(CarrierLine.entitlement_id == entitlement.id)
        ).first()
        number = (
            session.exec(
                select(AssignedNumber)
                .where(
                    AssignedNumber.carrier_line_id == carrier_line.id,
                    col(AssignedNumber.released_at).is_(None),
                )
                .order_by(col(AssignedNumber.assigned_at).desc())
            ).first()
            if carrier_line is not None
            else None
        )
        rule = session.exec(
            select(DeviceEligibilityRule).where(
                DeviceEligibilityRule.product_id == entitlement.product_id
            )
        ).first()
        policy = session.exec(
            select(NumberPolicy).where(
                NumberPolicy.product_id == entitlement.product_id
            )
        ).first()
        return LineContext(
            entitlement=entitlement,
            item=item,
            order=order,
            product=product,
            installation=installation,
            carrier_line=carrier_line,
            number=number,
            # No rule is not "no requirement" — chunk 15's reasoning. But for a
            # *view*, existing carrier resources are a stronger signal than a
            # missing rule, so they win below in `_delivery`.
            requires_esim=rule.requires_esim if rule is not None else True,
            # No policy recorded is treated as "no number". Chunk 09's rule:
            # a product whose number policy nobody wrote is not a product that
            # quietly promises one.
            includes_number=(
                policy is not None
                and policy.number_type is not NumberType.NONE
                and policy.assignment is not NumberAssignment.NONE
            ),
        )

    # --- the list ----------------------------------------------------------

    def lines(self, session: Session, user: User) -> list[LineSummary]:
        """Every line this account holds.

        Resolved one at a time through `_context_for` rather than as a batched
        join. A consumer holds a handful of lines, and sharing the resolution
        with the detail view is worth more here than the round trips it costs —
        two code paths that could disagree about what a line *is* would be a
        worse problem than this one. An enterprise listing, where the counts are
        different, is chunk 24's and should not reuse this.
        """
        entitlements = session.exec(
            select(Entitlement)
            .where(Entitlement.holder_user_id == user.id)
            .order_by(col(Entitlement.granted_at).desc())
        ).all()
        summaries: list[LineSummary] = []
        for entitlement in entitlements:
            context = self._context_for(session, entitlement)
            delivery = self._delivery(context)
            status, number = self._number(context, delivery)
            summary_expiry = self._effective_expiry(session, entitlement)
            summaries.append(
                LineSummary(
                    entitlement_id=entitlement.id,
                    order_id=context.order.id,
                    order_reference=context.order.reference,
                    product_name=context.product.name,
                    delivery=delivery,
                    number_status=status,
                    e164=number.e164 if number else None,
                    activation_state=(
                        context.carrier_line.activation_state.value
                        if context.carrier_line
                        else None
                    ),
                    installation_state=(
                        context.installation.installation_state.value
                        if context.installation
                        else None
                    ),
                    ready_to_use=self._ready(context, delivery, summary_expiry),
                    expires_at=summary_expiry,
                    expired=summary_expiry is not None
                    and summary_expiry <= self.clock(),
                )
            )
        return summaries

    # --- the detail --------------------------------------------------------

    def detail(self, session: Session, context: LineContext) -> LineDetailResponse:
        delivery = self._delivery(context)
        status, number = self._number(context, delivery)
        allowance = (
            self.controls.allowance(session, context.entitlement)
            if self.controls is not None
            else self.usage.allowance(session, context.entitlement)
        )
        expires_at = _aware(allowance.expires_at)
        now = self.clock()

        return LineDetailResponse(
            entitlement_id=context.entitlement.id,
            order_id=context.order.id,
            order_reference=context.order.reference,
            order_item_id=context.item.id,
            product_id=context.product.id,
            product_name=context.product.name,
            delivery=delivery,
            ready_to_use=self._ready(context, delivery, expires_at),
            number_status=status,
            assigned_number=(
                AssignedNumberView(
                    e164=number.e164,
                    country=number.country,
                    assigned_at=_aware(number.assigned_at) or now,
                )
                if number is not None
                else None
            ),
            installation=self._installation(session, context, delivery),
            line=self._line_state(context),
            usage=UsageView(
                data_bytes_total=allowance.data_bytes_total,
                data_bytes_used=allowance.data_bytes_used,
                data_bytes_remaining=allowance.data_bytes_remaining,
                voice_seconds_total=allowance.voice_seconds_total,
                voice_seconds_used=allowance.voice_seconds_used,
                voice_seconds_remaining=allowance.voice_seconds_remaining,
                observed_at=_aware(allowance.observed_at),
                freshness=allowance.freshness.value,
                has_provisional=allowance.has_provisional,
                expires_at=expires_at,
                expired=expires_at is not None and expires_at <= now,
            ),
            restriction=self._restriction(session, context),
            top_ups=self._top_ups(session, context),
            tariff=self._tariff(session, context),
            calling=self._calling(context, delivery),
        )

    # --- the parts ---------------------------------------------------------

    @staticmethod
    def _delivery(context: LineContext) -> LineDelivery:
        """What kind of service this is, from what actually exists.

        Existing carrier resources win over the catalogue rule, matching chunk
        18's `ConsumerService._summarize`. Two views of the same account
        disagreeing about whether a service needs installing would be worse than
        either answer on its own.
        """
        if context.carrier_line is not None or context.installation is not None:
            return LineDelivery.CARRIER_ESIM
        return (
            LineDelivery.CARRIER_ESIM
            if context.requires_esim
            else LineDelivery.INTERNET
        )

    @staticmethod
    def _number(
        context: LineContext, delivery: LineDelivery
    ) -> tuple[NumberStatus, AssignedNumber | None]:
        """Three answers, because a blank number field means three things.

        An internet-calling grant has no number by design; a carrier line that
        has not been assigned one yet is waiting; and a data-only plan never
        gets one. Rendering all three as an empty space makes the first two
        indistinguishable from a bug.
        """
        if context.number is not None:
            return NumberStatus.ASSIGNED, context.number
        if delivery is LineDelivery.INTERNET:
            return NumberStatus.NOT_INCLUDED, None
        if not context.includes_number:
            # The plan never promised one. Not a delay.
            return NumberStatus.NOT_INCLUDED, None
        return NumberStatus.PENDING, None

    def _installation(
        self, session: Session, context: LineContext, delivery: LineDelivery
    ) -> InstallationView | None:
        if delivery is LineDelivery.INTERNET or context.installation is None:
            # Null rather than a `not_installed` view: there is no profile, so
            # reporting one as uninstalled is a false negative, not a fact.
            return None

        credential = session.exec(
            select(EsimActivationCredential).where(
                EsimActivationCredential.esim_installation_id
                == context.installation.id
            )
        ).first()

        available, reason = self._credential_availability(credential)
        one_time_use = credential.one_time_use if credential is not None else True
        delivery_count = credential.delivery_count if credential is not None else 0

        return InstallationView(
            state=context.installation.installation_state.value,
            installed_at=_aware(context.installation.installed_at),
            profile_released_at=_aware(context.installation.profile_released_at),
            credential_available=available,
            credential_unavailable_reason=reason,
            delivery_count=delivery_count,
            one_time_use=one_time_use,
            # The honest answer, and it is no. Telnyx documents that a
            # downloaded eSIM profile cannot be re-downloaded — a lost or
            # replaced device needs a fresh purchase. Offering a "reinstall"
            # button would be offering something the supplier cannot do.
            reinstall_available=False,
            reinstall_blocked_reason=(
                "one_time_profile" if one_time_use else "supplier_reissue_unproven"
            ),
        )

    def _credential_availability(
        self, credential: EsimActivationCredential | None
    ) -> tuple[bool, str | None]:
        if self.vault is None:
            # Fail closed and say which way. A deployment with no activation
            # key must not silently look like a deployment with no profiles.
            return False, "material_key_unavailable"
        if credential is None:
            return False, "profile_not_issued"
        if credential.one_time_use and credential.delivery_count > 0:
            # Still deliverable — the row is there and the vault can unseal it —
            # but the customer has already revealed a one-time code, and the app
            # has to warn rather than hand it over as if nothing happened.
            return True, "already_delivered"
        return True, None

    @staticmethod
    def _line_state(context: LineContext) -> LineStateView | None:
        line = context.carrier_line
        if line is None:
            return None
        return LineStateView(
            carrier=line.carrier,
            activation_state=line.activation_state.value,
            network_state=line.network_state.value,
            network_state_observed_at=_aware(line.network_state_observed_at),
            provider_status=line.provider_status,
            provider_status_observed_at=_aware(line.provider_status_observed_at),
            voice_enabled=line.voice_enabled,
            voice_enabled_observed_at=_aware(line.voice_enabled_observed_at),
        )

    def _restriction(
        self, session: Session, context: LineContext
    ) -> RestrictionView | None:
        line = context.carrier_line
        if line is None:
            return None
        control = session.exec(
            select(SpendingControl).where(SpendingControl.carrier_line_id == line.id)
        ).first()
        suspended = line.activation_state is ActivationState.SUSPENDED
        if control is None:
            # A line with no control row has nothing enforcing a cap. Saying so
            # is the point of chunk 17: `none` is an honest state, not a gap.
            return RestrictionView(
                suspended=suspended,
                enforcement="none",
                control_state="requested",
                requested_limit_bytes=None,
                confirmed_limit_bytes=None,
                detail=None,
            )
        return RestrictionView(
            suspended=suspended,
            enforcement=control.enforcement.value,
            control_state=control.state.value,
            requested_limit_bytes=control.requested_limit_bytes,
            confirmed_limit_bytes=control.confirmed_limit_bytes,
            detail=control.detail,
        )

    @staticmethod
    def _top_ups(session: Session, context: LineContext) -> TopUpView:
        rows = session.exec(
            select(EntitlementTopUp).where(
                EntitlementTopUp.entitlement_id == context.entitlement.id
            )
        ).all()
        applied = [row for row in rows if row.state in SPENDABLE_TOP_UP_STATES]
        pending = [
            row
            for row in rows
            if row.state
            in (
                TopUpState.RESERVED,
                TopUpState.PAID,
                TopUpState.PROVISIONING,
                TopUpState.OUTCOME_UNKNOWN,
            )
        ]
        return TopUpView(
            applied_data_bytes=sum(row.data_bytes for row in applied),
            applied_voice_seconds=sum(row.voice_seconds for row in applied),
            applied_extra_days=sum(row.extends_days for row in applied),
            pending_count=len(pending),
        )

    def _tariff(self, session: Session, context: LineContext) -> TariffView | None:
        """What this line's calls cost, from the published tariff only.

        Draft and superseded tariffs are excluded, and an unpriced destination
        is simply absent rather than shown at zero: a destination the tariff
        does not price is one this plan cannot price, and therefore one it must
        not imply it covers.
        """
        now = self.clock()
        tariffs = session.exec(
            select(Tariff).where(
                Tariff.product_id == context.product.id,
                Tariff.status == PublicationStatus.PUBLISHED,
            )
        ).all()
        live = [
            tariff
            for tariff in tariffs
            if (_aware(tariff.effective_from) or now) <= now
            and (
                tariff.effective_to is None
                or (_aware(tariff.effective_to) or now) > now
            )
        ]
        if not live:
            return None
        tariff = max(live, key=lambda row: row.version)
        rates = session.exec(
            select(TariffRate)
            .where(
                TariffRate.tariff_id == tariff.id,
                TariffRate.origin_kind == (
                    OriginKind.INTERNET
                    if self._delivery(context) is LineDelivery.INTERNET
                    else OriginKind.CARRIER_VISITED_NETWORK
                ),
            )
            .order_by(col(TariffRate.destination_country))
        ).all()
        return TariffView(
            version=tariff.version,
            currency=tariff.currency,
            destinations=[
                CallDestinationView(
                    country=rate.destination_country,
                    origin_country=rate.origin_country,
                    destination_kind=rate.destination_kind.value,
                    # Full stored precision: a per-minute rate rounded to the
                    # currency's scale cannot represent a fraction of a kobo,
                    # and a metered charge built from it is wrong every minute.
                    per_minute_amount=str(rate.per_minute_amount),
                    setup_amount=format_money(rate.setup_amount, tariff.currency),
                    increment_seconds=rate.increment_seconds,
                    minimum_seconds=rate.minimum_seconds,
                )
                for rate in rates
            ],
        )

    def _calling(self, context: LineContext, delivery: LineDelivery) -> CallingView:
        """Native and internet calling, reported separately and never inferred.

        The approved calling amendment: these are distinct capabilities, and
        launching the phone dialer says nothing about which SIM was chosen,
        whether the line attached, or whether a call happened. So native
        availability is the carrier's observed `voice_enabled` on this line —
        not the product having voice in it — and the internet dialer stays off
        until V04 is accepted and enabled.
        """
        line = context.carrier_line
        if delivery is LineDelivery.INTERNET:
            native_available, native_reason = False, "no_carrier_line"
        elif line is None:
            native_available, native_reason = False, "line_not_provisioned"
        elif not line.voice_enabled:
            native_available, native_reason = False, "voice_not_enabled"
        elif line.activation_state is not ActivationState.ACTIVE:
            native_available, native_reason = False, "line_not_active"
        else:
            native_available, native_reason = True, None

        return CallingView(
            native_available=native_available,
            native_unavailable_reason=native_reason,
            internet_dialer_enabled=self.internet_dialer_enabled,
            internet_dialer_reason=(
                None if self.internet_dialer_enabled else "v04_not_accepted"
            ),
            # Selection only matters where there is a carrier line to select.
            requires_line_selection=delivery is LineDelivery.CARRIER_ESIM,
        )

    # --- installation ------------------------------------------------------

    def credential_for(
        self, session: Session, context: LineContext
    ) -> EsimActivationCredential:
        """The sealed profile for this line, or a reason there is none.

        Separate from `_installation` because the view tolerates absence and
        this does not: a caller here is about to be handed material, and every
        way that can fail has to be a distinct refusal rather than an empty
        response the client renders as a blank screen.
        """
        if self.vault is None:
            raise LineError(
                "installation_material_unavailable",
                "no activation-material key is configured; delivering the "
                "profile in the clear is not the fallback",
            )
        if context.installation is None:
            raise LineError("profile_not_issued")
        credential = session.exec(
            select(EsimActivationCredential).where(
                EsimActivationCredential.esim_installation_id
                == context.installation.id
            )
        ).first()
        if credential is None:
            raise LineError("profile_not_issued")
        return credential

    def record_installation_report(
        self, session: Session, context: LineContext, installed: bool
    ) -> EsimInstallation:
        """What the device says happened, in both directions.

        A `false` report is recorded rather than discarded. An install that
        failed, on a record still reading `installed`, is how a customer gets
        told their line is ready while nothing is on the phone — and it is the
        state a support agent would then have to disbelieve.

        Nothing here touches activation. The carrier decides that, and a profile
        landing on a handset is not the carrier agreeing to carry its traffic.
        """
        if context.installation is None:
            raise LineError("profile_not_issued")
        if installed:
            if self.connectivity is None:  # pragma: no cover - wired in main
                raise LineError("installation_reporting_unavailable")
            return self.connectivity.record_device_installation(
                session, context.installation
            )
        context.installation.installation_state = InstallationState.NOT_INSTALLED
        context.installation.installed_at = None
        session.add(context.installation)
        session.flush()
        return context.installation

    # --- derived booleans --------------------------------------------------

    def _effective_expiry(
        self, session: Session, entitlement: Entitlement
    ) -> datetime | None:
        """The expiry including any extension a top-up bought.

        Reading `entitlements.expires_at` directly would expire a line whose
        owner has already paid to keep it, which is the worst possible moment to
        get this wrong.
        """
        if self.controls is not None:
            return _aware(self.controls.allowance(session, entitlement).expires_at)
        return _aware(entitlement.expires_at)

    def _ready(
        self,
        context: LineContext,
        delivery: LineDelivery,
        expires_at: datetime | None,
    ) -> bool:
        """Installed by the device **and** active at the carrier. Never one of them.

        Payment is not part of this, and neither is provisioning: the customer
        asking "can I use it" is asking about the phone and the network, and
        both have to have said yes.

        `expires_at` is passed in rather than read off the entitlement because a
        top-up can extend it. Reading the column directly would report a line as
        unusable while its owner has already paid to keep it, and would disagree
        with the `usage.expired` flag in the same response.
        """
        if expires_at is not None and expires_at <= self.clock():
            return False
        if delivery is LineDelivery.INTERNET:
            return True
        return (
            context.installation is not None
            and context.installation.installation_state is InstallationState.INSTALLED
            and context.carrier_line is not None
            and context.carrier_line.activation_state is ActivationState.ACTIVE
        )
