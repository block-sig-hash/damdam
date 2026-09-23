"""Release-gate regressions against a real disposable git history."""

from __future__ import annotations

import base64
import os
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

import validate_release_signoff as gate


TODAY = date(2026, 9, 23)


class ReleaseSignoffTests(unittest.TestCase):
    def test_template_and_validator_matrix_stay_in_sync(self) -> None:
        template = (
            Path(__file__).resolve().parents[1]
            / "docs" / "release-signoffs" / "TEMPLATE.md"
        ).read_text()
        self.assertEqual(set(gate.table(template, "Released channels")), set(gate.CHANNELS))
        self.assertEqual(
            set(gate.table(template, "Critical scenario results")),
            set(gate.COMMON).union(*gate.CONDITIONAL.values()),
        )

    def setUp(self) -> None:
        self.old_cwd = Path.cwd()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.chdir(self.root)
        self.run_git("init", "-b", "main")
        self.run_git("config", "user.email", "release-test@example.invalid")
        self.run_git("config", "user.name", "Release Test")
        (self.root / "app.txt").write_text("baseline\n")
        self.run_git("add", "app.txt")
        self.run_git("commit", "-m", "baseline")
        self.base = self.run_git("rev-parse", "HEAD")
        self.run_git("update-ref", "refs/remotes/origin/main", self.base)
        self.run_git("switch", "-c", "staging")
        (self.root / "app.txt").write_text("candidate\n")
        self.run_git("commit", "-am", "candidate")
        self.candidate = self.run_git("rev-parse", "HEAD")
        self.run_git("update-ref", "refs/remotes/origin/staging", self.candidate)
        self.private_key = self.root / "release-owner-key.pem"
        self.public_key = self.root / "release-owner-public.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(self.private_key)], check=True, capture_output=True)
        subprocess.run(["openssl", "pkey", "-in", str(self.private_key), "-pubout", "-out", str(self.public_key)], check=True, capture_output=True)
        self.old_public_key = os.environ.get("DAMDAM_RELEASE_PUBLIC_KEY_B64")
        os.environ["DAMDAM_RELEASE_PUBLIC_KEY_B64"] = base64.b64encode(self.public_key.read_bytes()).decode()

    def tearDown(self) -> None:
        if self.old_public_key is None:
            os.environ.pop("DAMDAM_RELEASE_PUBLIC_KEY_B64", None)
        else:
            os.environ["DAMDAM_RELEASE_PUBLIC_KEY_B64"] = self.old_public_key
        os.chdir(self.old_cwd)
        self.temp.cleanup()

    def run_git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    def body(self) -> str:
        fields = {
            "Commit SHA": self.candidate,
            "Tester name": "Release owner",
            "Date": TODAY.isoformat(),
            "Environment": "production",
            "Runtime configuration SHA-256": "a" * 64,
            "Carrier configuration reference": "disabled",
            "Merchant configuration reference": "approved-merchant-001",
            "Schema revision": "0044 with migration report 123",
            "Accepted dependency commits": self.base,
            "Release markets": "approved-market-record-001",
            "Release manifest reference": "manifest-001",
            "Mock supplier mode": "disabled",
            "Signed Android build evidence": "android-signed-001",
            "Signed iOS build evidence": "ios-signed-001",
            "Store privacy and payment disclosure evidence": "store-review-001",
            "Incident owner": "On-call owner",
            "Rollback owner": "Rollback operator",
        }
        lines = [f"- **{name}:** {value}" for name, value in fields.items()]
        lines += [
            "", "## Released channels", "",
            "| Channel | Status | Decision evidence | Eligibility/denial result |",
            "|---|---|---|---|",
            "| Carrier eSIM | DISABLED | carrier-denial-001 | PASS |",
            "| Mobile internet | ENABLED | mobile-approval-001 | PASS |",
            "| Browser internet | DISABLED | browser-denial-001 | PASS |",
            "", "## Device matrix tested", "",
            "| Platform | Model | OS version | Visited network | Evidence |",
            "|---|---|---|---|---|",
            "| Android | Pixel 9 | 16 | Operator A | physical-android-001 |",
            "| iOS | iPhone 16 | 19 | Operator B | physical-ios-001 |",
            "", "## Critical scenario results", "",
            "| Scenario | Result | Evidence |", "|---|---|---|",
        ]
        required = set(gate.COMMON) | set(gate.CONDITIONAL["Mobile internet"])
        for scenario in (*gate.COMMON, *sum(gate.CONDITIONAL.values(), ())):
            result = "PASS" if scenario in required else "NOT_APPLICABLE"
            lines.append(f"| {scenario} | {result} | evidence-001 |")
        return "\n".join(lines) + "\n"

    def promote(self, body: str, change_after_test: bool = False, signed_body: str | None = None) -> str:
        signoff = self.root / "docs" / "release-signoffs" / f"{self.candidate}.md"
        signoff.parent.mkdir(parents=True)
        signoff.write_text(body)
        signed_input = self.root / "signed-input.md"
        signed_input.write_text(signed_body if signed_body is not None else body)
        raw_signature = self.root / "signature.bin"
        subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", str(self.private_key),
                        "-rawin", "-in", str(signed_input), "-out", str(raw_signature)], check=True, capture_output=True)
        signature = signoff.with_suffix(".md.sig")
        signature.write_bytes(base64.b64encode(raw_signature.read_bytes()) + b"\n")
        self.run_git("add", str(signoff.relative_to(self.root)), str(signature.relative_to(self.root)))
        if change_after_test:
            (self.root / "app.txt").write_text("untested runtime change\n")
            self.run_git("add", "app.txt")
        self.run_git("commit", "-m", "add release signoff")
        return self.run_git("rev-parse", "HEAD")

    def assert_blocked(self, body: str, message: str) -> None:
        head = self.promote(body)
        with self.assertRaisesRegex(gate.SignoffError, message):
            gate.validate(head, TODAY)

    def test_complete_signoff_passes(self) -> None:
        head = self.promote(self.body())
        self.assertIn(self.candidate, gate.validate(head, TODAY))

    def test_merge_queue_commit_revalidates_same_signoff(self) -> None:
        head = self.promote(self.body())
        self.run_git("switch", "main")
        self.run_git("merge", "--no-ff", head, "-m", "queue candidate")
        group_head = self.run_git("rev-parse", "HEAD")
        self.assertIn(self.candidate, gate.validate(group_head, TODAY))

    def test_untrusted_evidence_edit_blocks(self) -> None:
        head = self.promote(self.body().replace("physical-ios-001", "fabricated-record"), signed_body=self.body())
        with self.assertRaisesRegex(gate.SignoffError, "signature verification failed"):
            gate.validate(head, TODAY)

    def test_missing_trusted_key_blocks(self) -> None:
        head = self.promote(self.body())
        os.environ.pop("DAMDAM_RELEASE_PUBLIC_KEY_B64")
        with self.assertRaisesRegex(gate.SignoffError, "public key is not configured"):
            gate.validate(head, TODAY)

    def test_no_signoff_blocks(self) -> None:
        with self.assertRaisesRegex(gate.SignoffError, "exactly one signoff"):
            gate.validate(self.candidate, TODAY)

    def test_explicit_fail_blocks_even_on_disabled_channel(self) -> None:
        body = self.body().replace(
            "| Carrier eSIM install and data | NOT_APPLICABLE |",
            "| Carrier eSIM install and data | FAIL |",
        )
        self.assert_blocked(body, "Explicit FAIL")

    def test_duplicate_scenario_section_cannot_hide_fail(self) -> None:
        body = self.body() + "\n## Critical scenario results\n\n| Identity and recovery | FAIL | observed |\n"
        self.assert_blocked(body, "Explicit FAIL")

    def test_indented_fail_row_cannot_hide(self) -> None:
        body = self.body() + "\n   | Identity and recovery | FAIL | observed |\n"
        self.assert_blocked(body, "Explicit FAIL")

    def test_future_dated_signoff_blocks(self) -> None:
        self.assert_blocked(self.body().replace(TODAY.isoformat(), "2026-09-24"), "future-dated")

    def test_old_signoff_blocks(self) -> None:
        self.assert_blocked(self.body().replace(TODAY.isoformat(), "2026-09-01"), "older")

    def test_mock_mode_blocks(self) -> None:
        self.assert_blocked(self.body().replace("Mock supplier mode:** disabled", "Mock supplier mode:** enabled"), "Mock supplier")

    def test_missing_merchant_blocks(self) -> None:
        self.assert_blocked(self.body().replace("approved-merchant-001", "<merchant approval>"), "Merchant configuration")

    def test_enabled_carrier_without_configuration_blocks(self) -> None:
        body = self.body().replace(
            "| Carrier eSIM | DISABLED |", "| Carrier eSIM | ENABLED |"
        )
        self.assert_blocked(body, "Carrier configuration evidence")

    def test_missing_physical_device_blocks(self) -> None:
        self.assert_blocked(self.body().replace("physical-ios-001", "<device evidence>"), "physical-device")

    def test_required_scenario_cannot_be_skipped(self) -> None:
        body = self.body().replace(
            "| Mobile outbound call, identity and DTMF | PASS |",
            "| Mobile outbound call, identity and DTMF | NOT_APPLICABLE |",
        )
        self.assert_blocked(body, "Required scenario")

    def test_missing_scenario_blocks(self) -> None:
        body = self.body().replace("| Migration and rollback | PASS | evidence-001 |\n", "")
        self.assert_blocked(body, "Scenario matrix")

    def test_untested_runtime_change_blocks(self) -> None:
        head = self.promote(self.body(), change_after_test=True)
        with self.assertRaisesRegex(gate.SignoffError, "changed after tested commit"):
            gate.validate(head, TODAY)

    def test_candidate_not_current_staging_blocks(self) -> None:
        head = self.promote(self.body())
        self.run_git("update-ref", "refs/remotes/origin/staging", self.base)
        with self.assertRaisesRegex(gate.SignoffError, "current staging"):
            gate.validate(head, TODAY)

    def test_filename_and_internal_commit_must_match(self) -> None:
        self.assert_blocked(self.body().replace(
            f"Commit SHA:** {self.candidate}", f"Commit SHA:** {self.base}"
        ), "does not match")

    def test_unrelated_dependency_commit_blocks(self) -> None:
        self.assert_blocked(self.body().replace(
            f"Accepted dependency commits:** {self.base}",
            f"Accepted dependency commits:** {'f' * 40}",
        ), "Dependency commit")


if __name__ == "__main__":
    unittest.main()
