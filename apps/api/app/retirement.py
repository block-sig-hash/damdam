"""Explicit refusals for features the product reset retires (US-30, chunk 04).

A retired endpoint must not answer as though it still works. The original
finding was that an old client could queue a check-in or an SOS alert and be
told it had been received, for a workflow nobody operates any more. Returning
404 would be nearly as bad: it reads as a routing fault the client should retry.

So retired endpoints answer 410 Gone with a stable machine-readable code. The
route stays registered precisely so the refusal can be explicit, and the
response names the feature and asks for an upgrade.

Retirement authority is recorded in docs/implementation/SCOPE-DISPOSITION.md.
No table is dropped and no record is deleted here -- this module withdraws the
behavior, not the data.
"""

from typing import Any

from pydantic import BaseModel, Field

CHECKINS = "checkins"
SOS = "sos"
FAMILY_CONTACTS = "family_contacts"
EMERGENCY_CONTACT = "emergency_contact"
ARRIVAL_GEOFENCE = "arrival_geofence"
VERIFIED_CLI = "verified_cli"
APP_VOICE = "app_voice"

RETIRED_FEATURES = frozenset(
    {
        CHECKINS,
        SOS,
        FAMILY_CONTACTS,
        EMERGENCY_CONTACT,
        ARRIVAL_GEOFENCE,
        VERIFIED_CLI,
        APP_VOICE,
    }
)

RETIRED_ERROR_CODE = "feature_retired"


class RetiredFeatureError(Exception):
    """Raised by a route whose feature has been withdrawn from the product."""

    def __init__(self, feature: str) -> None:
        if feature not in RETIRED_FEATURES:
            raise ValueError(f"unknown retired feature: {feature}")
        self.feature = feature
        self.code = RETIRED_ERROR_CODE
        super().__init__(f"{RETIRED_ERROR_CODE}:{feature}")


class RetiredFeatureResponse(BaseModel):
    """The documented body of a retirement refusal.

    Old clients parse `error` and `details.feature` to decide what to tell the
    user, so the shape is part of the published contract, not an incidental
    detail of the handler.
    """

    error: str = Field(default=RETIRED_ERROR_CODE, examples=[RETIRED_ERROR_CODE])
    message: str
    details: dict[str, object] = Field(
        examples=[{"feature": SOS, "upgrade_required": True}]
    )


RETIRED_RESPONSES: dict[int | str, dict[str, Any]] = {
    410: {
        "description": "This feature has been retired from the product.",
        "model": RetiredFeatureResponse,
    }
}
