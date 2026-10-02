"""Durable per-call usage ledger and source-aware totals."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

SCHEMA = """
CREATE TABLE IF NOT EXISTS model_usage_calls (
    id TEXT PRIMARY KEY,
    owner_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    case_id TEXT,
    model_id TEXT NOT NULL,
    input_tokens INTEGER,
    input_source TEXT NOT NULL,
    output_tokens INTEGER,
    output_source TEXT NOT NULL,
    tokenizer TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS model_usage_owner ON model_usage_calls(owner_type, owner_id, created_at);
"""


def summarize_calls(calls: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, dict[str, dict[str, int]]] = {
        side: {
            source: {"calls": 0, "tokens": 0}
            for source in ("actual", "estimated", "not_applicable", "unknown")
        }
        for side in ("input", "output")
    }
    for call in calls:
        for side in ("input", "output"):
            bucket = totals[side][call[f"{side}_source"]]
            bucket["calls"] += 1
            bucket["tokens"] += call[f"{side}_tokens"] or 0
    return {"call_count": len(calls), "totals": totals, "calls": calls}


class UsageStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "usage.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)
        return connection

    def record(
        self,
        owner_type: str,
        owner_id: str,
        operation: str,
        case_id: str | None,
        model_id: str,
        usage: dict[str, Any],
    ) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO model_usage_calls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    owner_type,
                    owner_id,
                    operation,
                    case_id,
                    model_id,
                    usage["input_tokens"],
                    usage["input_source"],
                    usage["output_tokens"],
                    usage["output_source"],
                    usage["tokenizer"],
                    datetime.now(UTC).isoformat(),
                ),
            )

    def for_owner(self, owner_type: str, owner_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM model_usage_calls WHERE owner_type = ? AND owner_id = ? "
                "ORDER BY created_at, id",
                (owner_type, owner_id),
            ).fetchall()
        return summarize_calls([dict(row) for row in rows])
