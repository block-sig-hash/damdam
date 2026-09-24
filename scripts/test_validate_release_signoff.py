"""Release-gate regressions against a real disposable git history."""

from __future__ import annotations

import base64
import hashlib
import os
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

import validate_release_signoff as gate


TODAY = date(2026, 9, 23)


def evidence(label: str) -> str:
    """An opaque fixture locator, never a claim about a real external artifact."""
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def owner(label: str) -> str:
    """A synthetic restricted-roster identity reference, not a real person."""
    return "owner:" + hashlib.sha256(label.encode()).hexdigest()[:32]


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
        for name in (*gate.REQUIRED_EXTERNAL_REFERENCES, *gate.EXACT_HEAD_FIELDS,
                     "Blocking review findings status"):
            self.assertEqual(template.count(f"- **{name}:**"), 1, name)

    def setUp(self) -> None:
        self.old_cwd = Path.cwd()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.chdir(self.root)
        self.run_git("init", "-b", "main")
        self.run_git("config", "user.email", "release-test@example.invalid")
        self.run_git("config", "user.name", "Release Test")
        (self.root / "app.txt").write_text("baseline\n")
        migration = self.root / "apps/api/migrations/versions/0044_operator_actions.py"
        migration.parent.mkdir(parents=True)
        migration.write_text('revision: str = "0044_operator_actions"\ndown_revision = None\n')
        self.run_git("add", "app.txt", str(migration.relative_to(self.root)))
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
            "Tester identity": owner("release-tester"),
            "Date": TODAY.isoformat(),
            "Environment": "production",
            "Runtime configuration SHA-256": "a" * 64,
            "Carrier configuration reference": "disabled",
            "Merchant configuration reference": evidence("approved-merchant-001"),
            "Schema revision": "0044_operator_actions @ " + evidence("migration-report-123"),
            "Accepted dependency commits": self.base,
            "Release markets": evidence("approved-market-record-001"),
            "Release manifest reference": evidence("manifest-001"),
            "Mock supplier mode": "disabled",
            "Signed Android build evidence": evidence("android-signed-001"),
            "Signed iOS build evidence": evidence("ios-signed-001"),
            "EAS build source SHA": self.candidate,
            "Android EAS signed artifact evidence": evidence("eas-android-001"),
            "iOS EAS signed artifact evidence": evidence("eas-ios-001"),
            "Native CI source SHA": self.candidate,
            "Native simulator/emulator CI evidence": evidence("native-ci-001"),
            "TestFlight physical installation evidence": evidence("testflight-install-001"),
            "Android internal physical installation evidence": evidence("android-internal-install-001"),
            "Evidence configuration compatibility reference": evidence("compatibility-review-001"),
            "Blocking review findings status": "CLEAR",
            "Blocking review findings evidence": evidence("closed-findings-001"),
            "Pilot limits approval evidence": evidence("approved-limits-001"),
            "Incident and support ownership evidence": evidence("incident-owner-001"),
            "Refund and finance ownership evidence": evidence("refund-owner-001"),
            "Rollback rehearsal and owner evidence": evidence("rollback-owner-001"),
            "Store privacy and payment disclosure evidence": evidence("store-review-001"),
            "Incident owner": owner("incident-commander"),
            "Support owner": owner("support-lead"),
            "Refund and finance owner": owner("finance-lead"),
            "Rollback owner": owner("rollback-operator"),
        }
        lines = [f"- **{name}:** {value}" for name, value in fields.items()]
        lines += [
            "", "## Released channels", "",
            "| Channel | Status | Decision evidence | Eligibility/denial result |",
            "|---|---|---|---|",
            f"| Carrier eSIM | DISABLED | {evidence('carrier-denial-001')} | PASS |",
            f"| Mobile internet | ENABLED | {evidence('mobile-approval-001')} | PASS |",
            f"| Browser internet | DISABLED | {evidence('browser-denial-001')} | PASS |",
            "", "## Device matrix tested", "",
            "| Platform | Model | OS version | Visited network | Evidence |",
            "|---|---|---|---|---|",
            f"| Android | Pixel 9 | 16 | Operator A | {evidence('physical-android-001')} |",
            f"| iOS | iPhone 16 | 19 | Operator B | {evidence('physical-ios-001')} |",
            "", "## Critical scenario results", "",
            "| Scenario | Result | Evidence |", "|---|---|---|",
        ]
        required = set(gate.COMMON) | set(gate.CONDITIONAL["Mobile internet"])
        for scenario in (*gate.COMMON, *sum(gate.CONDITIONAL.values(), ())):
            result = "PASS" if scenario in required else "NOT_APPLICABLE"
            lines.append(f"| {scenario} | {result} | {evidence(scenario)} |")
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
        head = self.promote(
            self.body().replace(evidence("physical-ios-001"), evidence("fabricated-record")),
            signed_body=self.body(),
        )
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
        self.assert_blocked(self.body().replace(evidence("approved-merchant-001"), "<merchant approval>"), "Merchant configuration")

    def test_explicitly_unapproved_merchant_blocks(self) -> None:
        self.assert_blocked(
            self.body().replace(evidence("approved-merchant-001"), "not approved — no merchant account"),
            "Merchant configuration",
        )

    def test_denied_merchant_approval_blocks(self) -> None:
        self.assert_blocked(
            self.body().replace(evidence("approved-merchant-001"), "merchant approval denied"),
            "Merchant configuration",
        )

    def test_unresolved_review_evidence_blocks(self) -> None:
        self.assert_blocked(
            self.body().replace(evidence("closed-findings-001"), "blocking findings unresolved"),
            "Blocking review findings evidence",
        )

    def test_unapplied_schema_reference_blocks(self) -> None:
        self.assert_blocked(
            self.body().replace("0044_operator_actions @ " + evidence("migration-report-123"),
                                "0044 — no applied migration report"),
            "Schema revision",
        )

    def test_schema_revision_must_match_tested_source_head(self) -> None:
        self.assert_blocked(
            self.body().replace("0044_operator_actions @", "0001_us01_auth @"),
            "Schema revision does not match tested source migration head",
        )

    def test_new_tested_migration_changes_required_schema_revision(self) -> None:
        migration = self.root / "apps/api/migrations/versions/0045_next.py"
        migration.write_text(
            'revision: str = "0045_next"\n'
            'down_revision: str | None = "0044_operator_actions"\n'
        )
        self.run_git("add", str(migration.relative_to(self.root)))
        self.run_git("commit", "-m", "new source migration")
        self.candidate = self.run_git("rev-parse", "HEAD")
        self.run_git("update-ref", "refs/remotes/origin/staging", self.candidate)
        self.assert_blocked(self.body(), "Schema revision does not match tested source migration head")

    def test_disconnected_migration_cycle_blocks(self) -> None:
        versions = self.root / "apps/api/migrations/versions"
        for revision, parent in (("cycle_a", "cycle_b"), ("cycle_b", "cycle_a")):
            (versions / f"{revision}.py").write_text(
                f'revision = "{revision}"\ndown_revision = "{parent}"\n'
            )
            self.run_git("add", str((versions / f"{revision}.py").relative_to(self.root)))
        self.run_git("commit", "-m", "invalid migration cycle")
        self.candidate = self.run_git("rev-parse", "HEAD")
        self.run_git("update-ref", "refs/remotes/origin/staging", self.candidate)
        self.assert_blocked(self.body(), "disconnected revisions")

    def test_rollback_owner_needs_rehearsal_reference(self) -> None:
        self.assert_blocked(
            self.body().replace(evidence("rollback-owner-001"), "Alice was assigned"),
            "Rollback rehearsal and owner evidence",
        )

    def test_generic_owner_label_is_not_an_identity(self) -> None:
        self.assert_blocked(
            self.body().replace(owner("incident-commander"), "On-call owner"),
            "Incident owner",
        )

    def test_generic_tester_label_is_not_an_identity(self) -> None:
        self.assert_blocked(
            self.body().replace(owner("release-tester"), "Release owner"),
            "Tester identity",
        )

    def test_missing_required_scenario_proof_blocks_even_if_pass(self) -> None:
        self.assert_blocked(
            self.body().replace(
                f"| Purchase, payment and refund | PASS | {evidence('Purchase, payment and refund')} |",
                "| Purchase, payment and refund | PASS | no payment evidence |",
            ),
            "Purchase, payment and refund evidence",
        )

    def test_untested_rollback_cannot_be_marked_pass(self) -> None:
        self.assert_blocked(
            self.body().replace(
                f"| Migration and rollback | PASS | {evidence('Migration and rollback')} |",
                "| Migration and rollback | PASS | rollback untested |",
            ),
            "Migration and rollback evidence",
        )

    def test_missing_channel_decision_proof_blocks(self) -> None:
        self.assert_blocked(
            self.body().replace(evidence("mobile-approval-001"), "no approval"),
            "Mobile internet decision evidence",
        )

    def test_missing_physical_install_proof_blocks(self) -> None:
        self.assert_blocked(
            self.body().replace(evidence("physical-ios-001"), "no installation"),
            "iOS physical-device evidence",
        )

    def test_enabled_carrier_without_configuration_blocks(self) -> None:
        body = self.body().replace(
            "| Carrier eSIM | DISABLED |", "| Carrier eSIM | ENABLED |"
        )
        self.assert_blocked(body, "Carrier configuration reference")

    def test_disabled_carrier_cannot_claim_unverified_configuration(self) -> None:
        self.assert_blocked(
            self.body().replace("Carrier configuration reference:** disabled",
                                "Carrier configuration reference:** unverified"),
            "Disabled carrier configuration",
        )

    def test_missing_physical_device_blocks(self) -> None:
        self.assert_blocked(self.body().replace(evidence("physical-ios-001"), "<device evidence>"), "physical-device")

    def test_missing_eas_artifact_blocks(self) -> None:
        self.assert_blocked(self.body().replace(evidence("eas-ios-001"), "disabled"), "EAS signed artifact")

    def test_empty_reference_cannot_consume_next_field(self) -> None:
        self.assert_blocked(
            self.body().replace("- **iOS EAS signed artifact evidence:** " + evidence("eas-ios-001"),
                                "- **iOS EAS signed artifact evidence:**"),
            "iOS EAS signed artifact evidence",
        )

    def test_blocked_eas_artifact_blocks(self) -> None:
        self.assert_blocked(
            self.body().replace(evidence("eas-ios-001"), "BLOCKED — no approved signing identity"),
            "EAS signed artifact",
        )

    def test_negative_evidence_prose_cannot_pass(self) -> None:
        for value in (
            "Not available: no approved signing identity",
            "disabled — no EAS build",
            "NONE (no build)",
            "Unavailable",
            "OPEN — awaiting artifact",
            "No artifact was produced",
            "not yet approved",
        ):
            with self.subTest(value=value):
                gate.artifact_field(
                    self.body().replace(evidence("eas-ios-001"), value),
                    "Android EAS signed artifact evidence",
                )
                with self.assertRaisesRegex(gate.SignoffError, "iOS EAS signed artifact evidence"):
                    gate.artifact_field(
                        self.body().replace(evidence("eas-ios-001"), value),
                        "iOS EAS signed artifact evidence",
                    )

    def test_artifact_reference_cannot_append_denial_to_digest(self) -> None:
        self.assert_blocked(
            self.body().replace(evidence("eas-ios-001"), evidence("eas-ios-001") + " — approval denied"),
            "iOS EAS signed artifact evidence",
        )

    def test_eas_build_from_other_commit_blocks(self) -> None:
        body = self.body().replace(
            f"EAS build source SHA:** {self.candidate}",
            f"EAS build source SHA:** {self.base}",
        )
        self.assert_blocked(body, "EAS build source SHA")

    def test_native_ci_from_other_commit_blocks(self) -> None:
        body = self.body().replace(
            f"Native CI source SHA:** {self.candidate}",
            f"Native CI source SHA:** {self.base}",
        )
        self.assert_blocked(body, "Native CI source SHA")

    def test_missing_internal_install_blocks(self) -> None:
        self.assert_blocked(
            self.body().replace(evidence("android-internal-install-001"), "disabled"),
            "internal physical installation",
        )

    def test_open_blocking_review_finding_blocks(self) -> None:
        self.assert_blocked(
            self.body().replace("Blocking review findings status:** CLEAR", "Blocking review findings status:** OPEN"),
            "Blocking review findings",
        )

    def test_missing_pilot_limits_approval_blocks(self) -> None:
        self.assert_blocked(self.body().replace(evidence("approved-limits-001"), "disabled"), "Pilot limits approval")

    def test_missing_compatibility_assessment_blocks(self) -> None:
        self.assert_blocked(
            self.body().replace(evidence("compatibility-review-001"), "disabled"),
            "Evidence configuration compatibility",
        )

    def test_required_scenario_cannot_be_skipped(self) -> None:
        body = self.body().replace(
            "| Mobile outbound call, identity and DTMF | PASS |",
            "| Mobile outbound call, identity and DTMF | NOT_APPLICABLE |",
        )
        self.assert_blocked(body, "Required scenario")

    def test_missing_scenario_blocks(self) -> None:
        body = self.body().replace(f"| Migration and rollback | PASS | {evidence('Migration and rollback')} |\n", "")
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
