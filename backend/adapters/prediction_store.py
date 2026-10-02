"""Immutable prediction batches bound to dataset version snapshots."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from backend.adapters.dataset_store import DatasetNotFound, DatasetStore
from backend.domain.datasets import EvaluationCase
from backend.domain.predictions import EvaluationType, Prediction

PREDICTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS prediction_batches (
    id TEXT PRIMARY KEY,
    dataset_version_id TEXT NOT NULL REFERENCES dataset_versions(id),
    evaluation_type TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    created_at TEXT NOT NULL,
    record_count INTEGER NOT NULL,
    matched_count INTEGER NOT NULL,
    missing_case_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS predictions (
    batch_id TEXT NOT NULL REFERENCES prediction_batches(id),
    position INTEGER NOT NULL,
    case_id TEXT NOT NULL,
    answer TEXT,
    contexts_json TEXT,
    latency_ms REAL,
    PRIMARY KEY(batch_id, case_id),
    UNIQUE(batch_id, position)
);
CREATE TABLE IF NOT EXISTS prediction_attempts (
    batch_id TEXT NOT NULL REFERENCES prediction_batches(id),
    case_id TEXT NOT NULL,
    error TEXT,
    attempts_json TEXT NOT NULL,
    usage_json TEXT,
    elapsed_ms REAL,
    PRIMARY KEY(batch_id, case_id)
);
"""


class PredictionNotFound(Exception):
    pass


class PredictionStore(DatasetStore):
    def _connect(self) -> sqlite3.Connection:
        connection = super()._connect()
        connection.executescript(PREDICTION_SCHEMA)
        return connection

    def resolve_version(self, dataset_id: str, version: int | None) -> tuple[int, set[str]]:
        with closing(self._connect()) as connection:
            if version is None:
                row = connection.execute(
                    "SELECT id, version FROM dataset_versions WHERE dataset_id = ? "
                    "ORDER BY version DESC LIMIT 1",
                    (dataset_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT id, version FROM dataset_versions WHERE dataset_id = ? AND version = ?",
                    (dataset_id, version),
                ).fetchone()
            if row is None:
                raise DatasetNotFound(dataset_id)
            ids = connection.execute(
                "SELECT case_id FROM evaluation_cases WHERE version_id = ?", (row["id"],)
            ).fetchall()
        return int(row["version"]), {item["case_id"] for item in ids}

    def import_batch(
        self,
        dataset_id: str | None,
        dataset_version: int | None,
        dataset_name: str | None,
        filename: str,
        evaluation_type: EvaluationType,
        predictions: list[Prediction],
        cases: list[EvaluationCase] | None,
    ) -> dict[str, Any]:
        created_at = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if cases is not None:
                dataset = self.insert_version(connection, dataset_name, None, filename, cases)
                dataset_id = dataset["dataset_id"]
                dataset_version = dataset["version"]
                version_id = dataset["id"]
                case_count = len(cases)
            else:
                row = connection.execute(
                    "SELECT id, case_count, version FROM dataset_versions "
                    "WHERE dataset_id = ? AND version = ?",
                    (dataset_id, dataset_version),
                ).fetchone()
                if row is None:
                    raise DatasetNotFound(dataset_id)
                version_id = row["id"]
                case_count = int(row["case_count"])
                dataset_version = int(row["version"])
            batch_id = str(uuid4())
            connection.execute(
                "INSERT INTO prediction_batches "
                "(id, dataset_version_id, evaluation_type, source_filename, created_at, "
                "record_count, matched_count, missing_case_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    batch_id,
                    version_id,
                    evaluation_type,
                    filename,
                    created_at,
                    len(predictions),
                    len(predictions),
                    case_count - len(predictions),
                ),
            )
            connection.executemany(
                "INSERT INTO predictions "
                "(batch_id, position, case_id, answer, contexts_json, latency_ms) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        batch_id,
                        position,
                        prediction.case_id,
                        prediction.answer,
                        json.dumps(
                            [vars(chunk) for chunk in prediction.contexts], ensure_ascii=False
                        )
                        if prediction.contexts is not None
                        else None,
                        prediction.latency_ms,
                    )
                    for position, prediction in enumerate(predictions)
                ],
            )
        return {
            "id": batch_id,
            "dataset_id": dataset_id,
            "dataset_version": dataset_version,
            "evaluation_type": evaluation_type,
            "source_filename": filename,
            "created_at": created_at,
            "record_count": len(predictions),
            "matched_count": len(predictions),
            "missing_case_count": case_count - len(predictions),
        }

    def list_batches(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT b.id, v.dataset_id, v.version AS dataset_version, "
                "b.evaluation_type, b.source_filename, b.created_at, b.record_count, "
                "b.matched_count, b.missing_case_count "
                "FROM prediction_batches b JOIN dataset_versions v ON v.id = b.dataset_version_id "
                "ORDER BY b.created_at DESC, b.id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_batch(self, batch_id: str, offset: int, limit: int) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            batch = connection.execute(
                "SELECT b.id, v.dataset_id, v.version AS dataset_version, "
                "b.evaluation_type, b.source_filename, b.created_at, b.record_count, "
                "b.matched_count, b.missing_case_count "
                "FROM prediction_batches b JOIN dataset_versions v ON v.id = b.dataset_version_id "
                "WHERE b.id = ?",
                (batch_id,),
            ).fetchone()
            if batch is None:
                raise PredictionNotFound(batch_id)
            rows = connection.execute(
                "SELECT case_id, answer, contexts_json, latency_ms FROM predictions "
                "WHERE batch_id = ? ORDER BY position LIMIT ? OFFSET ?",
                (batch_id, limit, offset),
            ).fetchall()
        return {
            **dict(batch),
            "offset": offset,
            "limit": limit,
            "predictions": [
                {
                    "case_id": row["case_id"],
                    "answer": row["answer"],
                    "contexts": json.loads(row["contexts_json"])
                    if row["contexts_json"] is not None
                    else None,
                    "latency_ms": row["latency_ms"],
                }
                for row in rows
            ],
        }
