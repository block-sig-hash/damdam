"""The outbound calling API — US-45.

Endpoint shapes come from V01's reviewed interface proposal
(`docs/implementation/voice/GO-NO-GO.md`), not from the retired `/voice/*`
surface, whose contracts no longer match anything (reject item X6).

The authorization pattern is the same in every handler and is worth stating
once: **the caller's identity comes from their session, and the resource is
loaded by owner.** No handler takes a user id, an account id or a payer from the
request body. `organization_id` is the single exception, and it is a *request* to
bill a tenant that the service verifies against an active membership before any
money is held.

Webhooks are the other direction and get the opposite treatment: the endpoint is
unauthenticated by necessity, so the adapter authenticates the payload before it
is parsed, and the response says as little as possible.
"""

from collections.abc import Sequence
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel import Session, col, select

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.calling.contract import LegState
from app.calling.lifecycle import CallLifecycleService
from app.calling.models import CallAttempt, CallLeg
from app.calling.schemas import (
    AttemptListResponse,
    AttemptResponse,
    AuthorizeRequest,
    CallEventAckResponse,
    ClientSessionRequest,
    ClientSessionResponse,
    EligibilityResponse,
    StartResponse,
    StopRequest,
)
from app.calling.service import CallAuthorizationService
from app.calling.sessions import ClientSessionService

router = APIRouter(tags=["calling"])
webhook_router = APIRouter(tags=["calling"])


def _authorization(request: Request) -> CallAuthorizationService:
    return cast(
        CallAuthorizationService, request.app.state.call_authorization_service
    )


def _sessions(request: Request) -> ClientSessionService:
    return cast(ClientSessionService, request.app.state.client_session_service)


def _lifecycle(request: Request) -> CallLifecycleService:
    return cast(CallLifecycleService, request.app.state.call_lifecycle_service)


def _attempt_response(attempt: CallAttempt) -> AttemptResponse:
    return AttemptResponse(
        attempt_id=attempt.id,
        state=attempt.state.value,
        destination_e164=attempt.e164_destination,
        destination_country=attempt.destination_country,
        identity_e164=attempt.identity_e164,
        currency=attempt.currency,
        max_seconds=attempt.max_seconds,
        max_charge_amount=attempt.max_charge_amount,
        expires_at=attempt.expires_at,
        created_at=attempt.created_at,
        answered_at=attempt.answered_at,
        ended_at=attempt.ended_at,
        end_reason=attempt.end_reason,
        organization_id=attempt.organization_id,
    )


@router.get("/calls/eligibility", response_model=EligibilityResponse)
def eligibility(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    destination: Annotated[str, Query(max_length=32)],
    currency: Annotated[str, Query(min_length=3, max_length=3)],
    organization_id: Annotated[UUID | None, Query()] = None,
    requested_seconds: Annotated[int | None, Query(ge=1, le=14400)] = None,
) -> EligibilityResponse:
    """Price a call and say whether it could start. Holds nothing.

    A preview that reserved money would make a customer's balance flicker as
    they scrolled a contact list, so this deliberately commits nothing — the
    ledger is not touched and no attempt row is written.
    """
    service = _authorization(request)
    with request.app.state.session_factory() as session:
        preview = service.preview(
            session,
            user,
            destination,
            currency=currency.upper(),
            organization_id=organization_id,
            requested_seconds=requested_seconds,
        )
        return EligibilityResponse(
            destination_e164=preview.destination.e164,
            destination_country=preview.destination.country,
            destination_kind=preview.destination.kind.value,
            currency=preview.currency,
            max_seconds=preview.max_seconds,
            max_charge_amount=preview.max_charge_amount,
            rate_per_minute_amount=preview.rate_per_minute_amount,
            setup_amount=preview.setup_amount,
            available_amount=preview.available_amount,
            fundable=preview.fundable,
            route_enabled=preview.route_enabled,
        )


@router.post("/calls/client-session", response_model=ClientSessionResponse)
def issue_client_session(
    payload: ClientSessionRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> ClientSessionResponse:
    """Issue this device a short provider session. The account key never leaves.

    One credential per device, so signing out one installation later does not
    take out the customer's other devices.
    """
    service = _sessions(request)
    with request.app.state.session_factory() as session:
        _credential, issued = service.issue(
            session,
            user,
            device_id=payload.device_id,
            device_label=payload.device_label,
        )
        response = ClientSessionResponse(
            token=issued.token,
            sip_identity=issued.sip_identity,
            expires_at=issued.expires_at,
        )
        session.commit()
        return response


@router.delete("/calls/client-session", status_code=204)
def revoke_client_session(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    device_id: Annotated[str | None, Query(max_length=200)] = None,
) -> None:
    """Revoke this device's credential, or every device's.

    Not gated on the route being enabled: withdrawing a credential is a
    containment action, and a deployment that has just switched calling off is
    exactly when outstanding credentials most need withdrawing.
    """
    service = _sessions(request)
    with request.app.state.session_factory() as session:
        service.revoke(session, user, device_id=device_id, reason="client_revoked")
        session.commit()


@router.post("/calls/authorize", response_model=AttemptResponse, status_code=201)
def authorize_call(
    payload: AuthorizeRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> AttemptResponse:
    """Create one durable grant with the money already held.

    The response carries no provider material. Authorization and dialling are
    separate steps precisely so that holding a grant is not the same as holding
    the means to place a call.
    """
    service = _authorization(request)
    sessions = _sessions(request)
    with request.app.state.session_factory() as session:
        credential_id = None
        if payload.device_id:
            match = [
                credential
                for credential in sessions.active(session, user)
                if credential.device_id == payload.device_id
            ]
            credential_id = match[0].id if match else None
        attempt = service.authorize(
            session,
            user,
            payload.destination,
            idempotency_key=payload.idempotency_key,
            currency=payload.currency.upper(),
            # The outbound identity is chosen by the server from numbers we own.
            # Own-number presentation is deferred and unproven on this route, so
            # there is no request field through which a client could ask for one.
            identity_e164=request.app.state.calling_identity_e164,
            organization_id=payload.organization_id,
            client_credential_id=credential_id,
            requested_seconds=payload.requested_seconds,
        )
        response = _attempt_response(attempt)
        session.commit()
        return response


@router.post("/calls/{attempt_id}/start", response_model=StartResponse)
def start_call(
    attempt_id: UUID,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    device_id: Annotated[str | None, Query(max_length=200)] = None,
) -> StartResponse:
    """Hand the client its instruction for one attempt. Converges on repetition."""
    service = _authorization(request)
    with request.app.state.session_factory() as session:
        instruction = service.start(session, user, attempt_id, device_id=device_id)
        response = StartResponse(
            attempt_id=instruction.attempt_id,
            destination_e164=instruction.destination_e164,
            correlation=instruction.correlation,
            max_seconds=instruction.max_seconds,
            expires_at=instruction.expires_at,
        )
        session.commit()
        return response


@router.post("/calls/{attempt_id}/stop", response_model=AttemptResponse)
def stop_call(
    attempt_id: UUID,
    payload: StopRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> AttemptResponse:
    """End a call. Works whether or not new calling is enabled.

    Termination is never gated on the route flag: disabling new calling must not
    disable termination or financial recovery.
    """
    service = _authorization(request)
    lifecycle = _lifecycle(request)
    with request.app.state.session_factory() as session:
        attempt = service.stop(
            session, user, attempt_id, reason=payload.reason or "stopped"
        )
        for leg in _live_legs(session, attempt):
            lifecycle.hangup(session, attempt, leg)
        response = _attempt_response(attempt)
        session.commit()
        return response


@router.get("/calls/{attempt_id}", response_model=AttemptResponse)
def get_call(
    attempt_id: UUID,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> AttemptResponse:
    service = _authorization(request)
    with request.app.state.session_factory() as session:
        return _attempt_response(service.get(session, user, attempt_id))


@router.get("/calls", response_model=AttemptListResponse)
def list_calls(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    organization_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AttemptListResponse:
    """This caller's calls in one scope.

    Personal and work histories are separate queries, not one query with a
    label. The payer differs and so does who may read them, and a combined list
    would put a member's personal calls in front of whoever can see the
    organization's.
    """
    service = _authorization(request)
    with request.app.state.session_factory() as session:
        attempts = service.history(
            session, user, organization_id=organization_id, limit=limit
        )
        return AttemptListResponse(
            attempts=[_attempt_response(attempt) for attempt in attempts]
        )


@webhook_router.post(
    "/webhooks/calling/events", response_model=CallEventAckResponse, status_code=202
)
async def receive_call_event(request: Request) -> CallEventAckResponse:
    """Ingest a signed provider event, exactly once.

    The **raw** body is read and handed to the adapter unparsed. A signature
    checked against re-serialized JSON verifies what our parser produced rather
    than what was sent, and those differ the moment key order or number
    formatting does.
    """
    body = await request.body()
    headers = {key.lower(): value for key, value in request.headers.items()}
    lifecycle = _lifecycle(request)
    with request.app.state.session_factory() as session:
        lifecycle.ingest(session, body, headers)
        session.commit()
    return CallEventAckResponse(received=True)


def _live_legs(session: Session, attempt: CallAttempt) -> Sequence[CallLeg]:
    """Legs that might still be running up a bill, for a stop request."""
    return session.exec(
        select(CallLeg).where(
            col(CallLeg.attempt_id) == attempt.id,
            col(CallLeg.state) != LegState.ENDED,
        )
    ).all()
