"""Atomic candidate publication into immutable dataset versions."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from backend.adapters.dataset_store import DatasetNotFound, DatasetStore
from backend.adapters.generation_store import DuplicateDecisionConflict, GenerationStore
from backend.domain.datasets import (
    FIELDS,
    EvaluationCase,
    ImportIssue,
    ReferenceChunk,
    SourceRow,
    validate_cases,
)


class PublicationConflict(Exception):
    pass


class InvalidPublication(Exception):
    def __init__(self, issues: list[ImportIssue]) -> None:
        self.issues = issues


class PublicationStore(GenerationStore):
    def __init__(self, data_dir: Path) -> None:
        super().__init__(data_dir)
        self.datasets = DatasetStore(data_dir)
        with closing(self.datasets._connect()):
            pass

    def publish(
        self,
        candidate_ids: list[str],
        *,
        dataset_name: str | None,
        dataset_id: str | None,
        expected_version: int | None,
    ) -> dict[str, Any]:
        if not candidate_ids or len(set(candidate_ids)) != len(candidate_ids):
            raise InvalidPublication(
                [ImportIssue(None, "candidate_ids", "invalid_selection", "请选择不同的候选")]
            )
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            previous_id: str | None = None
            previous_cases: list[EvaluationCase] = []
            if dataset_id is not None:
                previous_id, previous_cases = self._previous_version(
                    connection, dataset_id, expected_version
                )

            candidates = []
            for candidate_id in candidate_ids:
                try:
                    candidates.append(self.assert_publishable(connection, candidate_id))
                except DuplicateDecisionConflict as exc:
                    raise PublicationConflict(
                        f"候选 {candidate_id} 未批准，或当前查重结论不允许发布"
                    ) from exc

            rows = [
                SourceRow(
                    line=index,
                    values={
                        "case_id": f"gen-{candidate['id']}",
                        "question": candidate["question"],
                        "reference_answer": candidate["reference_answer"],
                        "reference_chunks": candidate["reference_chunks"],
                    },
                )
                for index, candidate in enumerate(candidates, 1)
            ]
            new_cases, issues = validate_cases(rows, {field: field for field in FIELDS})
            if issues:
                raise InvalidPublication(issues)
            old_ids = {case.case_id for case in previous_cases}
            conflicts = old_ids & {case.case_id for case in new_cases}
            if conflicts:
                raise PublicationConflict(f"样本 ID 已存在：{min(conflicts)}")

            summary = self.datasets.insert_version(
                connection,
                dataset_name,
                dataset_id,
                "generated-candidates",
                previous_cases + new_cases,
            )
            version_id = summary["id"]
            if previous_id is not None:
                connection.execute(
                    "INSERT INTO dataset_version_sources (version_id, collection_id) "
                    "SELECT ?, collection_id FROM dataset_version_sources WHERE version_id = ?",
                    (version_id, previous_id),
                )
            for candidate, case in zip(candidates, new_cases, strict=True):
                connection.execute(
                    "INSERT OR IGNORE INTO dataset_version_sources VALUES (?, ?)",
                    (version_id, candidate["collection_id"]),
                )
                self.record_published_candidate(
                    connection, candidate["id"], version_id, case.case_id
                )
            if previous_id is not None:
                connection.execute(
                    "INSERT INTO published_candidate_cases "
                    "(version_id, case_id, candidate_id, collection_id, "
                    "question, reference_answer, "
                    "reference_chunks_json, published_at) "
                    "SELECT ?, case_id, candidate_id, collection_id, question, reference_answer, "
                    "reference_chunks_json, published_at FROM published_candidate_cases "
                    "WHERE version_id = ?",
                    (version_id, previous_id),
                )
            summary["source_collection_ids"] = self.datasets._source_collection_ids(
                connection, version_id
            )
        return summary

    @staticmethod
    def _previous_version(
        connection: sqlite3.Connection, dataset_id: str, expected_version: int | None
    ) -> tuple[str, list[EvaluationCase]]:
        row = connection.execute(
            "SELECT id, version FROM dataset_versions WHERE dataset_id = ? "
            "ORDER BY version DESC LIMIT 1",
            (dataset_id,),
        ).fetchone()
        if row is None:
            raise DatasetNotFound(dataset_id)
        if row["version"] != expected_version:
            raise PublicationConflict("数据集已有新版本，请刷新后重试")
        rows = connection.execute(
            "SELECT case_id, question, reference_answer, reference_chunks_json "
            "FROM evaluation_cases WHERE version_id = ? ORDER BY position",
            (row["id"],),
        ).fetchall()
        cases = [
            EvaluationCase(
                case_id=item["case_id"],
                question=item["question"],
                reference_answer=item["reference_answer"],
                reference_chunks=tuple(
                    ReferenceChunk(**chunk) for chunk in json.loads(item["reference_chunks_json"])
                )
                if item["reference_chunks_json"] is not None
                else None,
            )
            for item in rows
        ]
        return row["id"], cases
