"""Retired check-in surface (US-30, chunk 04B).

The check-in workflow is withdrawn from the product. These routes stay
registered so an old client is told so explicitly rather than being led to
believe a check-in was recorded, or that a delivery receipt was processed.

The `check_ins` and `check_in_notifications` tables and their rows are
untouched; see docs/implementation/retirement/RETENTION-PLAN.md.
"""

from fastapi import APIRouter

from app.retirement import CHECKINS, RETIRED_RESPONSES, RetiredFeatureError

router = APIRouter(tags=["check-ins"])


@router.post("/checkins", status_code=410, responses=RETIRED_RESPONSES)
async def create_checkin() -> None:
    raise RetiredFeatureError(CHECKINS)


@router.get("/me/checkins", status_code=410, responses=RETIRED_RESPONSES)
async def history() -> None:
    raise RetiredFeatureError(CHECKINS)


@router.get("/webhooks/meta/whatsapp", status_code=410, responses=RETIRED_RESPONSES)
def verify_meta_webhook() -> None:
    # This webhook existed only to confirm delivery of retired check-in and SOS
    # family notifications. Nothing dispatches those any more, so there is
    # nothing left for a receipt to correlate to.
    raise RetiredFeatureError(CHECKINS)


@router.post("/webhooks/meta/whatsapp", status_code=410, responses=RETIRED_RESPONSES)
async def meta_webhook() -> None:
    raise RetiredFeatureError(CHECKINS)
