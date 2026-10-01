"""Local process configuration."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


def _positive_int(name: str, raw: str, maximum: int | None = None) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 1 or (maximum is not None and value > maximum):
        limit = f" between 1 and {maximum}" if maximum is not None else " positive"
        raise ValueError(f"{name} must be{limit}")
    return value


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    heartbeat_interval: int = 2
    worker_stale_after: int = 8

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        values = os.environ if environ is None else environ
        host = values.get("RAGEVA_API_HOST", "127.0.0.1").strip()
        if not host:
            raise ValueError("RAGEVA_API_HOST must not be empty")
        return cls(
            data_dir=Path(values.get("RAGEVA_DATA_DIR", ".local")).expanduser().resolve(),
            api_host=host,
            api_port=_positive_int("RAGEVA_API_PORT", values.get("RAGEVA_API_PORT", "8000"), 65535),
            heartbeat_interval=_positive_int(
                "RAGEVA_HEARTBEAT_INTERVAL", values.get("RAGEVA_HEARTBEAT_INTERVAL", "2")
            ),
            worker_stale_after=_positive_int(
                "RAGEVA_WORKER_STALE_AFTER", values.get("RAGEVA_WORKER_STALE_AFTER", "8")
            ),
        )
