"""Run only the document download routes on their configured interface."""

import sys

import uvicorn

from backend.config import DownloadSettings
from backend.download.app import create_app


def main() -> int:
    try:
        settings = DownloadSettings.from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
