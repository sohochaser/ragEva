"""Local HTTP targets, secret files, and durable prediction collection jobs."""

import json
import os
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.adapters.http_target import TargetCall
from backend.adapters.prediction_store import PredictionStore
from backend.domain.predictions import EvaluationType

TARGET_SCHEMA = """
CREATE TABLE IF NOT EXISTS http_targets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    has_token INTEGER NOT NULL,
    timeout_seconds REAL NOT NULL,
    retries INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS target_jobs (
    id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL REFERENCES http_targets(id),
    version_id TEXT NOT NULL REFERENCES dataset_versions(id),
    evaluation_type TEXT NOT NULL,
    status TEXT NOT NULL,
    batch_id TEXT REFERENCES prediction_batches(id),
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS target_job_cases (
    job_id TEXT NOT NULL REFERENCES target_jobs(id),
    position INTEGER NOT NULL,
    case_id TEXT NOT NULL,
    status TEXT NOT NULL,
    prediction_json TEXT,
    error TEXT,
    attempts_json TEXT,
    usage_json TEXT,
    elapsed_ms REAL,
    PRIMARY KEY(job_id, case_id)
);
"""


class TargetNotFound(Exception):
    pass


class TargetJobNotFound(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


class TargetStore(PredictionStore):
    def __init__(self, data_dir: Path) -> None:
        super().__init__(data_dir)
        self.secret_dir = data_dir / "secrets" / "targets"

    def _connect(self) -> sqlite3.Connection:
        connection = super()._connect()
        connection.executescript(TARGET_SCHEMA)
        return connection

    def create_target(
        self, name: str, url: str, token: str | None, timeout_seconds: float, retries: int
    ) -> dict[str, Any]:
        target_id = str(uuid4())
        secret_path = self.secret_dir / target_id
        if token:
            self.secret_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(secret_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(token)
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    "INSERT INTO http_targets "
                    "(id, name, url, has_token, timeout_seconds, retries, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (target_id, name, url, bool(token), timeout_seconds, retries, _now()),
                )
        except Exception:
            secret_path.unlink(missing_ok=True)
            raise
        return self.get_target(target_id)

    def get_target(self, target_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM http_targets WHERE id = ?", (target_id,)
            ).fetchone()
        if row is None:
            raise TargetNotFound(target_id)
        return {**dict(row), "has_token": bool(row["has_token"])}

    def list_targets(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id FROM http_targets ORDER BY created_at DESC, id DESC"
            ).fetchall()
        return [self.get_target(row["id"]) for row in rows]

    def token(self, target_id: str) -> str | None:
        target = self.get_target(target_id)
        if not target["has_token"]:
            return None
        return (self.secret_dir / target_id).read_text(encoding="utf-8")

    def create_job(
        self, target_id: str, dataset_id: str, version: int, evaluation_type: EvaluationType
    ) -> dict[str, Any]:
        job_id = str(uuid4())
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            target = connection.execute(
                "SELECT 1 FROM http_targets WHERE id = ?", (target_id,)
            ).fetchone()
            if target is None:
                raise TargetNotFound(target_id)
            dataset = connection.execute(
                "SELECT id FROM dataset_versions WHERE dataset_id = ? AND version = ?",
                (dataset_id, version),
            ).fetchone()
            if dataset is None:
                raise TargetJobNotFound(dataset_id)
            connection.execute(
                "INSERT INTO target_jobs "
                "(id, target_id, version_id, evaluation_type, status, created_at) "
                "VALUES (?, ?, ?, ?, 'queued', ?)",
                (job_id, target_id, dataset["id"], evaluation_type, _now()),
            )
            connection.execute(
                "INSERT INTO target_job_cases (job_id, position, case_id, status) "
                "SELECT ?, position, case_id, 'pending' FROM evaluation_cases "
                "WHERE version_id = ? ORDER BY position",
                (job_id, dataset["id"]),
            )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT j.id, j.target_id, v.dataset_id, v.version AS dataset_version, "
                "j.evaluation_type, j.status, j.batch_id, j.created_at, "
                "j.started_at, j.finished_at "
                "FROM target_jobs j JOIN dataset_versions v ON v.id = j.version_id "
                "WHERE j.id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise TargetJobNotFound(job_id)
            counts = connection.execute(
                "SELECT status, COUNT(*) AS count FROM target_job_cases WHERE job_id = ? "
                "GROUP BY status",
                (job_id,),
            ).fetchall()
        by_status = {item["status"]: item["count"] for item in counts}
        total = sum(by_status.values())
        return {
            **dict(row),
            "total_count": total,
            "processed_count": total - by_status.get("pending", 0),
            "success_count": by_status.get("success", 0),
            "failed_count": by_status.get("failed", 0),
        }

    def list_jobs(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id FROM target_jobs ORDER BY created_at DESC, id DESC LIMIT 100"
            ).fetchall()
        return [self.get_job(row["id"]) for row in rows]

    def claim_job(self, job_id: str) -> bool:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE target_jobs SET status = 'running', started_at = ? "
                "WHERE id = ? AND status = 'queued'",
                (_now(), job_id),
            ).rowcount
        return changed == 1

    def pending_cases(self, job_id: str) -> list[tuple[str, str]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT c.case_id, c.question FROM target_job_cases jc "
                "JOIN target_jobs j ON j.id = jc.job_id "
                "JOIN evaluation_cases c ON c.version_id = j.version_id "
                "AND c.case_id = jc.case_id "
                "WHERE jc.job_id = ? AND jc.status = 'pending' ORDER BY jc.position",
                (job_id,),
            ).fetchall()
        return [(row["case_id"], row["question"]) for row in rows]

    def record_case(self, job_id: str, case_id: str, result: TargetCall) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE target_job_cases SET status = ?, prediction_json = ?, error = ?, "
                "attempts_json = ?, usage_json = ?, elapsed_ms = ? "
                "WHERE job_id = ? AND case_id = ? AND status = 'pending'",
                (
                    "success" if result.prediction else "failed",
                    json.dumps(asdict(result.prediction), ensure_ascii=False)
                    if result.prediction
                    else None,
                    result.error,
                    json.dumps([asdict(item) for item in result.attempts]),
                    json.dumps(result.usage) if result.usage is not None else None,
                    sum(item.elapsed_ms for item in result.attempts),
                    job_id,
                    case_id,
                ),
            )

    def fail_pending(self, job_id: str, error: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE target_job_cases SET status = 'failed', error = ?, attempts_json = '[]' "
                "WHERE job_id = ? AND status = 'pending'",
                (error, job_id),
            )

    def finish_job(self, job_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT j.status, j.target_id, j.version_id, j.evaluation_type, "
                "t.name AS target_name FROM target_jobs j "
                "JOIN http_targets t ON t.id = j.target_id WHERE j.id = ?",
                (job_id,),
            ).fetchone()
            if job is None:
                raise TargetJobNotFound(job_id)
            if job["status"] != "running":
                return self.get_job(job_id)
            connection.execute(
                "UPDATE target_job_cases SET status = 'failed', error = 'incomplete_worker', "
                "attempts_json = '[]' WHERE job_id = ? AND status = 'pending'",
                (job_id,),
            )
            rows = connection.execute(
                "SELECT position, case_id, status, prediction_json, error, attempts_json, "
                "usage_json, elapsed_ms FROM target_job_cases WHERE job_id = ? ORDER BY position",
                (job_id,),
            ).fetchall()
            batch_id = str(uuid4())
            successes = sum(row["status"] == "success" for row in rows)
            connection.execute(
                "INSERT INTO prediction_batches "
                "(id, dataset_version_id, evaluation_type, source_filename, created_at, "
                "record_count, matched_count, missing_case_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    batch_id,
                    job["version_id"],
                    job["evaluation_type"],
                    f"HTTP: {job['target_name']}",
                    _now(),
                    successes,
                    successes,
                    len(rows) - successes,
                ),
            )
            for row in rows:
                if row["status"] == "success":
                    prediction = json.loads(row["prediction_json"])
                    connection.execute(
                        "INSERT INTO predictions "
                        "(batch_id, position, case_id, answer, contexts_json, latency_ms) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            batch_id,
                            row["position"],
                            row["case_id"],
                            prediction["answer"],
                            json.dumps(prediction["contexts"], ensure_ascii=False)
                            if prediction["contexts"] is not None
                            else None,
                            prediction["latency_ms"],
                        ),
                    )
                connection.execute(
                    "INSERT INTO prediction_attempts "
                    "(batch_id, case_id, error, attempts_json, usage_json, elapsed_ms) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        batch_id,
                        row["case_id"],
                        row["error"],
                        row["attempts_json"],
                        row["usage_json"],
                        row["elapsed_ms"],
                    ),
                )
            connection.execute(
                "UPDATE target_jobs SET status = ?, batch_id = ?, finished_at = ? WHERE id = ?",
                ("completed" if successes == len(rows) else "failed", batch_id, _now(), job_id),
            )
        return self.get_job(job_id)

    def job_cases(self, job_id: str) -> list[dict[str, Any]]:
        self.get_job(job_id)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT case_id, status, error, attempts_json, usage_json, elapsed_ms "
                "FROM target_job_cases WHERE job_id = ? ORDER BY position",
                (job_id,),
            ).fetchall()
        return [
            {
                "case_id": row["case_id"],
                "status": row["status"],
                "error": row["error"],
                "attempts": json.loads(row["attempts_json"]) if row["attempts_json"] else None,
                "usage": json.loads(row["usage_json"]) if row["usage_json"] else None,
                "elapsed_ms": row["elapsed_ms"],
            }
            for row in rows
        ]
