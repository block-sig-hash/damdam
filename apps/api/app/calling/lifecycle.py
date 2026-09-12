"""Durable call lifecycle: the event inbox, provider operations and convergence.

`service.py` decides whether a call *may* happen. This module deals with what
happens next, and everything in it is shaped by the fact that the provider's
side of the conversation is unreliable in four specific, documented ways
(V01 §4–§5): events are duplicated, delayed, reordered, and sometimes describe a
leg we have no record of. A fifth failure is ours — we send a command and lose
the response.

So the ingestion path is deliberately boring and always the same:

1. **Authenticate**, inside the adapter, before parsing. Unauthenticated input
   never reaches a parser (reuse item R4).
2. **Store**, by unique provider event id, before deciding anything. A crash
   after this leaves an event to reprocess; a crash before it leaves nothing
   half-applied. A second delivery collides here and is answered without being
   applied twice (N8).
3. **Resolve** the attempt and leg from *our* tables. `client_state` may point;
   it may not authorize (N7).
4. **Validate** connection, credential and expected transition against the
   stored grant. A mismatch is quarantined, not applied (N6).
5. **Apply**, forward only.

Commands go the other way and follow the outbox discipline chunk 11 established:
the operation row is written and **committed by the caller before the provider is
called**, so a lost response has a durable thing to ask about. Reconciliation
asks "what did operation X produce"; it never asks "has enough time passed to try
again", because that question has produced a second billable call every time
anybody has asked it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.auth.models import utc_now
from app.calling.contract import (
    LEG_STATE_RANK,
    CallingAdapter,
    CallingError,
    CallOutcomeUnknown,
    LegRole,
    LegState,
    ProviderEvent,
    ProviderLegHandle,
)
from app.calling.models import (
    LIVE_OPERATION_OUTCOMES,
    AttemptState,
    CallAttempt,
    CallEvent,
    CallingClientCredential,
    CallLeg,
    CallOperation,
    EventDisposition,
    OperationKind,
    OperationOutcome,
)
from app.calling.service import CallAuthorizationService


class CallLifecycleError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


#: Provider event types this chunk acts on, mapped to the leg state they assert.
#: An event type absent from here is stored and acknowledged but changes nothing
#: — an unknown event is not an error, and treating it as one would make every
#: provider feature release an outage.
_EVENT_LEG_STATE: dict[str, LegState] = {
    "call.initiated": LegState.PARKED,
    "call.ringing": LegState.RINGING,
    "call.answered": LegState.ANSWERED,
    "call.bridged": LegState.BRIDGED,
    "call.hangup": LegState.ENDED,
}

_LEG_TO_ATTEMPT: dict[LegState, AttemptState] = {
    LegState.PARKED: AttemptState.ACCEPTED,
    LegState.RINGING: AttemptState.RINGING,
    LegState.ANSWERED: AttemptState.ANSWERED,
    LegState.BRIDGED: AttemptState.ANSWERED,
}


class CallLifecycleService:
    """Ingest provider events and issue provider commands, durably.

    Holds no state of its own. Everything it decides is read from and written to
    the database in the caller's session, so two workers running it concurrently
    are serialized by the same row locks and unique indexes rather than by an
    assumption that only one of them is running.
    """

    def __init__(
        self,
        adapter: CallingAdapter,
        authorization: CallAuthorizationService,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.adapter = adapter
        self.authorization = authorization
        self.clock = clock

    # --- ingestion --------------------------------------------------------

    def ingest(
        self, session: Session, body: bytes, headers: dict[str, str]
    ) -> CallEvent:
        """Authenticate, store once, then decide. In that order, always.

        A bad signature raises before anything is written. That is deliberate and
        it is the one place this path stores nothing: an endpoint that recorded
        every unauthenticated POST would be a free write amplifier for anybody
        who found the URL (N9).
        """
        event = self.adapter.parse_event(body, headers)
        stored = self._store(session, event)
        if stored.disposition is EventDisposition.DUPLICATE:
            return stored
        return self._apply(session, stored, event)

    def _store(self, session: Session, event: ProviderEvent) -> CallEvent:
        """Insert by unique provider event id, or report the collision.

        The insert is attempted rather than preceded by a SELECT. Two concurrent
        deliveries of one event both pass a SELECT and both proceed; only one of
        them survives the unique index, and letting the database be the one to
        say so is what makes this correct under concurrency rather than merely
        usually right.
        """
        record = CallEvent(
            provider=self.adapter.name,
            provider_event_id=event.event_id,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            received_at=self.clock(),
            disposition=EventDisposition.UNMATCHED,
            payload=dict(event.raw),
        )
        savepoint = session.begin_nested()
        try:
            session.add(record)
            session.flush()
        except IntegrityError:
            savepoint.rollback()
            existing = session.exec(
                select(CallEvent).where(
                    CallEvent.provider == self.adapter.name,
                    CallEvent.provider_event_id == event.event_id,
                )
            ).first()
            if existing is None:  # pragma: no cover - the collision was on this key
                raise
            # Replays inside the signature's tolerance window land here. The
            # signature was valid and the timestamp was fresh; this is what says
            # we have already acted on it.
            return _as_duplicate(existing)
        else:
            savepoint.commit()
        return record

    def _apply(
        self, session: Session, record: CallEvent, event: ProviderEvent
    ) -> CallEvent:
        attempt, leg = self._resolve(session, event)
        if attempt is None:
            # Not an error. A provider event can overtake the response to the
            # command that caused it, and this row is replayable once the leg
            # exists.
            return self._dispose(
                session,
                record,
                EventDisposition.UNMATCHED,
                "no attempt resolves from this event's identifiers or client state",
            )
        record.attempt_id = attempt.id

        quarantine = self._quarantine_reason(session, attempt, leg, event)
        if quarantine is not None:
            return self._dispose(
                session, record, EventDisposition.QUARANTINED, quarantine
            )

        target = _EVENT_LEG_STATE.get(event.event_type)
        if target is None:
            return self._dispose(
                session,
                record,
                EventDisposition.SUPERSEDED,
                f"{event.event_type} carries no state transition",
            )

        if leg is None:
            if target is not LegState.PARKED:
                # An event for a leg we never recorded, that is not the client's
                # first one. Storing it unmatched keeps it replayable without
                # inventing a leg from a provider identifier.
                return self._dispose(
                    session,
                    record,
                    EventDisposition.UNMATCHED,
                    "no recorded leg for this provider identifier",
                )
            leg = self._record_client_leg(session, attempt, event)
        record.leg_id = leg.id

        changed = self._advance_leg(session, leg, target, event)
        if not changed:
            return self._dispose(
                session,
                record,
                EventDisposition.SUPERSEDED,
                f"leg already at or beyond {target.value}",
            )

        self._advance_attempt(session, attempt, leg, target, event)
        return self._dispose(session, record, EventDisposition.APPLIED, None)

    # --- resolution and validation ----------------------------------------

    def _resolve(
        self, session: Session, event: ProviderEvent
    ) -> tuple[CallAttempt | None, CallLeg | None]:
        """Find our records for this event. Database first, client state last.

        A recorded leg is the strongest answer because we wrote it. `client_state`
        is consulted only when no leg matches, and even then it is used to *look
        up* an attempt whose ownership is then re-validated — never to assert
        anything about one.
        """
        leg = session.exec(
            select(CallLeg).where(
                CallLeg.provider == self.adapter.name,
                CallLeg.provider_call_control_id == event.leg.control_id,
            )
        ).first()
        if leg is not None:
            return session.get(CallAttempt, leg.attempt_id), leg

        reference = event.client_state.get("attempt_id")
        if not isinstance(reference, str):
            return None, None
        try:
            attempt_id = UUID(reference)
        except ValueError:
            return None, None
        return session.get(CallAttempt, attempt_id), None

    def _quarantine_reason(
        self,
        session: Session,
        attempt: CallAttempt,
        leg: CallLeg | None,
        event: ProviderEvent,
    ) -> str | None:
        """Reasons to store an event and deliberately not act on it.

        Each of these is a contradiction between what the provider says and what
        we authorized, and none of them is recoverable by processing the event
        anyway. They are separated from `UNMATCHED` because an operator triaging
        a queue needs "arrived early" and "does not add up" to look different
        (N6).
        """
        if attempt.client_credential_id is not None and event.leg.credential_id:
            credential = session.get(
                CallingClientCredential, attempt.client_credential_id
            )
            if (
                credential is not None
                and credential.provider_credential_id != event.leg.credential_id
            ):
                return (
                    "the provider credential on this event is not the one the "
                    "grant was bound to"
                )
        if leg is not None and leg.attempt_id != attempt.id:  # pragma: no cover
            return "this leg belongs to a different attempt"
        if (
            event.claimed_destination
            and leg is not None
            and leg.role is LegRole.DESTINATION
            and event.claimed_destination != attempt.e164_destination
        ):
            # The destination leg is ours; it can only be going where we sent it.
            # If the provider says otherwise, something is wrong that no state
            # transition fixes (N4).
            return "the destination on this event is not the authorized one"
        return None

    # --- legs --------------------------------------------------------------

    def _record_client_leg(
        self, session: Session, attempt: CallAttempt, event: ProviderEvent
    ) -> CallLeg:
        leg = CallLeg(
            attempt_id=attempt.id,
            role=LegRole.CLIENT,
            provider=self.adapter.name,
            provider_call_control_id=event.leg.control_id,
            provider_call_leg_id=event.leg.leg_id,
            provider_call_session_id=event.leg.session_id,
            provider_connection_id=event.leg.connection_id,
            provider_credential_id=event.leg.credential_id,
            state=LegState.CREATED,
            # No `time_limit_seconds`: V01 found no documented provider-enforced
            # bound on a leg the client created. Recording one would claim a
            # limit that does not exist (B3).
            time_limit_seconds=None,
            started_at=event.occurred_at,
            created_at=self.clock(),
        )
        session.add(leg)
        session.flush()
        return leg

    def _advance_leg(
        self, session: Session, leg: CallLeg, target: LegState, event: ProviderEvent
    ) -> bool:
        """Forward only. A late event describes an earlier moment, not a new one."""
        if LEG_STATE_RANK[target] <= LEG_STATE_RANK[leg.state]:
            return False
        leg.state = target
        if target in (LegState.ANSWERED, LegState.BRIDGED) and leg.answered_at is None:
            leg.answered_at = event.occurred_at
        if target is LegState.ENDED:
            leg.ended_at = event.occurred_at
            leg.hangup_cause = event.hangup_cause
            # A leg that ends without ever answering has no answer time, and
            # `ck_call_legs_not_negative_duration` is what stops a reordered
            # pair from producing one that precedes it.
            if leg.answered_at is not None and _aware(leg.ended_at) < _aware(
                leg.answered_at
            ):
                leg.ended_at = leg.answered_at
        session.add(leg)
        session.flush()
        return True

    def _advance_attempt(
        self,
        session: Session,
        attempt: CallAttempt,
        leg: CallLeg,
        target: LegState,
        event: ProviderEvent,
    ) -> None:
        if target is LegState.ENDED:
            if self._has_live_leg(session, attempt):
                return
            # Whether this was a call or a failed attempt is decided by whether
            # anything ever answered — not by the hangup cause, which describes
            # one leg and is provider vocabulary.
            answered = attempt.answered_at is not None
            self.authorization.advance(
                session,
                attempt,
                AttemptState.COMPLETED if answered else AttemptState.FAILED,
                end_reason=event.hangup_cause or "provider_hangup",
            )
            return
        mapped = _LEG_TO_ATTEMPT.get(target)
        if mapped is None:
            return
        self.authorization.advance(
            session,
            attempt,
            mapped,
            answered_at=(
                leg.answered_at if mapped is AttemptState.ANSWERED else None
            ),
        )

    def _has_live_leg(self, session: Session, attempt: CallAttempt) -> bool:
        return (
            session.exec(
                select(CallLeg).where(
                    CallLeg.attempt_id == attempt.id,
                    CallLeg.state != LegState.ENDED,
                )
            ).first()
            is not None
        )

    # --- durable operations -----------------------------------------------

    def begin_operation(
        self, session: Session, attempt: CallAttempt, kind: OperationKind
    ) -> CallOperation:
        """Write the intent down. **The caller commits before calling out.**

        Returning an existing live operation instead of creating a second one is
        the duplicate-command guard in service form; `ux_call_operations_live` is
        the same guard in the database, and it is the one that holds when two
        workers reach here at the same moment.
        """
        live = session.exec(
            select(CallOperation).where(
                CallOperation.attempt_id == attempt.id,
                CallOperation.kind == kind,
                col(CallOperation.outcome).in_(list(LIVE_OPERATION_OUTCOMES)),
            )
        ).first()
        if live is not None:
            return live
        previous = session.exec(
            select(CallOperation).where(
                CallOperation.attempt_id == attempt.id, CallOperation.kind == kind
            )
        ).all()
        number = len(previous) + 1
        operation = CallOperation(
            attempt_id=attempt.id,
            kind=kind,
            provider=self.adapter.name,
            # Names one request. A retry of the same request reuses it; a new
            # decision gets a new number, so a legitimate second command after a
            # definite rejection is not deduplicated against the refusal.
            operation_key=f"attempt:{attempt.id}:{kind.value}:{number}",
            attempt_number=number,
            outcome=OperationOutcome.IN_FLIGHT,
            created_at=self.clock(),
        )
        session.add(operation)
        session.flush()
        return operation

    def record_accepted(
        self, session: Session, operation: CallOperation, reference: str
    ) -> CallOperation:
        operation.outcome = OperationOutcome.ACCEPTED
        operation.provider_reference = reference
        operation.settled_at = self.clock()
        session.add(operation)
        session.flush()
        return operation

    def record_rejected(
        self, session: Session, operation: CallOperation, detail: str
    ) -> CallOperation:
        operation.outcome = OperationOutcome.REJECTED
        operation.detail = detail
        operation.settled_at = self.clock()
        session.add(operation)
        session.flush()
        return operation

    def record_unknown(
        self, session: Session, operation: CallOperation, reason: str
    ) -> CallOperation:
        """We sent it and lost the answer. Not a failure, and never retried.

        The operation stays *live* — `outcome_unknown` is in
        `LIVE_OPERATION_OUTCOMES` — so `ux_call_operations_live` keeps refusing a
        second command of this kind until reconciliation settles it.
        """
        operation.outcome = OperationOutcome.OUTCOME_UNKNOWN
        operation.detail = reason
        session.add(operation)
        session.flush()
        return operation

    def reconcile(
        self, session: Session, operation: CallOperation
    ) -> CallOperation:
        """Ask the provider what this exact operation produced. Never re-send.

        Three answers, and the third is the important one. A leg means it
        happened and we record it; a definite `None` from an adapter that *knows*
        means it did not; and an adapter that cannot tell us leaves the operation
        held for review, because a human deciding is better than a worker
        guessing with a PSTN leg on the line.
        """
        if operation.outcome is not OperationOutcome.OUTCOME_UNKNOWN:
            return operation
        try:
            handle = self.adapter.reconcile_operation(operation.id)
        except (CallingError, CallOutcomeUnknown) as exc:
            operation.detail = f"reconciliation failed: {exc}"
            operation.outcome = OperationOutcome.HELD_FOR_REVIEW
            session.add(operation)
            session.flush()
            return operation
        if handle is None:
            operation.outcome = OperationOutcome.HELD_FOR_REVIEW
            operation.detail = (
                "the provider could not report this operation's outcome; a "
                "second command would risk a duplicate billable leg"
            )
            session.add(operation)
            session.flush()
            return operation
        attempt = session.get(CallAttempt, operation.attempt_id)
        if (
            attempt is not None
            and operation.kind is OperationKind.CREATE_DESTINATION_LEG
        ):
            self._ensure_destination_leg(session, attempt, handle)
        return self.record_accepted(session, operation, handle.control_id)

    # --- commands -----------------------------------------------------------

    def create_destination_leg(
        self, session: Session, attempt: CallAttempt, operation: CallOperation
    ) -> CallLeg | None:
        """Dial the destination recorded on the grant. Never one from an event.

        `attempt.e164_destination` and `attempt.identity_e164` are read from the
        row, not from the caller and not from the provider event that triggered
        this. That is the whole of N4: there is no parameter here through which a
        different destination could arrive.

        `time_limit_seconds` comes from the grant's `max_seconds`, so the only
        bound that survives this process dying is set from the amount of money
        that was actually reserved (V01 §6).
        """
        try:
            handle = self.adapter.create_destination_leg(
                operation_reference=operation.id,
                destination=attempt.e164_destination,
                identity=attempt.identity_e164,
                time_limit_seconds=attempt.max_seconds,
                correlation=str(attempt.id),
            )
        except CallOutcomeUnknown as exc:
            self.record_unknown(session, operation, exc.reason)
            self.authorization.mark_unknown(
                session, attempt, "destination leg outcome unknown"
            )
            return None
        except CallingError as exc:
            self.record_rejected(session, operation, exc.detail or exc.code)
            self.authorization.advance(
                session, attempt, AttemptState.FAILED, end_reason=exc.code
            )
            return None
        leg = self._ensure_destination_leg(session, attempt, handle)
        self.record_accepted(session, operation, handle.control_id)
        return leg

    def _ensure_destination_leg(
        self, session: Session, attempt: CallAttempt, handle: ProviderLegHandle
    ) -> CallLeg:
        """Record the destination leg, or return the one already there.

        Reconciliation and the original command both land here, and exactly one
        of them may create the row. The partial unique index decides; this
        function's job is to notice that it lost rather than to raise.
        """
        existing = session.exec(
            select(CallLeg).where(
                CallLeg.provider == self.adapter.name,
                CallLeg.provider_call_control_id == handle.control_id,
            )
        ).first()
        if existing is not None:
            return existing
        leg = CallLeg(
            attempt_id=attempt.id,
            role=LegRole.DESTINATION,
            provider=self.adapter.name,
            provider_call_control_id=handle.control_id,
            provider_call_leg_id=handle.leg_id,
            provider_call_session_id=handle.session_id,
            provider_connection_id=handle.connection_id,
            state=LegState.CREATED,
            time_limit_seconds=attempt.max_seconds,
            started_at=self.clock(),
            created_at=self.clock(),
        )
        savepoint = session.begin_nested()
        try:
            session.add(leg)
            session.flush()
        except IntegrityError:
            savepoint.rollback()
            # `ux_call_legs_live_destination` refused a second live destination
            # leg for this attempt. That is the database preventing a duplicate
            # PSTN call, and the correct response is to use the existing one.
            current = session.exec(
                select(CallLeg).where(
                    CallLeg.attempt_id == attempt.id,
                    CallLeg.role == LegRole.DESTINATION,
                    CallLeg.state != LegState.ENDED,
                )
            ).first()
            if current is None:  # pragma: no cover - the index was the refusal
                raise
            return current
        savepoint.commit()
        return leg

    def hangup(
        self, session: Session, attempt: CallAttempt, leg: CallLeg
    ) -> CallOperation:
        """End a leg through a durable operation, like every other command.

        A hangup whose response is lost is not retried blind either. The leg may
        already be down, and a second hangup against a control id the provider
        has reused would end somebody else's call.
        """
        operation = self.begin_operation(session, attempt, OperationKind.HANGUP)
        try:
            self.adapter.hangup(
                operation_reference=operation.id,
                control_id=leg.provider_call_control_id,
            )
        except CallOutcomeUnknown as exc:
            return self.record_unknown(session, operation, exc.reason)
        except CallingError as exc:
            return self.record_rejected(session, operation, exc.detail or exc.code)
        return self.record_accepted(session, operation, leg.provider_call_control_id)

    def bridge(
        self,
        session: Session,
        attempt: CallAttempt,
        client_leg: CallLeg,
        destination_leg: CallLeg,
    ) -> CallOperation:
        """Join the two recorded legs, after the destination has answered.

        Bridging before the destination answers would connect the customer to a
        ringing tone we are paying for and call it a conversation. V01's topology
        step 5 is explicit that the bridge follows the answer.
        """
        if destination_leg.state not in (LegState.ANSWERED, LegState.BRIDGED):
            raise CallLifecycleError(
                "destination_not_answered",
                "a bridge before the destination answers bills a call nobody took",
            )
        operation = self.begin_operation(session, attempt, OperationKind.BRIDGE)
        try:
            self.adapter.bridge(
                operation_reference=operation.id,
                first=client_leg.provider_call_control_id,
                second=destination_leg.provider_call_control_id,
            )
        except CallOutcomeUnknown as exc:
            return self.record_unknown(session, operation, exc.reason)
        except CallingError as exc:
            return self.record_rejected(session, operation, exc.detail or exc.code)
        return self.record_accepted(
            session, operation, destination_leg.provider_call_control_id
        )

    # --- helpers -----------------------------------------------------------

    def _dispose(
        self,
        session: Session,
        record: CallEvent,
        disposition: EventDisposition,
        reason: str | None,
    ) -> CallEvent:
        record.disposition = disposition
        record.disposition_reason = reason
        session.add(record)
        session.flush()
        return record

    def replayable(self, session: Session, limit: int = 100) -> list[CallEvent]:
        """Events stored before their leg existed, oldest first.

        The reordering defence in practice: a `call.answered` that overtook the
        originate response is unmatched now and applicable in a moment, and this
        is what a worker iterates to apply it (N10).
        """
        return list(
            session.exec(
                select(CallEvent)
                .where(CallEvent.disposition == EventDisposition.UNMATCHED)
                .order_by(col(CallEvent.received_at))
                .limit(limit)
            ).all()
        )


def _as_duplicate(existing: CallEvent) -> CallEvent:
    """Mark an in-memory copy as a duplicate without rewriting the stored row.

    The stored row keeps its original disposition — it records what happened the
    first time, and overwriting it with `duplicate` would erase the fact that the
    event was applied.
    """
    copy = CallEvent(
        id=existing.id,
        provider=existing.provider,
        provider_event_id=existing.provider_event_id,
        event_type=existing.event_type,
        occurred_at=existing.occurred_at,
        received_at=existing.received_at,
        attempt_id=existing.attempt_id,
        leg_id=existing.leg_id,
        disposition=EventDisposition.DUPLICATE,
        disposition_reason="already stored; not applied again",
        payload=existing.payload,
    )
    return copy


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def new_operation_reference() -> UUID:
    return uuid4()


def redacted(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip anything credential-shaped before a payload reaches a log.

    `AGENTS.md`: secrets and activation material stay out of logs, handoffs and
    review records. Provider payloads carry tokens and SIP passwords, and a
    webhook body is exactly the sort of thing that gets logged wholesale during
    an incident.
    """
    hidden = {"token", "password", "sip_password", "secret", "api_key", "jwt"}
    return {
        key: ("<redacted>" if key.lower() in hidden else value)
        for key, value in payload.items()
    }
