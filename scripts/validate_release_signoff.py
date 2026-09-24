#!/usr/bin/env python3
"""Fail-closed staging-to-main signoff validation (US-42, chunk 27).

The artifact is read from the PR commit, not the working tree. CI verifies
tracked code/config ancestry and evidence structure; external evidence still
needs a human release owner and cannot be manufactured by this script.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

SIGNOFF_DIR = "docs/release-signoffs/"
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
CHANNELS = ("Carrier eSIM", "Mobile internet", "Browser internet")
COMMON = (
    "Identity and recovery",
    "Purchase, payment and refund",
    "Enterprise isolation and offboarding",
    "Supplier timeout, replay and recovery",
    "Migration and rollback",
    "Support and incident escalation",
    "Signed Android and iOS installation",
    "Store privacy and payment disclosures",
    "Production mock-mode rejection",
)
CONDITIONAL = {
    "Carrier eSIM": (
        "Carrier eSIM install and data",
        "Native call to Nigeria with app closed",
        "Carrier usage, top-up and limit",
    ),
    "Mobile internet": (
        "Mobile outbound call, identity and DTMF",
        "Mobile interruption, logout and cutoff",
    ),
    "Browser internet": (
        "Browser outbound call, identity and DTMF",
        "Browser refresh, logout and cutoff",
    ),
}
REQUIRED_EXTERNAL_REFERENCES = (
    "Android EAS signed artifact evidence",
    "iOS EAS signed artifact evidence",
    "Native simulator/emulator CI evidence",
    "TestFlight physical installation evidence",
    "Android internal physical installation evidence",
    "Evidence configuration compatibility reference",
    "Blocking review findings evidence",
    "Pilot limits approval evidence",
)
EXACT_HEAD_FIELDS = ("EAS build source SHA", "Native CI source SHA")
NEGATIVE_EVIDENCE = re.compile(
    r"\b(?:BLOCKED|DISABLED|NONE|UNAVAILABLE|MISSING|ABSENT|OPEN|"
    r"FAIL(?:ED)?|UNVERIFIED|INVALID|NO|NOT|WITHOUT|AWAITING)\b",
    re.I,
)


class SignoffError(Exception):
    """A release-blocking error suitable for a GitHub annotation."""


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    if result.returncode:
        raise SignoffError(f"git {' '.join(args[:2])} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def git_ok(*args: str) -> bool:
    return subprocess.run(["git", *args], capture_output=True).returncode == 0


def git_blob(revision: str, path: str) -> bytes:
    result = subprocess.run(["git", "show", f"{revision}:{path}"], capture_output=True)
    if result.returncode:
        raise SignoffError(f"Cannot read committed signoff object: {path}")
    return result.stdout


def verify_release_owner_signature(body: bytes, signature_b64: bytes) -> None:
    """Verify exact committed bytes against an out-of-repository release key."""
    public_key_b64 = os.environ.get("DAMDAM_RELEASE_PUBLIC_KEY_B64", "")
    if not public_key_b64:
        raise SignoffError("Trusted release-owner public key is not configured")
    try:
        public_key = base64.b64decode(public_key_b64, validate=True)
        signature = base64.b64decode(signature_b64.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignoffError("Invalid release-owner key or signature encoding") from exc
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        key_path, body_path, sig_path = (root / name for name in ("key.pem", "body.md", "signature.bin"))
        key_path.write_bytes(public_key)
        body_path.write_bytes(body)
        sig_path.write_bytes(signature)
        result = subprocess.run(
            ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(key_path),
             "-rawin", "-in", str(body_path), "-sigfile", str(sig_path)],
            capture_output=True,
        )
        if result.returncode:
            raise SignoffError("Release-owner signature verification failed")


def paths(*args: str) -> list[str]:
    output = subprocess.run(["git", *args], capture_output=True, check=True).stdout
    return [p.decode("utf-8") for p in output.split(b"\0") if p]


def field(body: str, name: str) -> str:
    matches = re.findall(
        rf"^- \*\*{re.escape(name)}:\*\*[ \t]*(.*?)[ \t]*$", body, re.MULTILINE
    )
    if len(matches) != 1:
        raise SignoffError(f"Expected exactly one '{name}' field")
    value = matches[0].strip()
    substantive(value, name)
    return value


def substantive(value: str, description: str) -> None:
    if not value or re.search(r"<[^>]+>|\b(TODO|TBD|PENDING|UNKNOWN|N/A)\b", value, re.I):
        raise SignoffError(f"Missing or placeholder {description}")


def mandatory_reference(body: str, name: str) -> str:
    value = field(body, name)
    if NEGATIVE_EVIDENCE.search(value):
        raise SignoffError(f"Missing mandatory {name}")
    return value


def table(body: str, heading: str) -> dict[str, list[str]]:
    sections = list(re.finditer(
        rf"^## {re.escape(heading)}\s*$([\s\S]*?)(?=^## |\Z)",
        body, re.MULTILINE,
    ))
    if len(sections) != 1:
        raise SignoffError(f"Expected exactly one '{heading}' section")
    rows: dict[str, list[str]] = {}
    for raw_line in sections[0].group(1).splitlines():
        # Up to three leading spaces are valid Markdown table indentation.
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.lstrip(" ") if indent <= 3 else raw_line
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or not cells[0] or cells[0].lower() in {"channel", "platform", "scenario"} or set(cells[0]) <= {"-", ":"}:
            continue
        if cells[0] in rows:
            raise SignoffError(f"Duplicate '{cells[0]}' row in {heading}")
        rows[cells[0]] = cells[1:]
    return rows


def validate_body(body: str, tested: str, today: date) -> None:
    # A second, misleading table elsewhere must not hide an observed failure.
    if re.search(r"^\s*\|[^|\n]+\|\s*FAIL\s*\|", body, re.MULTILINE):
        raise SignoffError("Explicit FAIL result in signoff")
    if field(body, "Commit SHA").lower() != tested:
        raise SignoffError("Commit SHA does not match signoff filename")
    for name in (
        "Tester name", "Environment", "Carrier configuration reference",
        "Merchant configuration reference", "Schema revision", "Incident owner",
        "Rollback owner", "Release markets", "Release manifest reference",
        "Signed Android build evidence", "Signed iOS build evidence",
        "Store privacy and payment disclosure evidence",
    ):
        field(body, name)
    for name in REQUIRED_EXTERNAL_REFERENCES:
        mandatory_reference(body, name)
    for name in EXACT_HEAD_FIELDS:
        if field(body, name).lower() != tested:
            raise SignoffError(f"{name} must match tested commit")
    if field(body, "Blocking review findings status") != "CLEAR":
        raise SignoffError("Blocking review findings must be CLEAR")
    if field(body, "Environment") != "production":
        raise SignoffError("Release environment must be production")
    if not DIGEST.fullmatch(field(body, "Runtime configuration SHA-256").lower()):
        raise SignoffError("Runtime configuration SHA-256 must be 64 hex digits")
    if field(body, "Mock supplier mode").lower() != "disabled":
        raise SignoffError("Mock supplier mode must be disabled")
    raw_date = field(body, "Date")
    try:
        signed = date.fromisoformat(raw_date)
    except ValueError as exc:
        raise SignoffError("Date must be valid YYYY-MM-DD") from exc
    if signed.isoformat() != raw_date or signed > today:
        raise SignoffError("Signoff date is invalid or future-dated")
    if (today - signed).days > 7:
        raise SignoffError("Signoff is older than seven days")

    dependencies = [item.strip() for item in field(body, "Accepted dependency commits").split(",")]
    if not dependencies or any(not SHA.fullmatch(item) for item in dependencies):
        raise SignoffError("Accepted dependency commits must be full comma-separated SHAs")
    for dependency in dependencies:
        if not git_ok("cat-file", "-e", f"{dependency}^{{commit}}") or not git_ok("merge-base", "--is-ancestor", dependency, tested):
            raise SignoffError(f"Dependency commit {dependency} is not in tested history")

    channels = table(body, "Released channels")
    if set(channels) != set(CHANNELS):
        raise SignoffError("All three release channels must be declared")
    enabled: set[str] = set()
    for name in CHANNELS:
        values = channels[name]
        if len(values) != 3 or values[0] not in {"ENABLED", "DISABLED"}:
            raise SignoffError(f"{name} needs a status, decision evidence and eligibility result")
        substantive(values[1], f"{name} decision evidence")
        if values[2] != "PASS":
            raise SignoffError(f"{name} eligibility or denial result must PASS")
        if values[0] == "ENABLED":
            enabled.add(name)
    if not enabled:
        raise SignoffError("At least one release channel must be enabled")
    if "Carrier eSIM" in enabled and field(body, "Carrier configuration reference").lower() == "disabled":
        raise SignoffError("Carrier configuration evidence is required")
    if field(body, "Merchant configuration reference").lower() == "disabled":
        raise SignoffError("Merchant configuration evidence is required")

    devices = table(body, "Device matrix tested")
    if set(devices) != {"Android", "iOS"}:
        raise SignoffError("Physical Android and iOS device rows are required")
    for platform, values in devices.items():
        if len(values) != 4:
            raise SignoffError(f"{platform} needs model, OS, network and evidence")
        for value in values:
            substantive(value, f"{platform} physical-device evidence")

    scenarios = table(body, "Critical scenario results")
    all_scenarios = set(COMMON).union(*CONDITIONAL.values())
    if set(scenarios) != all_scenarios:
        raise SignoffError("Scenario matrix must contain every defined row exactly once")
    required = set(COMMON)
    for name in enabled:
        required.update(CONDITIONAL[name])
    for name, values in scenarios.items():
        if len(values) != 2 or values[0] not in {"PASS", "FAIL", "NOT_APPLICABLE"}:
            raise SignoffError(f"{name} needs a valid result and evidence")
        if values[0] == "FAIL":
            raise SignoffError(f"Explicit FAIL result: {name}")
        if name in required:
            if values[0] != "PASS":
                raise SignoffError(f"Required scenario must PASS: {name}")
            substantive(values[1], f"{name} evidence")
        elif values[0] != "NOT_APPLICABLE":
            raise SignoffError(f"Disabled-channel scenario must be NOT_APPLICABLE: {name}")


def validate(head: str, today: date | None = None) -> str:
    if not SHA.fullmatch(head) or not git_ok("cat-file", "-e", f"{head}^{{commit}}"):
        raise SignoffError("PR head must be a resolvable full commit SHA")
    if not git_ok("cat-file", "-e", "origin/main^{commit}"):
        raise SignoffError("origin/main is missing; fetch full history")
    if not git_ok("cat-file", "-e", "origin/staging^{commit}"):
        raise SignoffError("origin/staging is missing; fetch full history")
    base = git("merge-base", "origin/main", head)
    added = paths("diff", "--name-only", "-z", "--diff-filter=A", base, head, "--", SIGNOFF_DIR)
    added = [p for p in added if p not in {f"{SIGNOFF_DIR}TEMPLATE.md", f"{SIGNOFF_DIR}README.md"}]
    signoffs = [p for p in added if p.endswith(".md")]
    if len(signoffs) != 1:
        raise SignoffError("Promotion must add exactly one signoff artifact")
    path = signoffs[0]
    signature_path = f"{path}.sig"
    if set(added) != {path, signature_path}:
        raise SignoffError("Promotion must add only a signoff and matching signature")
    if Path(path).parent.as_posix() != SIGNOFF_DIR.rstrip("/") or not path.endswith(".md"):
        raise SignoffError("Signoff must be a direct .md file in docs/release-signoffs")
    tested = Path(path).stem
    if not SHA.fullmatch(tested) or not git_ok("cat-file", "-e", f"{tested}^{{commit}}"):
        raise SignoffError("Signoff filename must be a resolvable full commit SHA")
    if not git_ok("merge-base", "--is-ancestor", tested, head) or not git_ok("merge-base", "--is-ancestor", base, tested):
        raise SignoffError("Tested commit is outside this promotion ancestry")
    if tested != git("rev-parse", "origin/staging"):
        raise SignoffError("Tested commit must equal the current staging branch head")
    changed_after_test = [p for p in paths("diff", "--name-only", "-z", tested, head, "--") if p not in {path, signature_path}]
    if changed_after_test:
        raise SignoffError("Tracked code/config changed after tested commit: " + ", ".join(changed_after_test[:5]))
    body_bytes = git_blob(head, path)
    verify_release_owner_signature(body_bytes, git_blob(head, signature_path))
    try:
        body = body_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SignoffError("Signoff must be UTF-8") from exc
    validate_body(body, tested, today or datetime.now(timezone.utc).date())
    return f"Release signoff valid for tested commit {tested}"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate-release-signoff.sh <pr-head-sha>", file=sys.stderr)
        return 2
    try:
        print(validate(sys.argv[1]))
    except (SignoffError, subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
