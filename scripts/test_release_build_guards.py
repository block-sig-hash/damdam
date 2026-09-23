"""Exercise the committed iOS build-phase mock/harness refusal on Linux."""

from __future__ import annotations

import ast
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1] / "apps/mobile/ios/DamDam.xcodeproj/project.pbxproj"
IOS = PROJECT.parents[1]
CI = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
PROMOTION = Path(__file__).resolve().parents[1] / ".github/workflows/release-promotion.yml"


class IOSReleaseGuardTests(unittest.TestCase):
    def test_ios_fixture_ci_uses_nonrelease_bundled_build(self) -> None:
        workflow = CI.read_text()
        ios_job = workflow.split("  screenshot-mobile-ios:", 1)[1]
        self.assertIn("-configuration Debug", ios_job)
        self.assertIn('FORCE_BUNDLING: "true"', ios_job)
        self.assertIn("Debug-iphonesimulator/DamDam.app", ios_job)
        self.assertIn('xcrun simctl bootstatus "$DEVICE_ID" -b', ios_job)
        self.assertNotIn("Release-iphonesimulator/DamDam.app", ios_job)

    def test_release_bundle_rejects_fixture_harness(self) -> None:
        project = PROJECT.read_text()
        phase = re.search(r"/\* Bundle React Native code and images \*/ = \{([\s\S]*?)\n\t\t\};", project)
        self.assertIsNotNone(phase)
        raw_script = re.search(r'shellScript = ("(?:\\.|[^"\\])*");', phase.group(1))
        self.assertIsNotNone(raw_script)
        script = ast.literal_eval(raw_script.group(1))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            xcode_scripts = root / "scripts" / "xcode"
            xcode_scripts.mkdir(parents=True)
            with_environment = xcode_scripts / "with-environment.sh"
            with_environment.write_text(
                "#!/bin/sh\nset -eu\n"
                '. "$PODFILE_DIR/.xcode.env.local"\n'
                'exec "$1"\n'
            )
            with_environment.chmod(0o755)
            rn_bundle = root / "scripts" / "react-native-xcode.sh"
            rn_bundle.write_text("#!/bin/sh\nexit 0\n")
            rn_bundle.chmod(0o755)
            local_env = root / ".xcode.env.local"
            environment = os.environ.copy()
            environment["REACT_NATIVE_PATH"] = directory
            environment["PODFILE_DIR"] = directory
            environment["PROJECT_DIR"] = str(IOS)
            environment["CONFIGURATION"] = "Release"
            environment["SCREENSHOT_HARNESS_MODE"] = "true"
            local_env.write_text("export SCREENSHOT_HARNESS_MODE=false\n")
            blocked = subprocess.run(["/bin/sh", "-c", script], env=environment, capture_output=True, text=True)
            self.assertEqual(blocked.returncode, 0, blocked.stderr)

            environment["SCREENSHOT_HARNESS_MODE"] = "false"
            local_env.write_text("export SCREENSHOT_HARNESS_MODE=true\n")
            blocked_from_local = subprocess.run(["/bin/sh", "-c", script], env=environment, capture_output=True, text=True)
            self.assertNotEqual(blocked_from_local.returncode, 0)
            self.assertIn("forbidden in an iOS Release build", blocked_from_local.stderr)

            local_env.write_text("export SCREENSHOT_HARNESS_MODE=false\n")
            accepted = subprocess.run(["/bin/sh", "-c", script], env=environment, capture_output=True, text=True)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            environment["CONFIGURATION"] = "Debug"
            environment["SCREENSHOT_HARNESS_MODE"] = "true"
            local_env.write_text("export SCREENSHOT_HARNESS_MODE=true\n")
            screenshot = subprocess.run(["/bin/sh", "-c", script], env=environment, capture_output=True, text=True)
            self.assertEqual(screenshot.returncode, 0, screenshot.stderr)


class PromotionWorkflowTests(unittest.TestCase):
    def test_trusted_status_uses_dedicated_app_and_protected_environment(self) -> None:
        workflow = PROMOTION.read_text()
        self.assertNotRegex(workflow, r"(?m)^\s+statuses: write$")
        self.assertNotIn("GH_TOKEN: ${{ github.token }}", workflow)
        self.assertEqual(workflow.count("environment: release-signoff"), 2)
        self.assertEqual(workflow.count("uses: actions/create-github-app-token@v3"), 2)
        self.assertEqual(workflow.count("permission-statuses: write"), 2)
        self.assertEqual(workflow.count("GH_TOKEN: ${{ steps.app-token.outputs.token }}"), 2)


if __name__ == "__main__":
    unittest.main()
