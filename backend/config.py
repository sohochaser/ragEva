"""Local process configuration."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def _positive_int(name: str, raw: str, maximum: int | None = None) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 1 or (maximum is not None and value > maximum):
        limit = f" between 1 and {maximum}" if maximum is not None else " positive"
        raise ValueError(f"{name} must be{limit}")
    return value


def _service_url(name: str, raw: str) -> str | None:
    value = raw.strip().rstrip("/")
    if not value:
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{name} must be an HTTP(S) URL without credentials or query")
    return value


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    heartbeat_interval: int = 2
    worker_stale_after: int = 8
    jaeger_url: str | None = None
    trace_retention_days: int = 30
    otlp_traces_endpoint: str | None = None

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
            jaeger_url=_service_url("RAGEVA_JAEGER_URL", values.get("RAGEVA_JAEGER_URL", "")),
            trace_retention_days=_positive_int(
                "RAGEVA_TRACE_RETENTION_DAYS", values.get("RAGEVA_TRACE_RETENTION_DAYS", "30")
            ),
            otlp_traces_endpoint=_service_url(
                "RAGEVA_OTLP_TRACES_ENDPOINT", values.get("RAGEVA_OTLP_TRACES_ENDPOINT", "")
            ),
        )


@dataclass(frozen=True)
class DownloadSettings:
    data_dir: Path
    token: str
    host: str = "127.0.0.1"
    port: int = 8001
    public_url: str = "http://127.0.0.1:8001"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "DownloadSettings":
        values = os.environ if environ is None else environ
        token = values.get("RAGEVA_DOWNLOAD_TOKEN", "")
        if not token.strip():
            raise ValueError("RAGEVA_DOWNLOAD_TOKEN must not be empty")
        host = values.get("RAGEVA_DOWNLOAD_HOST", "127.0.0.1").strip()
        if not host:
            raise ValueError("RAGEVA_DOWNLOAD_HOST must not be empty")
        port = _positive_int(
            "RAGEVA_DOWNLOAD_PORT", values.get("RAGEVA_DOWNLOAD_PORT", "8001"), 65535
        )
        public_url = (
            values.get("RAGEVA_DOWNLOAD_PUBLIC_URL", f"http://127.0.0.1:{port}").strip().rstrip("/")
        )
        parsed = urlsplit(public_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("RAGEVA_DOWNLOAD_PUBLIC_URL must be an HTTP(S) base URL")
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("RAGEVA_DOWNLOAD_PUBLIC_URL has an invalid port") from exc
        public_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
        return cls(
            data_dir=Path(values.get("RAGEVA_DATA_DIR", ".local")).expanduser().resolve(),
            token=token,
            host=host,
            port=port,
            public_url=public_url,
        )
