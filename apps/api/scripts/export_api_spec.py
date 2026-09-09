"""Regenerate docs/api-spec.yaml from the live FastAPI application.

CI fails on any drift between the implementation and the committed contract
(scripts/check_api_spec_drift.py), so a route change must be followed by a run
of this script. The dump settings reproduce the committed file byte for byte,
which keeps the review diff limited to the endpoints that actually changed.
"""

from pathlib import Path

import yaml

from app.main import app

ROOT = Path(__file__).resolve().parents[3]
COMMITTED_SPEC = ROOT / "docs" / "api-spec.yaml"


def main() -> None:
    COMMITTED_SPEC.write_text(yaml.safe_dump(app.openapi(), sort_keys=False))
    print(f"wrote {COMMITTED_SPEC}")


if __name__ == "__main__":
    main()
