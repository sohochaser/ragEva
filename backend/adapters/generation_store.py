"""Durable generation jobs, attempts, and reviewable candidates."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.adapters.document_store import DocumentStore
from backend.adapters.generation_model import GeneratedCase
from backend.domain.generation import PROMPT_VERSION, GenerationSlot, reference_chunks

SCHEMA = """
CREATE TABLE IF NOT EXISTS generation_runs (
    id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES document_collections(id),
    status TEXT NOT NULL,
    config_json TEXT NOT NULL,
    target_count INTEGER NOT NULL,
    target_multi_count INTEGER NOT NULL,
    max_calls INTEGER NOT NULL,
    max_concurrency INTEGER NOT NULL,
    attempted_count INTEGER NOT NULL DEFAULT 0,
    actual_count INTEGER NOT NULL DEFAULT 0,
    actual_multi_count INTEGER NOT NULL DEFAULT 0,
    shortfall_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS generation_attempts (
    run_id TEXT NOT NULL REFERENCES generation_runs(id),
    attempt_number INTEGER NOT NULL,
    slot_index INTEGER NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    usage_json TEXT,
    PRIMARY KEY(run_id, attempt_number)
);
CREATE TABLE IF NOT EXISTS generated_candidates (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES generation_runs(id),
    slot_index INTEGER NOT NULL,
    question TEXT NOT NULL,
    reference_answer TEXT NOT NULL,
    reference_chunks_json TEXT NOT NULL,
    support_positions_json TEXT NOT NULL,
    multi_chunk INTEGER NOT NULL,
    status TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, slot_index)
);
"""


class GenerationNotFound(Exception):
    pass


class GenerationStore(DocumentStore):
    def __init__(self, data_dir: Path) -> None:
        super().__init__(data_dir)

    def _connect(self) -> sqlite3.Connection:
        connection = super()._connect()
        connection.executescript(SCHEMA)
        return connection

    def create_run(
        self,
        collection_id: str,
        config: dict[str, Any],
        target_count: int,
        target_multi_count: int,
        max_calls: int,
        max_concurrency: int,
    ) -> dict[str, Any]:
        self.get_collection(collection_id)
        run_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO generation_runs "
                "(id, collection_id, status, config_json, target_count, target_multi_count, "
                "max_calls, max_concurrency, created_at) VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    collection_id,
                    json.dumps(config, ensure_ascii=False),
                    target_count,
                    target_multi_count,
                    max_calls,
                    max_concurrency,
                    now,
                ),
            )
        return self.get(run_id)

    def get_collection(self, collection_id: str) -> dict[str, Any]:
        return super().get(collection_id)

    def get(self, run_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM generation_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise GenerationNotFound(run_id)
            errors = connection.execute(
                "SELECT error, COUNT(*) AS count FROM generation_attempts "
                "WHERE run_id = ? AND error IS NOT NULL GROUP BY error ORDER BY count DESC, error",
                (run_id,),
            ).fetchall()
        result = dict(row)
        result["config"] = json.loads(result.pop("config_json"))
        result["shortfall_reasons"] = json.loads(result.pop("shortfall_json"))
        result["attempt_errors"] = {item["error"]: item["count"] for item in errors}
        return result

    def list_runs(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            ids = connection.execute(
                "SELECT id FROM generation_runs ORDER BY created_at DESC, id DESC"
            ).fetchall()
        return [self.get(row["id"]) for row in ids]

    def claim(self, run_id: str) -> bool:
        with closing(self._connect()) as connection, connection:
            changed = connection.execute(
                "UPDATE generation_runs SET status = 'running', started_at = ? "
                "WHERE id = ? AND status = 'queued'",
                (datetime.now(UTC).isoformat(), run_id),
            ).rowcount
        return bool(changed)

    def record(
        self,
        run_id: str,
        slot: GenerationSlot,
        case: GeneratedCase | None,
        error: str | None,
    ) -> None:
        model_name = self.get(run_id)["config"]["model_name"] if case is not None else None
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT attempted_count FROM generation_runs WHERE id = ? AND status = 'running'",
                (run_id,),
            ).fetchone()
            if row is None:
                return
            attempt_number = row["attempted_count"] + 1
            connection.execute(
                "INSERT INTO generation_attempts VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    attempt_number,
                    slot.index,
                    "success" if case else "failed",
                    error,
                    json.dumps(case.usage) if case and case.usage else None,
                ),
            )
            if case is not None:
                chunks = reference_chunks(case.support_positions, slot.sources, slot.multi_chunk)
                connection.execute(
                    "INSERT INTO generated_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid4()),
                        run_id,
                        slot.index,
                        case.question,
                        case.reference_answer,
                        json.dumps(chunks, ensure_ascii=False),
                        json.dumps(case.support_positions),
                        int(slot.multi_chunk),
                        "pending_review",
                        PROMPT_VERSION,
                        model_name,
                        datetime.now(UTC).isoformat(),
                    ),
                )
            connection.execute(
                "UPDATE generation_runs SET attempted_count = attempted_count + 1, "
                "actual_count = actual_count + ?, actual_multi_count = actual_multi_count + ? "
                "WHERE id = ?",
                (int(case is not None), int(case is not None and slot.multi_chunk), run_id),
            )

    def finish(
        self, run_id: str, unavailable_multi: int = 0, fatal_error: str | None = None
    ) -> None:
        run = self.get(run_id)
        if run["status"] != "running":
            return
        reasons = []
        if unavailable_multi:
            reasons.append("insufficient_source_chunks")
        if run["actual_count"] < run["target_count"]:
            if run["attempted_count"] >= run["max_calls"]:
                reasons.append("call_limit_reached")
            if run["attempt_errors"]:
                reasons.append("model_or_validation_errors")
            if fatal_error:
                reasons.append(fatal_error)
            if not reasons:
                reasons.append("insufficient_candidates")
        status = (
            "completed"
            if run["actual_count"] == run["target_count"]
            else "partial"
            if run["actual_count"]
            else "failed"
        )
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE generation_runs SET status = ?, shortfall_json = ?, finished_at = ? "
                "WHERE id = ? AND status = 'running'",
                (status, json.dumps(reasons), datetime.now(UTC).isoformat(), run_id),
            )

    def candidates(self, run_id: str) -> list[dict[str, Any]]:
        self.get(run_id)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM generated_candidates WHERE run_id = ? ORDER BY slot_index",
                (run_id,),
            ).fetchall()
        candidates = []
        for row in rows:
            item = dict(row)
            item["reference_chunks"] = json.loads(item.pop("reference_chunks_json"))
            item["support_positions"] = json.loads(item.pop("support_positions_json"))
            item["multi_chunk"] = bool(item["multi_chunk"])
            candidates.append(item)
        return candidates
