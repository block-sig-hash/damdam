"""The documented Telnyx Wireless contract, transcribed — not invented.

Every path, field name, enum value and error code here is copied from official
Telnyx documentation and recorded in
`docs/implementation/telnyx/API-CONTRACTS.md`. Nothing is guessed.

Chunk 03 wrote the first transcription under `tools/telnyx_probe/`, deliberately
outside the application, because there was nothing yet to wire it to. Chunk 15
is that wiring, so the transcription moves here and the probe imports it. One
transcription, one place to correct when Telnyx changes something — a second
copy under `tools/` would drift the first time only one of them was updated.

**Re-verified 10 September 2026** against the published OpenAPI source at
`https://developers.telnyx.com/openapi/source/external/wireless/wireless.json`
and the prose documentation. Three corrections to chunk 03's record came out of
that pass, and each one matters:

1. `GET /sim_cards/{id}/activation_code` **exists** and returns
   `SIMCardActivationCode.activation_code`, "Contents of the eSIM activation QR
   code". Chunk 03 recorded no way to obtain the profile; there is one.
2. The Wireless Detail Record report path is `/wireless/detail_records_reports`,
   not `/wireless/detail/records/reports`. The old path would have 404'd.
3. The OpenAPI `SIMCardStatus` enum lists **eight** values and omits
   `unauthorized_imei`, `blocked` and `abolished`, which the prose lifecycle
   page documents as real system-imposed statuses. The two official sources
   disagree, so this module accepts the union and says why.

Where the documentation is silent, this module is silent too. There is no
`Idempotency-Key` here, because Telnyx documents none, and inventing a
plausible-looking field is exactly the failure this transcription exists to
prevent.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any
from uuid import UUID

# https://api.telnyx.com/v2 -- from the published OpenAPI `servers` block.
API_BASE_URL = "https://api.telnyx.com/v2"

PURCHASE_ESIMS_PATH = "/actions/purchase/esims"
LIST_SIM_CARDS_PATH = "/sim_cards"
SIM_CARD_PATH = "/sim_cards/{id}"
#: The eSIM profile itself. Verified present in the OpenAPI source 2026-09-10.
ACTIVATION_CODE_PATH = "/sim_cards/{id}/activation_code"
SIM_CARD_ACTIONS_PATH = "/sim_card_actions"
SIM_CARD_ACTION_PATH = "/sim_card_actions/{id}"
ENABLE_PATH = "/sim_cards/{id}/actions/enable"
DISABLE_PATH = "/sim_cards/{id}/actions/disable"
SET_STANDBY_PATH = "/sim_cards/{id}/actions/set_standby"
ENABLE_VOICE_PATH = "/sim_cards/{id}/actions/enable_voice"
DISABLE_VOICE_PATH = "/sim_cards/{id}/actions/disable_voice"
WDR_REPORTS_PATH = "/wireless/detail_records_reports"
WDR_REPORT_PATH = "/wireless/detail_records_reports/{id}"

#: Tag prefix used to correlate a purchase attempt with the SIMs it created.
#: `tags` is the only client-supplied, filterable field on eSIM purchase, so it
#: is the only documented reconciliation key available. See API-CONTRACTS.md §2.
OPERATION_TAG_PREFIX = "damdam-op-"


class SimCardStatus(str, Enum):
    """SIM card statuses, from the SIM lifecycle documentation.

    User-controlled, transitional and system-imposed states are distinguished
    because they demand different handling: a transitional state means "ask
    again later", a system-imposed one means "something else must change first".

    The OpenAPI enum omits the last three. The prose lifecycle page documents
    them, including how to exit each one, so dropping them here would make a
    real supplier response parse as a contract violation.
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


class SimCardActionType(str, Enum):
    """`SIMCardAction.action_type`, verbatim from the OpenAPI enum."""

    ENABLE = "enable"
    ENABLE_STANDBY_SIM_CARD = "enable_standby_sim_card"
    DISABLE = "disable"
    SET_STANDBY = "set_standby"
    ENABLE_VOICE = "enable_voice"
    DISABLE_VOICE = "disable_voice"


class SimCardActionStatus(str, Enum):
    """`SIMCardAction.status.value`, verbatim.

    `INTERRUPTED` appears in the response enum but not in the `filter[status]`
    enum, so an interrupted action cannot be found by filtering for it. It is
    reachable only by id or by listing without a status filter.
    """

    IN_PROGRESS = "in-progress"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


#: An action in one of these has settled. Anything else is still open, and an
#: open action is not evidence that the state change happened.
TERMINAL_ACTION_STATUSES = frozenset(
    {
        SimCardActionStatus.COMPLETED,
        SimCardActionStatus.FAILED,
        SimCardActionStatus.INTERRUPTED,
    }
)


class EsimInstallationStatus(str, Enum):
    """`SimpleSIMCard.esim_installation_status` — two values, and neither of
    them means "installed on a handset".

    This is the field somebody will eventually mistake for proof of
    installation. `released` means the profile has been released for download.
    Whether a person actually scanned it is not something Telnyx observes, and
    `AGENTS.md` requires installation and activation to stay separate facts.
    """

    RELEASED = "released"
    DISABLED = "disabled"


class WirelessErrorCode(str, Enum):
    """Documented Wireless API error codes.

    Source: https://developers.telnyx.com/docs/iot-sim/api-errors
    Re-verified verbatim 2026-09-10; unchanged.
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

#: `data_limit` and `current_billing_period_consumed_data` carry `unit`, and
#: the documented enum is MB or GB. Decimal, not float: the amount arrives as a
#: string like "2048.1" and binary floating point cannot represent it exactly.
_UNIT_BYTES: dict[str, int] = {"MB": 1_000_000, "GB": 1_000_000_000}


class ContractViolation(ValueError):
    """Our request or our parsing disagrees with the documented contract."""


def operation_tag(operation_reference: UUID) -> str:
    """Build the correlation tag for one provisioning attempt.

    The operation reference must be persisted before dispatch (prd.md AC-32.4);
    this turns it into the supplier-visible key we can later search on.
    """
    return f"{OPERATION_TAG_PREFIX}{operation_reference}"


@dataclass(frozen=True)
class DataAmount:
    """A `{amount, unit}` pair, converted to exact bytes.

    Telnyx sends the amount as a **string** and the unit as MB or GB. Both
    matter. `float("2048.1") * 1_000_000` is 2048099999.9999998, and a byte
    count that is off by one in the customer's disfavour is a billing defect
    however small it looks — so the conversion goes through `Decimal`.

    The documented units are decimal MB/GB, not MiB/GiB. Assuming binary
    prefixes would inflate every allowance by 4.9%.
    """

    amount: Decimal
    unit: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> DataAmount | None:
        if payload is None:
            return None
        if not isinstance(payload, Mapping):
            raise ContractViolation("data amount must be an object or null")
        raw_amount = payload.get("amount")
        unit = payload.get("unit", "MB")
        if raw_amount is None:
            return None
        if not isinstance(unit, str) or unit not in _UNIT_BYTES:
            raise ContractViolation(
                f"undocumented data unit {unit!r}; the documented enum is MB|GB"
            )
        try:
            amount = Decimal(str(raw_amount))
        except (InvalidOperation, TypeError) as exc:
            raise ContractViolation(
                f"data amount {raw_amount!r} is not a number"
            ) from exc
        if amount < 0:
            raise ContractViolation("data amount cannot be negative")
        return cls(amount=amount, unit=unit)

    @property
    def bytes(self) -> int:
        """Exact bytes, rounded down.

        Down rather than to-nearest on purpose: this is used both for what a
        customer has consumed and for what a supplier says a limit is, and
        rounding consumption *up* would charge for bytes nobody sent.
        """
        return int(self.amount * _UNIT_BYTES[self.unit])


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
        if type(self.amount) is not int:
            raise ContractViolation("amount must be an integer")
        if self.amount < 1:
            raise ContractViolation("amount must be at least 1 (documented minimum)")
        if not isinstance(self.operation_reference, UUID):
            raise ContractViolation("operation_reference must be a UUID")
        if self.status is not None and not isinstance(self.status, SimCardStatus):
            raise ContractViolation("status must be a documented SimCardStatus")
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
            if not _WHITELABEL_NAME.fullmatch(self.whitelabel_name):
                raise ContractViolation(
                    "whitelabel_name must contain only letters, numbers and "
                    "whitespace"
                )
        if not isinstance(self.extra_tags, tuple) or not all(
            isinstance(tag, str) for tag in self.extra_tags
        ):
            raise ContractViolation("extra_tags must be a tuple of strings")

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
    """The subset of `SimpleSIMCard` / `SIMCard` this integration reads.

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
    msisdn: str | None = None
    sim_card_group_id: str | None = None
    actions_in_progress: bool | None = None
    data_limit: DataAmount | None = None
    consumed_data: DataAmount | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> SimCard:
        if not isinstance(payload, Mapping):
            raise ContractViolation("SIM card payload must be an object")
        card_id = payload.get("id")
        if not isinstance(card_id, str) or not card_id:
            raise ContractViolation("SIM card payload has no 'id'")
        raw_status = payload.get("status")
        # Telnyx returns status as an object in some responses and a bare
        # string in others; accept both rather than guessing one.
        if isinstance(raw_status, Mapping):
            raw_status = raw_status.get("value")
        try:
            status = SimCardStatus(raw_status)
        except (TypeError, ValueError) as exc:
            raise ContractViolation(
                f"undocumented SIM card status {raw_status!r} -- the contract "
                "record needs updating before this is treated as expected"
            ) from exc
        raw_tags = payload.get("tags")
        if raw_tags is None:
            tags: tuple[str, ...] = ()
        elif (
            not isinstance(raw_tags, Sequence)
            or isinstance(raw_tags, str | bytes)
            or not all(isinstance(tag, str) for tag in raw_tags)
        ):
            raise ContractViolation("SIM card 'tags' must be an array of strings")
        else:
            tags = tuple(raw_tags)

        def optional_string(field_name: str) -> str | None:
            value = payload.get(field_name)
            if value is not None and not isinstance(value, str):
                raise ContractViolation(
                    f"SIM card {field_name!r} must be a string or null"
                )
            return value

        def optional_bool(field_name: str) -> bool | None:
            value = payload.get(field_name)
            if value is not None and not isinstance(value, bool):
                raise ContractViolation(
                    f"SIM card {field_name!r} must be boolean or null"
                )
            return value

        installation_status = optional_string("esim_installation_status")
        if installation_status is not None:
            try:
                EsimInstallationStatus(installation_status)
            except ValueError as exc:
                raise ContractViolation(
                    f"undocumented esim_installation_status "
                    f"{installation_status!r}; the documented enum is "
                    "released|disabled"
                ) from exc

        return cls(
            id=card_id,
            status=status,
            type=optional_string("type"),
            iccid=optional_string("iccid"),
            tags=tags,
            voice_enabled=optional_bool("voice_enabled"),
            esim_installation_status=installation_status,
            msisdn=optional_string("msisdn"),
            sim_card_group_id=optional_string("sim_card_group_id"),
            actions_in_progress=optional_bool("actions_in_progress"),
            data_limit=DataAmount.from_payload(payload.get("data_limit")),
            consumed_data=DataAmount.from_payload(
                payload.get("current_billing_period_consumed_data")
            ),
            raw=dict(payload),
        )


@dataclass(frozen=True)
class SimCardAction:
    """`SIMCardAction` — the receipt for an asynchronous state change.

    Every lifecycle endpoint returns 202 with one of these. The action id is
    the only handle on whether the change actually happened, which is why
    nothing in this integration treats a 202 as a completed transition.
    """

    id: str
    sim_card_id: str | None
    action_type: SimCardActionType | None
    status: SimCardActionStatus
    reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> SimCardAction:
        if not isinstance(payload, Mapping):
            raise ContractViolation("SIM card action payload must be an object")
        action_id = payload.get("id")
        if not isinstance(action_id, str) or not action_id:
            raise ContractViolation("SIM card action payload has no 'id'")
        raw_status = payload.get("status")
        reason: str | None = None
        if isinstance(raw_status, Mapping):
            reason = raw_status.get("reason")
            raw_status = raw_status.get("value")
        if reason is not None and not isinstance(reason, str):
            raise ContractViolation("action status 'reason' must be a string or null")
        try:
            status = SimCardActionStatus(raw_status)
        except (TypeError, ValueError) as exc:
            raise ContractViolation(
                f"undocumented SIM card action status {raw_status!r}"
            ) from exc
        raw_action_type = payload.get("action_type")
        action_type: SimCardActionType | None = None
        if raw_action_type is not None:
            try:
                action_type = SimCardActionType(raw_action_type)
            except (TypeError, ValueError) as exc:
                raise ContractViolation(
                    f"undocumented action_type {raw_action_type!r}"
                ) from exc
        sim_card_id = payload.get("sim_card_id")
        if sim_card_id is not None and not isinstance(sim_card_id, str):
            raise ContractViolation("action 'sim_card_id' must be a string or null")
        return cls(
            id=action_id,
            sim_card_id=sim_card_id,
            action_type=action_type,
            status=status,
            reason=reason,
            raw=dict(payload),
        )

    @property
    def is_settled(self) -> bool:
        return self.status in TERMINAL_ACTION_STATUSES

    @property
    def succeeded(self) -> bool:
        return self.status is SimCardActionStatus.COMPLETED


@dataclass(frozen=True)
class ActivationCode:
    """`SIMCardActivationCode` — "Contents of the eSIM activation QR code".

    This is installation material. It is one-time use: Telnyx documents that a
    lost profile cannot be re-downloaded and needs a fresh purchase. It never
    goes in a log, a fixture, a handoff or an error message, which is why this
    type has no `__repr__` of its value and the vault stores it encrypted.
    """

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value:
            raise ContractViolation("activation_code must be a non-empty string")

    def __repr__(self) -> str:  # pragma: no cover - defensive, but exercised
        return "ActivationCode(<redacted>)"

    __str__ = __repr__

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ActivationCode:
        if not isinstance(payload, Mapping):
            raise ContractViolation("activation code payload must be an object")
        value = payload.get("activation_code")
        if not isinstance(value, str) or not value:
            raise ContractViolation("activation code payload has no 'activation_code'")
        return cls(value=value)


@dataclass(frozen=True)
class WirelessError:
    code: str
    title: str | None = None
    detail: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> WirelessError:
        if not isinstance(payload, Mapping):
            raise ContractViolation("Wireless error payload must be an object")
        code = payload.get("code")
        if not isinstance(code, str) or not code:
            raise ContractViolation("Wireless error payload has no string 'code'")
        title = payload.get("title")
        detail = payload.get("detail")
        if title is not None and not isinstance(title, str):
            raise ContractViolation("Wireless error 'title' must be a string or null")
        if detail is not None and not isinstance(detail, str):
            raise ContractViolation("Wireless error 'detail' must be a string or null")
        return cls(
            code=code,
            title=title,
            detail=detail,
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
    def from_payload(cls, payload: Mapping[str, Any]) -> ESimPurchaseResponse:
        if not isinstance(payload, Mapping):
            raise ContractViolation("eSIM purchase response must be an object")
        data = payload.get("data") or []
        errors = payload.get("errors") or []
        if not isinstance(data, list):
            raise ContractViolation("eSIM purchase response 'data' must be an array")
        if not isinstance(errors, list):
            raise ContractViolation("eSIM purchase response 'errors' must be an array")
        return cls(
            sim_cards=tuple(SimCard.from_payload(item) for item in data),
            errors=tuple(WirelessError.from_payload(item) for item in errors),
        )
