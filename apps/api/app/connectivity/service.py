"""Line lifecycle: provisioning, adoption, state mapping and recovery.

US-35, chunk 15. This is where a supplier's vocabulary becomes ours, and where
chunk 11's durable-recovery machinery gets a real supplier to drive.

Nothing here is a second copy of chunk 11. `FulfilmentService` already owns
attempt identity, the record-before-dispatch ordering, `OUTCOME_UNKNOWN` and
reconciliation-against-the-same-reference; this module wraps a
`ConnectivityAdapter` in the `SupplierClient` shape that machinery expects and
adds what is specific to connectivity: what a line *is* once it exists.

## The four states stay four states

`connectivity/models.py` explains why `provisioning_state`, `installation_state`,
`activation_state` and `network_state` are separate columns. This module is
where they could quietly stop being separate, because a supplier hands us one
status and it is tempting to fan it out. So, explicitly:

- Buying a profile sets **provisioning**. It says nothing about installation.
- A supplier releasing a profile for download sets `profile_released_at`. It is
  **not** `installed_at`. Telnyx cannot see a handset; only a device report can
  set installation, and `record_device_installation` is the only thing that does.
- A supplier's `enabled` sets **activation**. It does not set network state.
- **Network state is only ever set from an observation.** `NetworkState.UNKNOWN`
  is the default and stays the default until something actually observes an
  attachment. Reporting "attached" because we activated the line is how a
  support agent ends up telling somebody their phone works when it does not.

## The operation reference

Chunk 11's idempotency key names a request: `order-item:<id>:attempt:<n>`.
Telnyx's only reconciliation handle is a free-form tag, and the contract record
requires that tag to be a uuid rather than anything human-meaningful, because
tags carry no uniqueness guarantee and a tidy name is a name somebody else can
collide with.

`operation_reference` bridges the two with a uuid5 of the idempotency key. It is
deterministic — so it can be recomputed from the persisted attempt during
reconciliation, which is the entire point — and opaque to the supplier.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlmodel import Session, col, select

from app.auth.models import utc_now
from app.catalog.models import ProductAllowance
from app.connectivity.contract import (
    ActivationCredential,
    Capability,
    ConnectivityAdapter,
    ConnectivityError,
    ConnectivityOutcomeUnknown,
    ProviderLine,
    ProviderLineState,
)
from app.connectivity.credentials import CredentialVault
from app.connectivity.models import (
    ActivationState,
    AssignedNumber,
    CarrierLine,
    CarrierLineAction,
    Entitlement,
    EsimInstallation,
    InstallationState,
    LineActionKind,
    LineActionState,
    NetworkState,
)
from app.fulfilment.models import AttemptOutcome, SupplierAttempt
from app.fulfilment.service import (
    FulfilmentService,
    SupplierResult,
    SupplierTimeout,
)
from app.orders.models import OrderItem, ProvisioningState

#: Namespace for deriving a supplier-facing operation uuid from our own
#: idempotency key. Fixed forever: changing it would make every historical
#: attempt unreconcilable, because the tag it was purchased under could no
#: longer be recomputed.
_OPERATION_NAMESPACE = uuid5(NAMESPACE_URL, "https://damdam.app/connectivity/operation")


class ConnectivityServiceError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


def operation_reference(idempotency_key: str) -> UUID:
    """Our attempt key as a uuid the supplier can carry.

    Deterministic on purpose. Reconciliation happens after a crash, from a row
    and nothing else, and a random uuid would have had to be stored alongside —
    one more thing that can be missing exactly when it is needed.
    """
    return uuid5(_OPERATION_NAMESPACE, idempotency_key)


class ConnectivitySupplierClient:
    """A `ConnectivityAdapter` in the shape chunk 11's recovery expects.

    The lines the supplier returned are kept on the instance rather than
    squeezed into `SupplierResult`, because `SupplierResult` is chunk 11's type
    and it is about *whether the request landed*, not about what connectivity
    was created. The service reads `lines` after chunk 11 has decided the
    attempt's outcome, so the accounting question is settled before the domain
    question is asked.
    """

    def __init__(self, adapter: ConnectivityAdapter, quantity: int = 1) -> None:
        self.adapter = adapter
        self.name = adapter.name
        self.quantity = quantity
        self.lines: tuple[ProviderLine, ...] = ()

    def provision(
        self, idempotency_key: str, payload: dict[str, Any]
    ) -> SupplierResult:
        try:
            result = self.adapter.provision(
                operation_reference(idempotency_key), self.quantity, payload
            )
        except ConnectivityOutcomeUnknown as exc:
            # Translated, not swallowed. Chunk 11 catches `SupplierTimeout` and
            # routes it to `record_unknown`; letting the connectivity exception
            # escape would land it in a generic handler that treats it as a
            # failure, and a failure looks retryable.
            raise SupplierTimeout(exc.reason) from exc
        self.lines = result.lines
        if not result.accepted:
            return SupplierResult(
                accepted=False, rejection_reason=result.rejection_reason
            )
        if len(result.lines) < self.quantity:
            # A partial delivery is not a success and not a failure. Telnyx can
            # return fewer eSIMs than requested with errors in the same 202, and
            # topping up the shortfall is a new decision — never a retry of this
            # attempt, which the supplier already partly honoured.
            raise SupplierTimeout(
                f"supplier delivered {len(result.lines)} of {self.quantity} "
                f"lines ({', '.join(result.errors) or 'no error code'}); the "
                "shortfall is a separate decision, not a retry"
            )
        return SupplierResult(
            accepted=True, provider_reference=result.lines[0].provider_reference
        )

    def reconcile(self, idempotency_key: str) -> SupplierResult | None:
        result = self.adapter.reconcile(
            operation_reference(idempotency_key), self.quantity
        )
        if result is None:
            # The supplier could not tell us. Chunk 11 turns this into
            # HELD_FOR_REVIEW, which is the correct end of the line: guessing
            # costs money in one direction and service in the other.
            return None
        self.lines = result.lines
        if not result.accepted:
            return SupplierResult(
                accepted=False, rejection_reason=result.rejection_reason
            )
        if len(result.lines) != self.quantity:
            return None
        return SupplierResult(
            accepted=True, provider_reference=result.lines[0].provider_reference
        )


class ConnectivityService:
    def __init__(
        self,
        fulfilment: FulfilmentService,
        vault: CredentialVault | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.fulfilment = fulfilment
        self.vault = vault
        self.clock = clock

    # --- provisioning -----------------------------------------------------

    def begin_provisioning(
        self, session: Session, item: OrderItem, adapter: ConnectivityAdapter
    ) -> SupplierAttempt:
        """Record the attempt. **The caller commits before dispatching.**

        Not a formality and not something this method can do for you: the whole
        recovery design rests on the attempt row existing before the supplier is
        called, so that a crash in between leaves a row saying "we may have
        asked". Committing inside a helper would hide that ordering from the
        one place it has to be visible.
        """
        adapter.capabilities().require(Capability.DATA)
        return self.fulfilment.begin_attempt(session, item, adapter.name)

    def dispatch_provisioning(
        self,
        session: Session,
        attempt: SupplierAttempt,
        adapter: ConnectivityAdapter,
        options: dict[str, Any] | None = None,
    ) -> SupplierAttempt:
        """Call the supplier and record what it said. Never retries a purchase.

        Three endings, and the third is the one that matters:

        - accepted → the lines are adopted and the item is provisioned;
        - definitively refused → the attempt is rejected and may be re-ordered
          as a **new** attempt with a new key;
        - unknown → `OUTCOME_UNKNOWN`, and only `reconcile_provisioning` may
          resolve it.
        """
        client = ConnectivitySupplierClient(adapter)
        item = session.get(OrderItem, attempt.order_item_id)
        if item is None:  # pragma: no cover - FK guarantees this
            raise ConnectivityServiceError("order_item_not_found")
        try:
            result = client.provision(attempt.idempotency_key, options or {})
        except SupplierTimeout as exc:
            return self.fulfilment.record_unknown(session, attempt, str(exc))
        except ConnectivityError as exc:
            # A definite refusal. Safe to treat as final, which an absence of
            # response never is.
            return self.fulfilment.record_result(
                session,
                attempt,
                SupplierResult(accepted=False, rejection_reason=exc.detail or exc.code),
            )

        recorded = self.fulfilment.record_result(session, attempt, result)
        if result.accepted:
            self._adopt(session, item, client.lines, adapter)
        return recorded

    def reconcile_provisioning(
        self, session: Session, attempt: SupplierAttempt, adapter: ConnectivityAdapter
    ) -> SupplierAttempt:
        """Ask the same supplier about the same operation. Never another one.

        Chunk 11 enforces the never-another-supplier rule and the held-for-
        review ending; this adds the domain half — if reconciliation proves the
        purchase landed, the lines it created are adopted here, so a recovered
        order ends up indistinguishable from one that never lost its response.
        """
        client = ConnectivitySupplierClient(adapter)
        resolved = self.fulfilment.reconcile(session, attempt, client)
        if resolved.outcome is AttemptOutcome.ACCEPTED and client.lines:
            item = session.get(OrderItem, attempt.order_item_id)
            if item is not None:
                self._adopt(session, item, client.lines, adapter)
        return resolved

    # --- adoption ---------------------------------------------------------

    def _adopt(
        self,
        session: Session,
        item: OrderItem,
        lines: tuple[ProviderLine, ...],
        adapter: ConnectivityAdapter,
    ) -> None:
        for line in lines:
            self.adopt_line(session, item, line, adapter)

    def adopt_line(
        self,
        session: Session,
        item: OrderItem,
        line: ProviderLine,
        adapter: ConnectivityAdapter,
    ) -> CarrierLine:
        """Turn one supplier line into our four separate facts.

        Idempotent on `(carrier, provider_reference)`. A reconciliation that
        adopts the same line the original dispatch already adopted must not
        create a second `carrier_lines` row — the unique index would refuse it
        anyway, but refusing with an `IntegrityError` in a recovery path is a
        poor way to find out.
        """
        existing = session.exec(
            select(CarrierLine).where(
                CarrierLine.carrier == adapter.name,
                CarrierLine.carrier_line_reference == line.provider_reference,
            )
        ).first()
        if existing is not None:
            return self.apply_provider_line(session, existing, line)

        entitlement = self.grant_entitlement(session, item)
        installation = session.exec(
            select(EsimInstallation).where(
                EsimInstallation.entitlement_id == entitlement.id
            )
        ).first()
        if installation is None:
            installation = EsimInstallation(
                entitlement_id=entitlement.id,
                installation_state=InstallationState.NOT_INSTALLED,
            )
            session.add(installation)
            session.flush()
        if line.installation_released and installation.profile_released_at is None:
            installation.profile_released_at = line.observed_at or self.clock()
            session.add(installation)

        carrier_line = CarrierLine(
            entitlement_id=entitlement.id,
            carrier=adapter.name,
            carrier_line_reference=line.provider_reference,
            iccid=line.iccid,
            activation_state=ActivationState.PENDING,
            # Never inferred. We have provisioned a line, not observed a
            # handset attaching to a network, and those are different claims.
            network_state=NetworkState.UNKNOWN,
            created_at=self.clock(),
        )
        session.add(carrier_line)
        session.flush()
        return self.apply_provider_line(session, carrier_line, line)

    def grant_entitlement(self, session: Session, item: OrderItem) -> Entitlement:
        """What the buyer is owed, from what the catalog says was sold.

        Reads `ProductAllowance` rather than accepting an amount from the
        caller. A grant computed at fulfilment time from whatever the worker
        happened to be passed is a grant nobody agreed to, and the difference
        only shows up as a customer with the wrong balance months later.
        """
        existing = session.exec(
            select(Entitlement).where(Entitlement.order_item_id == item.id)
        ).first()
        if existing is not None:
            return existing

        allowance = session.exec(
            select(ProductAllowance).where(
                ProductAllowance.product_id == item.product_id
            )
        ).first()
        if allowance is None:
            raise ConnectivityServiceError(
                "product_allowance_missing",
                f"product {item.product_id} has no recorded allowance; "
                "provisioning would have to invent what the customer bought",
            )
        granted_at = self.clock()
        entitlement = Entitlement(
            order_item_id=item.id,
            holder_user_id=item.recipient_user_id,
            product_id=item.product_id,
            data_bytes_total=allowance.data_bytes,
            voice_seconds_total=allowance.voice_seconds,
            granted_at=granted_at,
            expires_at=(
                None
                if allowance.validity_days is None
                else granted_at + timedelta(days=allowance.validity_days)
            ),
        )
        session.add(entitlement)
        session.flush()
        return entitlement

    # --- state mapping ----------------------------------------------------

    def apply_provider_line(
        self, session: Session, carrier_line: CarrierLine, line: ProviderLine
    ) -> CarrierLine:
        """Fold one supplier observation into our own states.

        The single place a supplier's vocabulary is translated. Two rules it
        does not break:

        **A transitional status changes nothing.** `enabling` is not `enabled`.
        Acting on it would report a line as live while it is still coming up,
        and the next poll would report the truth anyway.

        **Network state is only ever set from a network observation.** There is
        no branch below that sets it, and that is deliberate — a carrier telling
        us a line is enabled is telling us about its own records, not about a
        handset. `record_network_observation` is the only writer.
        """
        observed_at = line.observed_at or self.clock()
        carrier_line.provider_status = line.provider_status
        carrier_line.provider_status_observed_at = observed_at
        if line.iccid and not carrier_line.iccid:
            carrier_line.iccid = line.iccid
        if line.voice_enabled is not None:
            carrier_line.voice_enabled = line.voice_enabled
            carrier_line.voice_enabled_observed_at = observed_at

        mapped = _ACTIVATION_BY_PROVIDER_STATE.get(line.state)
        # TERMINATED is final. A supplier that reports a terminated line as
        # active again is a supplier we do not believe without a human.
        if (
            mapped is not None
            and carrier_line.activation_state is not mapped
            and carrier_line.activation_state is not ActivationState.TERMINATED
        ):
            carrier_line.activation_state = mapped

        session.add(carrier_line)
        session.flush()
        return carrier_line

    def record_network_observation(
        self,
        session: Session,
        carrier_line: CarrierLine,
        attached: bool,
        observed_at: datetime | None = None,
    ) -> CarrierLine:
        """The only writer of `network_state`, and it needs an observation.

        Called from something that actually saw a session — a connectivity log,
        a data record, a device report. Not from activation, ever.
        """
        carrier_line.network_state = (
            NetworkState.ATTACHED if attached else NetworkState.DETACHED
        )
        carrier_line.network_state_observed_at = observed_at or self.clock()
        session.add(carrier_line)
        session.flush()
        return carrier_line

    def record_device_installation(
        self,
        session: Session,
        installation: EsimInstallation,
        installed_at: datetime | None = None,
    ) -> EsimInstallation:
        """A device said the profile is on it. The only thing that may say so.

        Delivering a QR code is not this. Neither is a supplier reporting the
        profile released for download. `prd.md` keeps installation and
        activation apart because a customer can install a profile on a phone
        that never attaches, and telling them otherwise is telling them their
        phone works when it does not.
        """
        installation.installation_state = InstallationState.INSTALLED
        installation.installed_at = installed_at or self.clock()
        session.add(installation)
        session.flush()
        return installation

    # --- installation material -------------------------------------------

    def store_activation_credential(
        self,
        session: Session,
        installation: EsimInstallation,
        credential: ActivationCredential,
    ) -> None:
        if self.vault is None:
            raise ConnectivityServiceError(
                "no_credential_vault",
                "activation material cannot be stored without a vault; storing "
                "it in the clear is not the fallback",
            )
        self.vault.store(
            session, installation, credential.secret, credential.one_time_use
        )

    def fetch_and_store_credential(
        self,
        session: Session,
        installation: EsimInstallation,
        carrier_line: CarrierLine,
        adapter: ConnectivityAdapter,
    ) -> None:
        """Retrieve the profile from the supplier and seal it immediately.

        The plaintext exists in memory for the length of this call and is never
        returned, logged or attached to an exception. A caller that wants it
        goes through a grant.
        """
        credential = adapter.fetch_activation_credential(
            carrier_line.carrier_line_reference
        )
        self.store_activation_credential(session, installation, credential)

    # --- lifecycle actions ------------------------------------------------

    def request_action(
        self,
        session: Session,
        carrier_line: CarrierLine,
        kind: LineActionKind,
    ) -> CarrierLineAction:
        """Record the intention. Nothing has been sent yet.

        Separate from dispatching for the same reason `begin_attempt` is
        separate from calling a supplier: the row has to exist before the
        request goes out, or a crash mid-call leaves a line whose state nobody
        knows and nothing to reconcile against.

        An open action on the line refuses a second one. Two simultaneous
        suspends are not two suspensions, and a suspend racing a resume has no
        defined answer — the carrier would refuse it anyway, later and less
        clearly.
        """
        open_action = self._open_action(session, carrier_line)
        if open_action is not None:
            if open_action.kind is kind:
                return open_action
            raise ConnectivityServiceError(
                "line_action_conflict",
                f"line {carrier_line.id} already has an open "
                f"{open_action.kind.value} action; settle it first",
            )
        action = CarrierLineAction(
            carrier_line_id=carrier_line.id,
            provider=carrier_line.carrier,
            kind=kind,
            state=LineActionState.REQUESTED,
            requested_at=self.clock(),
        )
        session.add(action)
        session.flush()
        return action

    def dispatch_action(
        self,
        session: Session,
        action: CarrierLineAction,
        carrier_line: CarrierLine,
        adapter: ConnectivityAdapter,
    ) -> CarrierLineAction:
        """Send it. A 202 makes it `PENDING`, never `CONFIRMED`.

        Telnyx documents every state change as asynchronous. An implementation
        that marked the line suspended on the 202 would be telling a customer
        their line is off while it is still passing traffic and still billable.
        """
        if action.state is not LineActionState.REQUESTED:
            raise ConnectivityServiceError(
                "action_already_dispatched",
                f"action {action.id} is {action.state.value}",
            )
        try:
            if action.kind is LineActionKind.ENABLE_VOICE:
                provider_action = adapter.enable_voice(
                    carrier_line.carrier_line_reference
                )
            else:
                provider_action = adapter.set_state(
                    carrier_line.carrier_line_reference,
                    _TARGET_BY_ACTION[action.kind],
                )
        except ConnectivityOutcomeUnknown as exc:
            # Left open at PENDING with no provider reference. The sweeper
            # resolves it by listing the carrier's actions for this line;
            # re-sending would race the request that may already be in flight.
            action.state = LineActionState.PENDING
            action.failure_reason = f"dispatch outcome unknown: {exc.reason}"[:500]
            session.add(action)
            session.flush()
            return action
        except ConnectivityError as exc:
            return self.settle_action(
                session, action, carrier_line, succeeded=False,
                reason=exc.detail or exc.code,
            )

        action.state = LineActionState.PENDING
        action.provider_action_reference = provider_action.provider_reference
        session.add(action)
        session.flush()
        if provider_action.settled:
            # Rare but documented: an action can come back already complete.
            return self.settle_action(
                session,
                action,
                carrier_line,
                succeeded=bool(provider_action.succeeded),
                reason=provider_action.reason,
            )
        return action

    def poll_action(
        self,
        session: Session,
        action: CarrierLineAction,
        carrier_line: CarrierLine,
        adapter: ConnectivityAdapter,
    ) -> CarrierLineAction:
        """Ask whether the change happened yet.

        An action with no provider reference — the lost-dispatch case — cannot
        be polled by id, so it stays open. Resolving it needs the carrier's
        action list for the line, which is an operations decision rather than
        something to guess at here.
        """
        if action.state is not LineActionState.PENDING:
            return action
        if action.provider_action_reference is None:
            return action
        provider_action = adapter.fetch_action(action.provider_action_reference)
        if provider_action is None or not provider_action.settled:
            return action
        return self.settle_action(
            session,
            action,
            carrier_line,
            succeeded=bool(provider_action.succeeded),
            reason=provider_action.reason,
        )

    def settle_action(
        self,
        session: Session,
        action: CarrierLineAction,
        carrier_line: CarrierLine,
        succeeded: bool,
        reason: str | None = None,
    ) -> CarrierLineAction:
        """Close the action, and only then move the line.

        The line's state changes because the carrier confirmed it, not because
        we asked. A failed action leaves the line exactly where it was, which
        is the honest outcome — a suspension that did not happen has not
        happened.
        """
        now = self.clock()
        action.state = (
            LineActionState.CONFIRMED if succeeded else LineActionState.FAILED
        )
        action.settled_at = now
        if reason:
            action.failure_reason = reason[:500]
        session.add(action)

        if succeeded:
            if action.kind in (LineActionKind.ACTIVATE, LineActionKind.RESUME):
                carrier_line.activation_state = ActivationState.ACTIVE
            elif action.kind is LineActionKind.SUSPEND:
                carrier_line.activation_state = ActivationState.SUSPENDED
                # Suspending stops the line, but whether the handset has
                # actually detached is a network fact we have not observed.
                carrier_line.network_state = NetworkState.UNKNOWN
                carrier_line.network_state_observed_at = None
            elif action.kind is LineActionKind.ENABLE_VOICE:
                carrier_line.voice_enabled = True
                carrier_line.voice_enabled_observed_at = now
            session.add(carrier_line)
        session.flush()
        return action

    def _open_action(
        self, session: Session, carrier_line: CarrierLine
    ) -> CarrierLineAction | None:
        return session.exec(
            select(CarrierLineAction).where(
                CarrierLineAction.carrier_line_id == carrier_line.id,
                col(CarrierLineAction.state).in_(
                    [LineActionState.REQUESTED, LineActionState.PENDING]
                ),
            )
        ).first()

    # --- numbers ----------------------------------------------------------

    def assign_number(
        self,
        session: Session,
        carrier_line: CarrierLine,
        adapter: ConnectivityAdapter,
        country: str,
        provider_number_reference: str | None = None,
    ) -> AssignedNumber | None:
        """Record the number the supplier assigned, if it has assigned one yet.

        Returns `None` rather than raising when there is no number. A voice line
        whose number has not been allocated is a normal intermediate state, and
        an exception would make a poll loop look like a fault.

        Re-assigning is not re-recording: a live assignment for the same number
        is returned as-is, and a *different* number releases the old row rather
        than editing it, because an old assignment has to survive to explain who
        held the number when a call was billed.
        """
        e164 = adapter.assigned_number(carrier_line.carrier_line_reference)
        if not e164:
            return None

        live = session.exec(
            select(AssignedNumber).where(
                AssignedNumber.carrier_line_id == carrier_line.id,
                col(AssignedNumber.released_at).is_(None),
            )
        ).first()
        if live is not None:
            if live.e164 == e164:
                return live
            live.released_at = self.clock()
            session.add(live)
            session.flush()

        assigned = AssignedNumber(
            carrier_line_id=carrier_line.id,
            e164=e164,
            country=country,
            provider_number_reference=provider_number_reference,
            assigned_at=self.clock(),
        )
        session.add(assigned)
        session.flush()
        return assigned

    # --- refresh ----------------------------------------------------------

    def refresh_line(
        self, session: Session, carrier_line: CarrierLine, adapter: ConnectivityAdapter
    ) -> CarrierLine:
        """Re-read the supplier's view of a line and fold it in.

        A line the supplier no longer knows about is left untouched and not
        marked terminated. A 404 from a supplier is ambiguous — a deleted line
        and a routing mistake look identical — and terminating a customer's
        service on an ambiguous read is not a recoverable mistake.
        """
        line = adapter.fetch_line(carrier_line.carrier_line_reference)
        if line is None:
            return carrier_line
        return self.apply_provider_line(session, carrier_line, line)


#: Supplier state to our activation state. `TRANSITIONING` is absent on
#: purpose: a line mid-change keeps the state it had, because "enabling" is not
#: "enabled" and acting on it reports a line as live before it is.
_ACTIVATION_BY_PROVIDER_STATE: dict[ProviderLineState, ActivationState] = {
    ProviderLineState.PROVISIONED: ActivationState.PENDING,
    ProviderLineState.ACTIVE: ActivationState.ACTIVE,
    ProviderLineState.SUSPENDED: ActivationState.SUSPENDED,
    # A carrier-imposed restriction — a data cap, an unauthorized device — is a
    # suspension from the customer's point of view: the line does not work.
    # Chunk 17 distinguishes *why*, which is what decides whether resuming is
    # even possible.
    ProviderLineState.RESTRICTED: ActivationState.SUSPENDED,
    ProviderLineState.TERMINATED: ActivationState.TERMINATED,
}

_TARGET_BY_ACTION: dict[LineActionKind, ProviderLineState] = {
    LineActionKind.ACTIVATE: ProviderLineState.ACTIVE,
    LineActionKind.RESUME: ProviderLineState.ACTIVE,
    LineActionKind.SUSPEND: ProviderLineState.SUSPENDED,
}


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


__all__ = [
    "ConnectivityService",
    "ConnectivityServiceError",
    "ConnectivitySupplierClient",
    "ProvisioningState",
    "operation_reference",
]
