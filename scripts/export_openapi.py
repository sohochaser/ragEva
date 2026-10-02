"""Generate or verify the checked-in API contract."""

import argparse
import json
from pathlib import Path

from backend.api.main import create_app
from backend.config import Settings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / "contracts" / "openapi.json"
    contract = (
        json.dumps(
            create_app(Settings(data_dir=Path(".local"))).openapi(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != contract:
            print("OpenAPI contract is stale; run uv run python scripts/export_openapi.py")
            return 1
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(contract, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
