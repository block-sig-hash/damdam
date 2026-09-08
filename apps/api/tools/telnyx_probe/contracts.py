"""Documented Telnyx Wireless contracts, transcribed — not invented.

Every field name, enum value and error code here is copied from official Telnyx
documentation fetched on 2026-09-08 and cited in
`docs/implementation/telnyx/API-CONTRACTS.md`. Nothing is guessed.

Where the documentation is silent, this module is silent too: there is no
`Idempotency-Key` here, because Telnyx does not document one, and inventing a
plausible-looking field is exactly the failure mode this harness exists to
avoid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID

# https://api.telnyx.com/v2 -- from the published OpenAPI `servers` block.
API_BASE_URL = "https://api.telnyx.com/v2"

PURCHASE_ESIMS_PATH = "/actions/purchase/esims"
LIST_SIM_CARDS_PATH = "/sim_cards"

#: Tag prefix used to correlate a purchase attempt with the SIMs it created.
#: `tags` is the only client-supplied, filterable field on eSIM purchase, so it
#: is the only documented reconciliation key available. See API-CONTRACTS.md §2.
OPERATION_TAG_PREFIX = "damdam-op-"


class SimCardStatus(str, Enum):
    """SIM card statuses, from the SIM lifecycle documentation.

    User-controlled, transitional and system-imposed states are distinguished
    because they demand different handling: a transitional state means "ask
    again later", a system-imposed one means "something else must change first".
    """

    # User-controlled
    ENABLED = "enabled"
    DISABLED = "disabled"
    STANDBY = "standby"
    # Transitional -- all lifecycle actions return 202 and settle asynchronously
    REGISTERING = "registering"
    ENABLING = "enabling"
    DISABLING = "disabling"
    SETTING_STANDBY = "setting_standby"
    # System-imposed -- the SIM cannot transition while in these
    DATA_LIMIT_EXCEEDED = "data_limit_exceeded"
    UNAUTHORIZED_IMEI = "unauthorized_imei"
    BLOCKED = "blocked"
    ABOLISHED = "abolished"


TRANSITIONAL_STATUSES = frozenset(
    {
        SimCardStatus.REGISTERING,
        SimCardStatus.ENABLING,
        SimCardStatus.DISABLING,
        SimCardStatus.SETTING_STANDBY,
    }
)

SYSTEM_IMPOSED_STATUSES = frozenset(
    {
        SimCardStatus.DATA_LIMIT_EXCEEDED,
        SimCardStatus.UNAUTHORIZED_IMEI,
        SimCardStatus.BLOCKED,
        SimCardStatus.ABOLISHED,
    }
)

#: Statuses accepted by `filter[status]` on GET /sim_cards. Note that the
#: documented filter does NOT include the transitional states or
#: blocked/abolished -- a SIM mid-transition may therefore be invisible to a
#: status-filtered lookup. Reconciliation must not filter by status.
FILTERABLE_STATUSES = frozenset(
    {
        SimCardStatus.ENABLED,
        SimCardStatus.DISABLED,
        SimCardStatus.STANDBY,
        SimCardStatus.DATA_LIMIT_EXCEEDED,
        SimCardStatus.UNAUTHORIZED_IMEI,
    }
)


class WirelessErrorCode(str, Enum):
    """Documented Wireless API error codes.

    Source: https://developers.telnyx.com/docs/iot-sim/api-errors
    """

    DATA_LIMIT_REACHED = "70000"
    NOT_ENOUGH_SIM_CARDS = "70001"
    INVALID_DATA_FORMAT = "70002"
    OPERATOR_PRIORITIES_OUT_OF_SEQUENCE = "70003"
    OTA_UPDATE_IN_PROGRESS = "70004"
    GROUP_HAS_SIMS = "70005"
    CANNOT_DELETE_DEFAULT_GROUP = "70006"
    SIM_HAS_NO_GROUP = "70007"
    PUBLIC_IPS_UNAVAILABLE = "70008"


#: Errors that mean "the request was understood and refused for a reason that
#: will not change by retrying the same request". Retrying these is a bug.
TERMINAL_ERROR_CODES = frozenset(
    {
        WirelessErrorCode.INVALID_DATA_FORMAT,
        WirelessErrorCode.OPERATOR_PRIORITIES_OUT_OF_SEQUENCE,
        WirelessErrorCode.GROUP_HAS_SIMS,
        WirelessErrorCode.CANNOT_DELETE_DEFAULT_GROUP,
        WirelessErrorCode.SIM_HAS_NO_GROUP,
    }
)

#: Errors that reflect a transient supplier-side capacity or state condition.
#: Retryable later -- but never blindly, and never without reconciling first.
CAPACITY_ERROR_CODES = frozenset(
    {
        WirelessErrorCode.NOT_ENOUGH_SIM_CARDS,
        WirelessErrorCode.PUBLIC_IPS_UNAVAILABLE,
        WirelessErrorCode.OTA_UPDATE_IN_PROGRESS,
    }
)

#: Telnyx documents whitelabel_name as "letters, numbers and whitespaces" only.
_WHITELABEL_NAME = re.compile(r"^[A-Za-z0-9 ]+$")


class ContractViolation(ValueError):
    """Our request or our parsing disagrees with the documented contract."""


def operation_tag(operation_reference: UUID) -> str:
    """Build the correlation tag for one provisioning attempt.

    The operation reference must be persisted before dispatch (prd.md AC-32.4);
    this turns it into the supplier-visible key we can later search on.
    """
    return f"{OPERATION_TAG_PREFIX}{operation_reference}"


@dataclass(frozen=True)
class ESimPurchaseRequest:
    """Request body for POST /actions/purchase/esims.

    Field names and constraints are the published `ESimPurchase` schema. There
    is deliberately no idempotency field: Telnyx does not document one.
    """

    amount: int
    operation_reference: UUID
    sim_card_group_id: UUID | None = None
    product: str | None = None
    whitelabel_name: str | None = None
    status: SimCardStatus | None = None
    extra_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.amount < 1:
            raise ContractViolation("amount must be at least 1 (documented minimum)")
        if self.status is not None and self.status not in {
            SimCardStatus.ENABLED,
            SimCardStatus.DISABLED,
            SimCardStatus.STANDBY,
        }:
            raise ContractViolation(
                f"status {self.status.value!r} is not accepted on purchase; "
                "the documented enum is enabled|disabled|standby"
            )
        if self.whitelabel_name is not None:
            if self.product != "whitelabel":
                raise ContractViolation(
                    "whitelabel_name requires product='whitelabel'"
                )
            if not _WHITELABEL_NAME.match(self.whitelabel_name):
                raise ContractViolation(
                    "whitelabel_name must contain only letters, numbers and "
                    "whitespace"
                )

    @property
    def correlation_tag(self) -> str:
        return operation_tag(self.operation_reference)

    def to_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "amount": self.amount,
            "tags": [self.correlation_tag, *self.extra_tags],
        }
        if self.sim_card_group_id is not None:
            body["sim_card_group_id"] = str(self.sim_card_group_id)
        if self.product is not None:
            body["product"] = self.product
        if self.whitelabel_name is not None:
            body["whitelabel_name"] = self.whitelabel_name
        if self.status is not None:
            body["status"] = self.status.value
        return body


@dataclass(frozen=True)
class SimCard:
    """The subset of `SimpleSIMCard` this harness reads.

    Unknown fields are preserved in `raw` rather than dropped, so a contract
    change shows up in evidence instead of being silently discarded.
    """

    id: str
    status: SimCardStatus
    type: str | None
    iccid: str | None
    tags: tuple[str, ...]
    voice_enabled: bool | None
    esim_installation_status: str | None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SimCard:
        if "id" not in payload:
            raise ContractViolation("SIM card payload has no 'id'")
        raw_status = payload.get("status")
        # Telnyx returns status as an object in some responses and a bare
        # string in others; accept both rather than guessing one.
        if isinstance(raw_status, dict):
            raw_status = raw_status.get("value")
        try:
            status = SimCardStatus(raw_status)
        except ValueError as exc:
            raise ContractViolation(
                f"undocumented SIM card status {raw_status!r} -- the contract "
                "record needs updating before this is treated as expected"
            ) from exc
        return cls(
            id=str(payload["id"]),
            status=status,
            type=payload.get("type"),
            iccid=payload.get("iccid"),
            tags=tuple(payload.get("tags") or ()),
            voice_enabled=payload.get("voice_enabled"),
            esim_installation_status=payload.get("esim_installation_status"),
            raw=payload,
        )


@dataclass(frozen=True)
class WirelessError:
    code: str
    title: str | None = None
    detail: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> WirelessError:
        return cls(
            code=str(payload.get("code", "")),
            title=payload.get("title"),
            detail=payload.get("detail"),
        )

    @property
    def is_terminal(self) -> bool:
        return self.code in {e.value for e in TERMINAL_ERROR_CODES}

    @property
    def is_capacity(self) -> bool:
        return self.code in {e.value for e in CAPACITY_ERROR_CODES}


@dataclass(frozen=True)
class ESimPurchaseResponse:
    """Parsed 202 body: `{data: SimpleSIMCard[], errors: Error[]}`."""

    sim_cards: tuple[SimCard, ...]
    errors: tuple[WirelessError, ...]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ESimPurchaseResponse:
        return cls(
            sim_cards=tuple(
                SimCard.from_payload(item) for item in payload.get("data") or ()
            ),
            errors=tuple(
                WirelessError.from_payload(item)
                for item in payload.get("errors") or ()
            ),
        )
