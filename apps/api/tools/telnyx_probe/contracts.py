"""Moved to `app/connectivity/telnyx_contract.py` by chunk 15.

Chunk 03 transcribed the documented Telnyx contract here, outside the
application, because nothing in the application used it yet. Chunk 15 wires the
same shapes to a real adapter, so the transcription moved and this module
re-exports it.

Keeping a second copy would have been worse than the indirection: two
transcriptions of the same vendor documentation drift the first time only one of
them is corrected, and the whole point of a transcription is that it is exactly
what Telnyx publishes.
"""

from app.connectivity.telnyx_contract import (
    API_BASE_URL,
    CAPACITY_ERROR_CODES,
    FILTERABLE_STATUSES,
    LIST_SIM_CARDS_PATH,
    OPERATION_TAG_PREFIX,
    PURCHASE_ESIMS_PATH,
    SYSTEM_IMPOSED_STATUSES,
    TERMINAL_ERROR_CODES,
    TRANSITIONAL_STATUSES,
    ContractViolation,
    ESimPurchaseRequest,
    ESimPurchaseResponse,
    SimCard,
    SimCardStatus,
    WirelessError,
    WirelessErrorCode,
    operation_tag,
)

__all__ = [
    "API_BASE_URL",
    "CAPACITY_ERROR_CODES",
    "FILTERABLE_STATUSES",
    "LIST_SIM_CARDS_PATH",
    "OPERATION_TAG_PREFIX",
    "PURCHASE_ESIMS_PATH",
    "SYSTEM_IMPOSED_STATUSES",
    "TERMINAL_ERROR_CODES",
    "TRANSITIONAL_STATUSES",
    "ContractViolation",
    "ESimPurchaseRequest",
    "ESimPurchaseResponse",
    "SimCard",
    "SimCardStatus",
    "WirelessError",
    "WirelessErrorCode",
    "operation_tag",
]
