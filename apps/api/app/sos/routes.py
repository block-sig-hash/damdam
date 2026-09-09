"""Retired SOS surface (US-30, chunk 04B).

In-app SOS is withdrawn. Accepting an alert that no operator will ever see is
the most dangerous silent success in the product, so every path -- the traveler
app side and the operator side alike -- refuses explicitly.

Retiring this says nothing about carrier emergency calling on a real cellular
line; that is a separate supplier and legal question under D1.

The `sos_alerts` and `sos_notifications` tables and their rows are untouched.
"""

from uuid import UUID

from fastapi import APIRouter

from app.retirement import RETIRED_RESPONSES, SOS, RetiredFeatureError

router = APIRouter(tags=["SOS"])


@router.post("/sos", status_code=410, responses=RETIRED_RESPONSES)
async def create_sos() -> None:
    raise RetiredFeatureError(SOS)


@router.post("/sos/{alert_id}/cancel", status_code=410, responses=RETIRED_RESPONSES)
async def cancel_sos(alert_id: UUID) -> None:
    del alert_id
    raise RetiredFeatureError(SOS)


@router.get("/hto/sos-alerts", status_code=410, responses=RETIRED_RESPONSES)
async def list_sos() -> None:
    raise RetiredFeatureError(SOS)


@router.post(
    "/hto/sos-alerts/{alert_id}/resolve",
    status_code=410,
    responses=RETIRED_RESPONSES,
)
async def resolve_sos(alert_id: UUID) -> None:
    del alert_id
    raise RetiredFeatureError(SOS)


@router.post("/hto/push-subscriptions", status_code=410, responses=RETIRED_RESPONSES)
async def create_push_subscription() -> None:
    # Operator push existed only to alert on SOS. Registering a token now would
    # promise notifications that will never be sent.
    raise RetiredFeatureError(SOS)
