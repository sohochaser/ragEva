"""Durable references to trace spans, separate from Jaeger's short-lived storage."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from opentelemetry.trace import Span

from backend.config import Settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS trace_references (
    owner_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (owner_type, owner_id)
);
"""


class TraceStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "rageva.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executescript(SCHEMA)

    def record(self, owner_type: str, owner_id: str, span: Span) -> None:
        span_context = span.get_span_context()
        if not span_context.is_valid:
            return
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "INSERT OR IGNORE INTO trace_references VALUES (?, ?, ?, ?, ?)",
                (
                    owner_type,
                    owner_id,
                    f"{span_context.trace_id:032x}",
                    f"{span_context.span_id:016x}",
                    datetime.now(UTC).isoformat(),
                ),
            )

    def get(
        self, owner_type: str, owner_id: str, settings: Settings, now: datetime | None = None
    ) -> dict[str, Any] | None:
        with closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT trace_id, span_id, created_at FROM trace_references "
                "WHERE owner_type = ? AND owner_id = ?",
                (owner_type, owner_id),
            ).fetchone()
        if row is None:
            return None
        expires_at = datetime.fromisoformat(row["created_at"]) + timedelta(
            days=settings.trace_retention_days
        )
        expired = (now or datetime.now(UTC)) >= expires_at
        configured = bool(settings.jaeger_url and settings.otlp_traces_endpoint)
        return {
            "trace_id": row["trace_id"],
            "span_id": row["span_id"],
            "expires_at": expires_at.isoformat(),
            "status": "unconfigured" if not configured else "expired" if expired else "available",
            "url": f"{settings.jaeger_url}/trace/{row['trace_id']}"
            if configured and not expired
            else None,
        }
