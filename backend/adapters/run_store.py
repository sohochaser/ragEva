"""SQLite run snapshots and idempotent per-case results."""

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.adapters.prediction_store import PredictionStore
from backend.domain.retrieval_scoring import aggregate_retrieval, score_from_dict
from backend.domain.runs import CaseStatus, MetricKey

RUN_SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluation_runs (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES prediction_batches(id),
    status TEXT NOT NULL,
    config_json TEXT NOT NULL,
    model_id TEXT,
    aggregate_json TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS run_cases (
    run_id TEXT NOT NULL REFERENCES evaluation_runs(id),
    position INTEGER NOT NULL,
    case_id TEXT NOT NULL,
    status TEXT NOT NULL,
    score_json TEXT,
    error TEXT,
    elapsed_ms REAL,
    finished_at TEXT,
    PRIMARY KEY (run_id, case_id),
    UNIQUE (run_id, position)
);
CREATE TABLE IF NOT EXISTS run_answer_metrics (
    run_id TEXT NOT NULL REFERENCES evaluation_runs(id),
    case_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    status TEXT NOT NULL,
    score REAL,
    reason TEXT,
    raw_response TEXT,
    error TEXT,
    usage_json TEXT,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    criteria TEXT NOT NULL,
    PRIMARY KEY (run_id, case_id, metric),
    FOREIGN KEY (run_id, case_id) REFERENCES run_cases(run_id, case_id)
);
"""


class RunNotFound(Exception):
    pass


class RunInputError(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RunStore(PredictionStore):
    def __init__(self, data_dir: Path) -> None:
        super().__init__(data_dir)

    def _connect(self) -> sqlite3.Connection:
        connection = super()._connect()
        connection.executescript(RUN_SCHEMA)
        return connection

    def create_run(
        self,
        batch_id: str,
        model_name: str,
        model_path: str | None,
        offline: bool,
        threshold: float,
        metrics: list[MetricKey],
        mode: str = "retrieval",
        answer_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            batch = connection.execute(
                "SELECT dataset_version_id, evaluation_type FROM prediction_batches WHERE id = ?",
                (batch_id,),
            ).fetchone()
            if batch is None:
                raise RunNotFound(batch_id)
            if mode not in {"retrieval", "answer", "both"}:
                raise RunInputError("未知评测类型")
            if mode in {"retrieval", "both"} and batch["evaluation_type"] == "answer":
                raise RunInputError("该预测批次没有检索 chunk，不能运行检索指标")
            if mode in {"answer", "both"} and batch["evaluation_type"] == "retrieval":
                raise RunInputError("该预测批次没有答案，不能运行回答指标")
            if mode in {"answer", "both"} and answer_config is None:
                raise RunInputError("回答评测需要场景版本和评分模型")
            run_id = str(uuid4())
            config = {
                "prediction_batch_id": batch_id,
                "dataset_version_id": batch["dataset_version_id"],
                "model_name": model_name,
                "model_path": model_path,
                "offline": offline,
                "threshold": threshold,
                "metrics": metrics,
                "match_rule_version": "one-to-one-v1",
                "gain_rule_version": "ordered-linear-v1",
                "mode": mode,
                "answer": answer_config,
            }
            connection.execute(
                "INSERT INTO evaluation_runs "
                "(id, batch_id, status, config_json, created_at) VALUES (?, ?, 'queued', ?, ?)",
                (run_id, batch_id, json.dumps(config, ensure_ascii=False), _now()),
            )
            rows = connection.execute(
                "SELECT c.position, c.case_id, p.case_id AS predicted_id, pa.error AS target_error "
                "FROM evaluation_cases c LEFT JOIN predictions p "
                "ON p.case_id = c.case_id AND p.batch_id = ? "
                "LEFT JOIN prediction_attempts pa ON pa.case_id = c.case_id AND pa.batch_id = ? "
                "WHERE c.version_id = ? ORDER BY c.position",
                (batch_id, batch_id, batch["dataset_version_id"]),
            ).fetchall()
            connection.executemany(
                "INSERT INTO run_cases (run_id, position, case_id, status, error) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        row["position"],
                        row["case_id"],
                        "pending" if row["predicted_id"] else "failed",
                        None
                        if row["predicted_id"]
                        else row["target_error"] or "missing_prediction",
                    )
                    for row in rows
                ],
            )
        return self.get_run(run_id)

    def claim(self, run_id: str) -> bool:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE evaluation_runs SET status = 'running', started_at = ? "
                "WHERE id = ? AND status = 'queued' AND cancel_requested = 0",
                (_now(), run_id),
            ).rowcount
        return changed == 1

    def config(self, run_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT config_json FROM evaluation_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise RunNotFound(run_id)
        return json.loads(row["config_json"])

    def set_model_id(self, run_id: str, model_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE evaluation_runs SET model_id = ? WHERE id = ? AND status = 'running'",
                (model_id, run_id),
            )

    def pending_case_ids(self, run_id: str) -> list[str]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT case_id FROM run_cases WHERE run_id = ? AND status = 'pending' "
                "ORDER BY position",
                (run_id,),
            ).fetchall()
        return [row["case_id"] for row in rows]

    def input_for_case(self, run_id: str, case_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT c.question, c.reference_answer, c.reference_chunks_json, "
                "p.answer, p.contexts_json, p.latency_ms, pa.error AS target_error, "
                "pa.attempts_json, pa.usage_json, pa.elapsed_ms AS target_elapsed_ms "
                "FROM evaluation_runs r JOIN prediction_batches b ON b.id = r.batch_id "
                "JOIN evaluation_cases c ON c.version_id = b.dataset_version_id AND c.case_id = ? "
                "LEFT JOIN predictions p ON p.batch_id = b.id AND p.case_id = c.case_id "
                "LEFT JOIN prediction_attempts pa ON pa.batch_id = b.id "
                "AND pa.case_id = c.case_id "
                "WHERE r.id = ?",
                (case_id, run_id),
            ).fetchone()
        if row is None:
            raise RunNotFound(run_id)
        return {
            "question": row["question"],
            "reference_answer": row["reference_answer"],
            "reference_chunks": json.loads(row["reference_chunks_json"])
            if row["reference_chunks_json"] is not None
            else None,
            "answer": row["answer"],
            "contexts": json.loads(row["contexts_json"])
            if row["contexts_json"] is not None
            else None,
            "latency_ms": row["latency_ms"],
        }

    def cancellation_requested(self, run_id: str) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT cancel_requested FROM evaluation_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return row is None or bool(row["cancel_requested"])

    def record_case(
        self,
        run_id: str,
        case_id: str,
        status: CaseStatus,
        score: dict[str, Any] | None = None,
        error: str | None = None,
        elapsed_ms: float | None = None,
    ) -> bool:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE run_cases SET status = ?, score_json = ?, error = ?, "
                "elapsed_ms = ?, finished_at = ? "
                "WHERE run_id = ? AND case_id = ? AND status = 'pending' "
                "AND EXISTS (SELECT 1 FROM evaluation_runs WHERE id = ? "
                "AND status = 'running' AND cancel_requested = 0)",
                (
                    status,
                    json.dumps(score, ensure_ascii=False) if score is not None else None,
                    error,
                    elapsed_ms,
                    _now(),
                    run_id,
                    case_id,
                    run_id,
                ),
            ).rowcount
        return changed == 1

    def record_answer_metric(
        self, run_id: str, case_id: str, metric: str, result: dict[str, Any]
    ) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR REPLACE INTO run_answer_metrics "
                "(run_id, case_id, metric, status, score, reason, raw_response, error, "
                "usage_json, model_name, prompt_version, criteria) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    case_id,
                    metric,
                    result["status"],
                    result.get("score"),
                    result.get("reason"),
                    result.get("raw_response"),
                    result.get("error"),
                    json.dumps(result["usage"]) if result.get("usage") is not None else None,
                    result["model_name"],
                    result["prompt_version"],
                    result["criteria"],
                ),
            )

    def fail_pending(self, run_id: str, error: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE run_cases SET status = 'failed', error = ?, finished_at = ? "
                "WHERE run_id = ? AND status = 'pending' AND EXISTS "
                "(SELECT 1 FROM evaluation_runs WHERE id = ? AND cancel_requested = 0)",
                (error, _now(), run_id, run_id),
            )

    def finish(self, run_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT status, cancel_requested FROM evaluation_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if run is None or run["status"] != "running":
                return
            if run["cancel_requested"]:
                connection.execute(
                    "UPDATE run_cases SET status = 'cancelled', finished_at = ? "
                    "WHERE run_id = ? AND status = 'pending'",
                    (_now(), run_id),
                )
                status = "cancelled"
            else:
                connection.execute(
                    "UPDATE run_cases SET status = 'failed', error = 'incomplete_worker', "
                    "finished_at = ? WHERE run_id = ? AND status = 'pending'",
                    (_now(), run_id),
                )
                failed = connection.execute(
                    "SELECT COUNT(*) FROM run_cases WHERE run_id = ? AND status = 'failed'",
                    (run_id,),
                ).fetchone()[0]
                status = "failed" if failed else "completed"
            rows = connection.execute(
                "SELECT status, score_json FROM run_cases WHERE run_id = ?", (run_id,)
            ).fetchall()
            config = json.loads(
                connection.execute(
                    "SELECT config_json FROM evaluation_runs WHERE id = ?", (run_id,)
                ).fetchone()["config_json"]
            )
            successful = [
                score_from_dict(json.loads(row["score_json"]))
                for row in rows
                if row["status"] == "success" and row["score_json"]
            ]
            not_applicable = (
                sum(row["status"] == "not_applicable" for row in rows)
                if config.get("mode", "retrieval") != "answer"
                else 0
            )
            if config.get("mode") == "both":
                not_applicable = connection.execute(
                    "SELECT COUNT(*) FROM run_cases rc "
                    "JOIN evaluation_runs r ON r.id = rc.run_id "
                    "JOIN prediction_batches b ON b.id = r.batch_id "
                    "JOIN evaluation_cases c ON c.version_id = b.dataset_version_id "
                    "AND c.case_id = rc.case_id "
                    "WHERE rc.run_id = ? AND rc.status IN ('success', 'not_applicable') "
                    "AND c.reference_chunks_json IS NULL",
                    (run_id,),
                ).fetchone()[0]
            aggregate = aggregate_retrieval(successful + [None] * not_applicable)
            aggregate_data = asdict(aggregate)
            aggregate_data["answer_metrics"] = {}
            if config.get("mode") in {"answer", "both"}:
                metric_rows = connection.execute(
                    "SELECT metric, status, score FROM run_answer_metrics WHERE run_id = ?",
                    (run_id,),
                ).fetchall()
                answer_metrics = {}
                for metric in ("faithfulness", "relevance", "correctness"):
                    selected = [row for row in metric_rows if row["metric"] == metric]
                    scores = [row["score"] for row in selected if row["status"] == "success"]
                    answer_metrics[metric] = {
                        "valid_count": len(scores),
                        "failed_count": sum(row["status"] == "failed" for row in selected),
                        "not_applicable_count": sum(
                            row["status"] == "not_applicable" for row in selected
                        ),
                        "mean_score": sum(scores) / len(scores) if scores else None,
                    }
                aggregate_data["answer_metrics"] = answer_metrics
                if any(row["status"] == "failed" for row in metric_rows) and status != "cancelled":
                    status = "failed"
                if config.get("mode") == "both" and status != "cancelled":
                    retrieval_errors = connection.execute(
                        "SELECT COUNT(*) FROM run_cases WHERE run_id = ? AND error IS NOT NULL",
                        (run_id,),
                    ).fetchone()[0]
                    if retrieval_errors:
                        status = "failed"
            connection.execute(
                "UPDATE evaluation_runs SET status = ?, aggregate_json = ?, finished_at = ? "
                "WHERE id = ?",
                (status, json.dumps(aggregate_data), _now(), run_id),
            )

    def cancel(self, run_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT status FROM evaluation_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if run is None:
                raise RunNotFound(run_id)
            if run["status"] == "queued":
                connection.execute(
                    "UPDATE evaluation_runs SET status = 'cancelled', cancel_requested = 1, "
                    "finished_at = ? WHERE id = ?",
                    (_now(), run_id),
                )
                connection.execute(
                    "UPDATE run_cases SET status = 'cancelled', finished_at = ? "
                    "WHERE run_id = ? AND status = 'pending'",
                    (_now(), run_id),
                )
            elif run["status"] == "running":
                connection.execute(
                    "UPDATE evaluation_runs SET cancel_requested = 1 WHERE id = ?",
                    (run_id,),
                )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT r.id, r.batch_id AS prediction_batch_id, v.dataset_id, "
                "v.version AS dataset_version, r.status, r.config_json, r.model_id, "
                "r.aggregate_json, r.cancel_requested, r.created_at, r.started_at, r.finished_at "
                "FROM evaluation_runs r JOIN prediction_batches b ON b.id = r.batch_id "
                "JOIN dataset_versions v ON v.id = b.dataset_version_id WHERE r.id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise RunNotFound(run_id)
            counts = connection.execute(
                "SELECT status, COUNT(*) AS count FROM run_cases WHERE run_id = ? GROUP BY status",
                (run_id,),
            ).fetchall()
        by_status = {item["status"]: item["count"] for item in counts}
        total = sum(by_status.values())
        return {
            **{
                key: row[key]
                for key in (
                    "id",
                    "prediction_batch_id",
                    "dataset_id",
                    "dataset_version",
                    "status",
                    "model_id",
                    "created_at",
                    "started_at",
                    "finished_at",
                )
            },
            "config": json.loads(row["config_json"]),
            "aggregate": json.loads(row["aggregate_json"]) if row["aggregate_json"] else None,
            "cancel_requested": bool(row["cancel_requested"]),
            "total_count": total,
            "processed_count": total - by_status.get("pending", 0),
            "success_count": by_status.get("success", 0),
            "failed_count": by_status.get("failed", 0),
            "not_applicable_count": by_status.get("not_applicable", 0),
            "cancelled_count": by_status.get("cancelled", 0),
        }

    def list_runs(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id FROM evaluation_runs ORDER BY created_at DESC, id DESC LIMIT 100"
            ).fetchall()
        return [self.get_run(row["id"]) for row in rows]

    def get_cases(
        self, run_id: str, offset: int, limit: int, status: CaseStatus | None = None
    ) -> dict[str, Any]:
        run = self.get_run(run_id)
        with closing(self._connect()) as connection:
            where = "WHERE rc.run_id = ?" + (" AND rc.status = ?" if status else "")
            parameters: tuple[str, ...] = (run_id, status) if status else (run_id,)
            count = connection.execute(
                "SELECT COUNT(*) FROM run_cases rc " + where, parameters
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT rc.case_id, rc.status, rc.error, rc.elapsed_ms, rc.score_json, "
                "c.question, c.reference_answer, c.reference_chunks_json, "
                "p.answer, p.contexts_json, p.latency_ms, pa.attempts_json, "
                "pa.usage_json, pa.elapsed_ms AS target_elapsed_ms "
                "FROM run_cases rc JOIN evaluation_runs r ON r.id = rc.run_id "
                "JOIN prediction_batches b ON b.id = r.batch_id "
                "JOIN evaluation_cases c ON c.version_id = b.dataset_version_id "
                "AND c.case_id = rc.case_id "
                "LEFT JOIN predictions p ON p.batch_id = b.id AND p.case_id = rc.case_id "
                "LEFT JOIN prediction_attempts pa ON pa.batch_id = b.id "
                "AND pa.case_id = rc.case_id "
                f"{where} ORDER BY rc.position LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            ).fetchall()
            metric_rows = connection.execute(
                "SELECT case_id, metric, status, score, reason, raw_response, error, "
                "usage_json, model_name, prompt_version, criteria FROM run_answer_metrics "
                "WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        answer_by_case: dict[str, dict[str, Any]] = {}
        for item in metric_rows:
            answer_by_case.setdefault(item["case_id"], {})[item["metric"]] = {
                **{
                    key: item[key]
                    for key in (
                        "status",
                        "score",
                        "reason",
                        "raw_response",
                        "error",
                        "model_name",
                        "prompt_version",
                        "criteria",
                    )
                },
                "usage": json.loads(item["usage_json"]) if item["usage_json"] else None,
            }
        return {
            "run_id": run_id,
            "total": count if status else run["total_count"],
            "offset": offset,
            "limit": limit,
            "cases": [
                {
                    "case_id": row["case_id"],
                    "status": row["status"],
                    "error": row["error"],
                    "elapsed_ms": row["elapsed_ms"],
                    "score": json.loads(row["score_json"]) if row["score_json"] else None,
                    "answer_metrics": answer_by_case.get(row["case_id"], {}),
                    "question": row["question"],
                    "reference_answer": row["reference_answer"],
                    "reference_chunks": json.loads(row["reference_chunks_json"])
                    if row["reference_chunks_json"]
                    else None,
                    "answer": row["answer"],
                    "contexts": json.loads(row["contexts_json"]) if row["contexts_json"] else None,
                    "target_latency_ms": row["target_elapsed_ms"]
                    if row["target_elapsed_ms"] is not None
                    else row["latency_ms"],
                    "target_attempts": json.loads(row["attempts_json"])
                    if row["attempts_json"] is not None
                    else None,
                    "target_usage": json.loads(row["usage_json"])
                    if row["usage_json"] is not None
                    else None,
                }
                for row in rows
            ],
        }
