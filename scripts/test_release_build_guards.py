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
CI = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"


class IOSReleaseGuardTests(unittest.TestCase):
    def test_ios_fixture_ci_uses_nonrelease_bundled_build(self) -> None:
        workflow = CI.read_text()
        ios_job = workflow.split("  screenshot-mobile-ios:", 1)[1]
        self.assertIn("-configuration Debug", ios_job)
        self.assertIn('FORCE_BUNDLING: "true"', ios_job)
        self.assertIn("Debug-iphonesimulator/DamDam.app", ios_job)
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
            for filename in ("with-environment.sh", "react-native-xcode.sh"):
                stub = xcode_scripts / filename
                stub.write_text("#!/bin/sh\nexit 0\n")
                stub.chmod(0o755)
            environment = os.environ.copy()
            environment["REACT_NATIVE_PATH"] = directory
            environment["CONFIGURATION"] = "Release"
            environment["SCREENSHOT_HARNESS_MODE"] = "true"
            blocked = subprocess.run(["/bin/sh", "-c", script], env=environment, capture_output=True, text=True)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("forbidden in an iOS Release build", blocked.stderr)

            environment["SCREENSHOT_HARNESS_MODE"] = "false"
            accepted = subprocess.run(["/bin/sh", "-c", script], env=environment, capture_output=True, text=True)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            environment["CONFIGURATION"] = "Debug"
            environment["SCREENSHOT_HARNESS_MODE"] = "true"
            screenshot = subprocess.run(["/bin/sh", "-c", script], env=environment, capture_output=True, text=True)
            self.assertEqual(screenshot.returncode, 0, screenshot.stderr)


if __name__ == "__main__":
    unittest.main()
