"""SQLite snapshots for imported datasets."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.domain.datasets import EvaluationCase

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dataset_versions (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES datasets(id),
    version INTEGER NOT NULL,
    case_count INTEGER NOT NULL,
    source_filename TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(dataset_id, version)
);
CREATE TABLE IF NOT EXISTS evaluation_cases (
    version_id TEXT NOT NULL REFERENCES dataset_versions(id),
    position INTEGER NOT NULL,
    case_id TEXT NOT NULL,
    question TEXT NOT NULL,
    reference_answer TEXT,
    reference_chunks_json TEXT,
    PRIMARY KEY(version_id, case_id),
    UNIQUE(version_id, position)
);
"""


class DatasetNotFound(Exception):
    pass


class DatasetStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "rageva.sqlite3"

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        return connection

    def import_cases(
        self, name: str | None, dataset_id: str | None, filename: str, cases: list[EvaluationCase]
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            summary = self.insert_version(connection, name, dataset_id, filename, cases)
        return summary

    def insert_version(
        self,
        connection: sqlite3.Connection,
        name: str | None,
        dataset_id: str | None,
        filename: str,
        cases: list[EvaluationCase],
    ) -> dict[str, Any]:
        created_at = datetime.now(UTC).isoformat()
        if dataset_id is None:
            if name is None:
                raise ValueError("新建数据集需要名称")
            dataset_id = str(uuid4())
            connection.execute(
                "INSERT INTO datasets (id, name, created_at) VALUES (?, ?, ?)",
                (dataset_id, name, created_at),
            )
            version = 1
        else:
            exists = connection.execute(
                "SELECT 1 FROM datasets WHERE id = ?", (dataset_id,)
            ).fetchone()
            if exists is None:
                raise DatasetNotFound(dataset_id)
            latest = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM dataset_versions WHERE dataset_id = ?",
                (dataset_id,),
            ).fetchone()[0]
            version = int(latest) + 1
        version_id = str(uuid4())
        connection.execute(
            "INSERT INTO dataset_versions "
            "(id, dataset_id, version, case_count, source_filename, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (version_id, dataset_id, version, len(cases), filename, created_at),
        )
        connection.executemany(
            "INSERT INTO evaluation_cases "
            "(version_id, position, case_id, question, reference_answer, "
            "reference_chunks_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    version_id,
                    position,
                    case.case_id,
                    case.question,
                    case.reference_answer,
                    json.dumps([vars(chunk) for chunk in case.reference_chunks], ensure_ascii=False)
                    if case.reference_chunks is not None
                    else None,
                )
                for position, case in enumerate(cases)
            ],
        )
        return {
            "id": version_id,
            "dataset_id": dataset_id,
            "version": version,
            "case_count": len(cases),
            "source_filename": filename,
            "created_at": created_at,
        }

    def list_datasets(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT d.id, d.name, d.created_at, COUNT(v.id) AS version_count, "
                "MAX(v.version) AS latest_version, "
                "(SELECT case_count FROM dataset_versions latest "
                " WHERE latest.dataset_id = d.id ORDER BY version DESC LIMIT 1) "
                "AS latest_case_count "
                "FROM datasets d LEFT JOIN dataset_versions v ON v.dataset_id = d.id "
                "GROUP BY d.id ORDER BY d.created_at DESC, d.id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_versions(self, dataset_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            exists = connection.execute(
                "SELECT 1 FROM datasets WHERE id = ?", (dataset_id,)
            ).fetchone()
            if exists is None:
                raise DatasetNotFound(dataset_id)
            rows = connection.execute(
                "SELECT id, dataset_id, version, case_count, source_filename, created_at "
                "FROM dataset_versions WHERE dataset_id = ? ORDER BY version DESC",
                (dataset_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_version(self, dataset_id: str, version: int, offset: int, limit: int) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT id, dataset_id, version, case_count, source_filename, created_at "
                "FROM dataset_versions WHERE dataset_id = ? AND version = ?",
                (dataset_id, version),
            ).fetchone()
            if row is None:
                raise DatasetNotFound(dataset_id)
            cases = connection.execute(
                "SELECT case_id, question, reference_answer, reference_chunks_json "
                "FROM evaluation_cases WHERE version_id = ? ORDER BY position LIMIT ? OFFSET ?",
                (row["id"], limit, offset),
            ).fetchall()
        return {
            **dict(row),
            "total": row["case_count"],
            "offset": offset,
            "limit": limit,
            "cases": [
                {
                    "case_id": case["case_id"],
                    "question": case["question"],
                    "reference_answer": case["reference_answer"],
                    "reference_chunks": json.loads(case["reference_chunks_json"])
                    if case["reference_chunks_json"] is not None
                    else None,
                }
                for case in cases
            ],
        }

    def get_case(self, dataset_id: str, version: int, case_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT c.case_id, c.question, c.reference_answer, c.reference_chunks_json "
                "FROM evaluation_cases c JOIN dataset_versions v ON v.id = c.version_id "
                "WHERE v.dataset_id = ? AND v.version = ? AND c.case_id = ?",
                (dataset_id, version, case_id),
            ).fetchone()
            if row is None:
                raise DatasetNotFound(dataset_id)
        return {
            "case_id": row["case_id"],
            "question": row["question"],
            "reference_answer": row["reference_answer"],
            "reference_chunks": json.loads(row["reference_chunks_json"])
            if row["reference_chunks_json"] is not None
            else None,
        }
