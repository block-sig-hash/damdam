import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

import httpx

from app.config import Settings


class EsimProviderError(Exception):
    pass


class EsimProviderPending(EsimProviderError):
    """A vendor accepted the idempotent order but has not allocated it yet."""


@dataclass(frozen=True)
class EsimIssueRequest:
    package_id: UUID
    user_id: UUID
    data_gb: int
    destination_country: str


@dataclass(frozen=True)
class EsimIssuedProfile:
    iccid: str
    activation_code_lpa: str
    qr_code_url: str


class EsimProvider(Protocol):
    name: str

    def issue(self, request: EsimIssueRequest) -> EsimIssuedProfile: ...


class HttpEsimProvider:
    """Partner-adapter boundary for vendor APIs that are not publicly documented.

    Monty Mobile and 1GLOBAL provide their commercial issuance schemas during
    onboarding. Their configured adapter URLs normalize that private contract;
    routes and lifecycle services remain vendor-agnostic.
    """

    def __init__(self, name: str, base_url: str, api_key: str, timeout: int) -> None:
        self.name = name
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout

    def issue(self, request: EsimIssueRequest) -> EsimIssuedProfile:
        if not self.base_url or not self.api_key:
            raise EsimProviderError(f"{self.name} is not configured")
        try:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/esims",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Idempotency-Key": str(request.package_id),
                },
                json={
                    "package_reference": str(request.package_id),
                    "destination_country": request.destination_country,
                    "data_gb": request.data_gb,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data", payload)
            activation_code = data.get("activation_code_lpa") or data.get("lpa")
            if activation_code is None:
                raise KeyError("activation_code_lpa")
            return EsimIssuedProfile(
                iccid=str(data["iccid"]),
                activation_code_lpa=str(activation_code),
                qr_code_url=str(data["qr_code_url"]),
            )
        except (
            AttributeError,
            httpx.HTTPError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise EsimProviderError(f"{self.name} issuance failed") from exc


class EsimAccessProvider:
    name = "esim_access"

    def __init__(
        self,
        settings: Settings,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.monotonic = monotonic
        self.sleeper = sleeper

    def issue(self, request: EsimIssueRequest) -> EsimIssuedProfile:
        package_key = f"{request.destination_country}:{request.data_gb}"
        package_code = self.settings.esim_access_package_codes.get(package_key)
        if not all(
            (
                self.settings.esim_access_base_url,
                self.settings.esim_access_access_code,
                self.settings.esim_access_secret_key,
                package_code,
            )
        ):
            raise EsimProviderError("esim_access is not configured for this tier")
        order = self._post(
            "/api/v1/open/esim/order",
            {
                "transactionId": str(request.package_id),
                "packageInfoList": [{"packageCode": package_code, "count": 1}],
            },
        )
        order_object = order.get("obj")
        if not isinstance(order_object, dict) or not order_object.get("orderNo"):
            raise EsimProviderError("esim_access order failed")
        order_number = str(order_object["orderNo"])

        deadline = (
            self.monotonic()
            + self.settings.esim_access_allocation_timeout_seconds
        )
        while self.monotonic() <= deadline:
            try:
                result = self._post(
                    "/api/v1/open/esim/query",
                    {
                        "orderNo": order_number,
                        "pager": {"pageNum": 1, "pageSize": 5},
                    },
                    allow_pending=True,
                )
            except EsimProviderError as exc:
                # The order is already accepted/billable. Any subsequent
                # query failure must retry this transaction id, never cascade
                # and purchase another supplier's profile.
                raise EsimProviderPending(
                    "esim_access allocation status is temporarily unavailable"
                ) from exc
            result_object = result.get("obj")
            profiles = (
                result_object.get("esimList")
                if isinstance(result_object, dict)
                else None
            )
            profile = profiles[0] if isinstance(profiles, list) and profiles else None
            if isinstance(profile, dict) and all(
                profile.get(field) for field in ("iccid", "ac", "qrCodeUrl")
            ):
                return EsimIssuedProfile(
                    iccid=str(profile["iccid"]),
                    activation_code_lpa=str(profile["ac"]),
                    qr_code_url=str(profile["qrCodeUrl"]),
                )
            self.sleeper(1)
        # The order was accepted, so cascading would risk buying a duplicate
        # profile. A retry uses the same transactionId and resumes this vendor.
        raise EsimProviderPending("esim_access allocation is still pending")

    def _post(
        self,
        path: str,
        payload: dict[str, object],
        *,
        allow_pending: bool = False,
    ) -> dict[str, object]:
        body = json.dumps(payload, separators=(",", ":"))
        timestamp = str(int(time.time()))
        request_id = uuid4().hex
        signed = (
            timestamp
            + request_id
            + self.settings.esim_access_access_code
            + body
        )
        signature = hmac.new(
            self.settings.esim_access_secret_key.encode(),
            signed.encode(),
            hashlib.sha256,
        ).hexdigest()
        try:
            response = httpx.post(
                f"{self.settings.esim_access_base_url.rstrip('/')}{path}",
                headers={
                    "Content-Type": "application/json",
                    "RT-AccessCode": self.settings.esim_access_access_code,
                    "RT-RequestID": request_id,
                    "RT-Timestamp": timestamp,
                    "RT-Signature": signature,
                },
                content=body,
                timeout=self.settings.esim_request_timeout_seconds,
            )
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EsimProviderError("esim_access request failed") from exc
        if not isinstance(result, dict):
            raise EsimProviderError("esim_access returned an invalid response")
        failed = result.get("success") is False or str(
            result.get("success")
        ).lower() == "false"
        if failed and not (
            allow_pending and str(result.get("errorCode")) == "200010"
        ):
            raise EsimProviderError("esim_access request failed")
        return result


def build_esim_providers(settings: Settings) -> dict[str, EsimProvider]:
    return {
        "monty_mobile": HttpEsimProvider(
            "monty_mobile",
            settings.monty_mobile_base_url,
            settings.monty_mobile_api_key,
            settings.esim_request_timeout_seconds,
        ),
        "esim_access": EsimAccessProvider(settings),
        "1global": HttpEsimProvider(
            "1global",
            settings.oneglobal_base_url,
            settings.oneglobal_api_key,
            settings.esim_request_timeout_seconds,
        ),
    }
