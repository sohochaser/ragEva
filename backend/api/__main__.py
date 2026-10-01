"""Run the management API on the configured local interface."""

import sys

import uvicorn

from backend.api.main import create_app
from backend.config import Settings


def main() -> int:
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    uvicorn.run(create_app(settings), host=settings.api_host, port=settings.api_port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
