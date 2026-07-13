import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
COMMITTED_SPEC = ROOT / "docs" / "api-spec.yaml"
GENERATED_SPEC = Path("openapi-generated.json")


def normalized(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def main() -> None:
    committed = yaml.safe_load(COMMITTED_SPEC.read_text())
    generated = json.loads(GENERATED_SPEC.read_text())
    if normalized(committed) != normalized(generated):
        raise SystemExit(
            "Generated OpenAPI differs from docs/api-spec.yaml. "
            "Regenerate the committed contract."
        )


if __name__ == "__main__":
    main()
