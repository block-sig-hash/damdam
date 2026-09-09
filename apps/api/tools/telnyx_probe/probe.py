"""Non-production probe CLI for the documented Telnyx Wireless contracts.

Two modes:

* ``--mode fixtures`` (default) runs entirely offline against the scrubbed
  fixtures in ``fixtures/``. It proves our request construction, parsing and
  reconciliation decisions match the documented schemas. It proves **nothing**
  about Telnyx's real behaviour, and it says so in its own output.

* ``--mode live`` is read-only and hard-gated. It requires an API key in the
  environment *and* an explicit authorization flag, and it will not issue any
  request that creates, changes, deletes or spends -- there is no code path in
  this file that can POST to the purchase endpoint.

Run:

    python -m tools.telnyx_probe.probe --mode fixtures
    python -m tools.telnyx_probe.probe --mode live --i-have-authorization \
        --tag damdam-op-<uuid>
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from .contracts import (
    API_BASE_URL,
    LIST_SIM_CARDS_PATH,
    PURCHASE_ESIMS_PATH,
    ContractViolation,
    ESimPurchaseRequest,
    ESimPurchaseResponse,
    SimCard,
    SimCardStatus,
)
from .reconcile import reconcile_purchase

FIXTURES = Path(__file__).parent / "fixtures"

SIMULATION_BANNER = (
    "SIMULATED -- fixture-driven. This exercises our own request construction, "
    "parsing and reconciliation against shapes transcribed from Telnyx "
    "documentation. It is not evidence of Telnyx behaviour, coverage, pricing "
    "or availability. D1 remains OPEN."
)


def load_fixture(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    if payload.get("_fixture") != "SIMULATED":
        raise ContractViolation(
            f"fixture {name} is not labelled SIMULATED; every fixture in this "
            "harness must declare that it is not real supplier evidence"
        )
    return payload


def _report(line: str) -> None:
    sys.stdout.write(f"{line}\n")


def run_fixture_mode() -> int:
    _report(SIMULATION_BANNER)
    _report("")

    operation = UUID("11111111-1111-4111-8111-111111111111")
    request = ESimPurchaseRequest(
        amount=2,
        operation_reference=operation,
        product="whitelabel",
        whitelabel_name="DamDam",
        status=SimCardStatus.STANDBY,
    )
    _report(f"POST {API_BASE_URL}{PURCHASE_ESIMS_PATH}")
    _report(f"  body: {json.dumps(request.to_body(), sort_keys=True)}")
    _report("  note: the documented schema has no idempotency key.")
    _report("")

    accepted = ESimPurchaseResponse.from_payload(
        load_fixture("purchase_esims_202_success.json")
    )
    _report(
        f"202 parsed: {len(accepted.sim_cards)} eSIM(s), "
        f"{len(accepted.errors)} error(s)"
    )

    partial = ESimPurchaseResponse.from_payload(
        load_fixture("purchase_esims_202_partial.json")
    )
    _report(
        f"202 partial parsed: {len(partial.sim_cards)} eSIM(s), "
        f"errors={[e.code for e in partial.errors]} "
        f"(capacity={[e.is_capacity for e in partial.errors]})"
    )
    _report("")

    _report(
        f"GET {API_BASE_URL}{LIST_SIM_CARDS_PATH}"
        f"?filter[tags][]={request.correlation_tag}"
    )
    for label, cards, trusted in (
        ("all requested eSIMs found", accepted.sim_cards, False),
        ("no eSIM found, lookup NOT trusted", (), False),
        ("no eSIM found, lookup trusted", (), True),
        ("one of two found", accepted.sim_cards[:1], False),
        (
            "three found for a request of two",
            accepted.sim_cards + accepted.sim_cards[:1],
            False,
        ),
    ):
        decision = reconcile_purchase(
            requested_amount=2,
            operation_reference=operation,
            sim_cards=cards,
            lookup_is_trusted=trusted,
        )
        _report(
            f"  {label}: {decision.outcome.value} "
            f"(retry={decision.may_retry_purchase}, "
            f"manual={decision.requires_manual_review})"
        )
        _report(f"      {decision.reason}")
    _report("")
    _report(SIMULATION_BANNER)
    return 0


def run_live_mode(args: argparse.Namespace) -> int:
    if not args.i_have_authorization:
        sys.stderr.write(
            "Refusing to run live: pass --i-have-authorization to confirm that "
            "an authorized Telnyx account, an agreed test scope and a spending "
            "limit exist. D1 is OPEN; this flag is not a substitute for it.\n"
        )
        return 2

    api_key = os.environ.get("TELNYX_API_KEY")
    if not api_key:
        sys.stderr.write(
            "Refusing to run live: TELNYX_API_KEY is not set. No credential is "
            "committed to this repository and none may be.\n"
        )
        return 2

    if not args.tag:
        sys.stderr.write(
            "Refusing to run live: --tag is required. This mode only performs a "
            "read-only lookup of SIM cards carrying a specific operation tag.\n"
        )
        return 2

    try:
        tag_uuid = UUID(args.tag.removeprefix("damdam-op-"))
    except (AttributeError, ValueError):
        tag_uuid = None
    if tag_uuid is None or args.tag != f"damdam-op-{tag_uuid}":
        sys.stderr.write(
            "Refusing to run live: --tag must be one exact DamDam operation tag "
            "in the form damdam-op-<uuid>.\n"
        )
        return 2

    if not math.isfinite(args.timeout) or args.timeout <= 0:
        sys.stderr.write("Refusing to run live: --timeout must be a positive number.\n")
        return 2

    try:
        import httpx
    except ImportError:  # pragma: no cover -- exercised only outside the venv
        sys.stderr.write("httpx is required for live mode.\n")
        return 2

    url = f"{API_BASE_URL}{LIST_SIM_CARDS_PATH}"
    sys.stdout.write(f"OBSERVED -- live read-only GET {url}\n")
    try:
        response = httpx.get(
            url,
            params={"filter[tags][]": args.tag, "page[size]": 250},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=args.timeout,
        )
    except httpx.RequestError:
        # Do not print the exception: proxy URLs and supplier errors can contain
        # account-specific data, and this output is intended to be shareable.
        sys.stderr.write("Live read-only request failed; details withheld.\n")
        return 1
    sys.stdout.write(f"HTTP {response.status_code}\n")
    if response.status_code != 200:
        # Deliberately not echoing the body: an error body can carry account
        # identifiers, and this output is intended to be pasteable evidence.
        sys.stderr.write("Non-200 response; body withheld from output.\n")
        return 1

    try:
        payload = response.json()
        if not isinstance(payload, dict):
            raise ContractViolation("list response must be an object")
        raw_cards = payload.get("data") or []
        if not isinstance(raw_cards, list):
            raise ContractViolation("list response 'data' must be an array")
        cards = tuple(SimCard.from_payload(item) for item in raw_cards)
    except (ContractViolation, ValueError):
        sys.stderr.write(
            "Live response did not match the documented contract; body withheld.\n"
        )
        return 1
    sys.stdout.write(f"{len(cards)} SIM card(s) carry that tag.\n")
    for card in cards:
        # Report only non-identifying fields. SIM IDs and even partial ICCIDs
        # identify account resources and do not belong in pasteable evidence.
        sys.stdout.write(
            f"  status={card.status.value} type={card.type} "
            f"voice_enabled={card.voice_enabled}\n"
        )
    sys.stdout.write(
        "This is a read-only observation. It does not establish coverage, "
        "pricing, VoLTE production support or device behaviour.\n"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="telnyx_probe",
        description=(
            "Non-production contract probe for documented Telnyx Wireless "
            "endpoints. Never purchases, enables, disables or deletes anything."
        ),
    )
    parser.add_argument("--mode", choices=("fixtures", "live"), default="fixtures")
    parser.add_argument(
        "--i-have-authorization",
        action="store_true",
        help="Confirm an authorized account, agreed test scope and spending limit.",
    )
    parser.add_argument("--tag", help="Operation tag to look up in live mode.")
    parser.add_argument("--timeout", type=float, default=15.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "fixtures":
        return run_fixture_mode()
    return run_live_mode(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
