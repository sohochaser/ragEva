"""Local, request-scoped span summaries for diagnosis without a Jaeger dependency."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import StatusCode

SCHEMA = """
CREATE TABLE IF NOT EXISTS request_log_spans (
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    parent_span_id TEXT,
    name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    duration_ms REAL NOT NULL,
    status TEXT NOT NULL,
    error_code TEXT,
    error_detail TEXT,
    attributes_json TEXT NOT NULL,
    PRIMARY KEY (trace_id, span_id)
);
CREATE INDEX IF NOT EXISTS request_log_spans_recent
    ON request_log_spans(name, started_at DESC);
"""

_DETAILS = {
    "call_error": "目标调用失败",
    "collection_error": "目标采集失败",
    "connection_error": "连接失败",
    "generation_error": "候选生成失败",
    "generation_worker_error": "生成任务处理失败",
    "invalid_content_type": "响应类型不符合目标协议",
    "invalid_json": "响应不是有效 JSON",
    "invalid_score": "评分结果无效",
    "metric_failed": "指标评分失败",
    "missing_answer": "目标响应缺少答案",
    "missing_completed": "流式响应未正常结束",
    "missing_contexts": "目标响应缺少检索片段",
    "missing_generation_dependency": "生成任务依赖已不存在",
    "model_error": "模型调用失败",
    "model_unavailable": "模型不可用",
    "operation_error": "处理请求时出错",
    "scoring_error": "评分失败",
    "timeout": "调用超时",
}


class RequestLogStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "rageva.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=30)) as connection:
            connection.executescript(SCHEMA)

    def record_span(self, span: ReadableSpan, allowed_attributes: frozenset[str]) -> None:
        context = span.context
        if (
            context is None
            or not context.is_valid
            or span.start_time is None
            or span.end_time is None
        ):
            return
        values = {
            key: value
            for key, value in (span.attributes or {}).items()
            if key in allowed_attributes
        }
        error_code = values.get("error.code")
        detail = _DETAILS.get(error_code, "步骤执行失败") if error_code else None
        if error_code and error_code.startswith("http_"):
            detail = f"HTTP {error_code[5:]} 请求失败"
        if error_code and error_code.startswith("stream_"):
            detail = "流式响应失败"
        error_type = values.get("error.type")
        if detail and error_type:
            detail = f"{detail}（{error_type}）"
        parent_id = span.parent.span_id if span.parent and span.parent.is_valid else None
        with closing(sqlite3.connect(self.path, timeout=30)) as connection, connection:
            connection.execute(
                "INSERT OR IGNORE INTO request_log_spans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{context.trace_id:032x}",
                    f"{context.span_id:016x}",
                    f"{parent_id:016x}" if parent_id is not None else None,
                    span.name,
                    datetime.fromtimestamp(span.start_time / 1e9, UTC).isoformat(),
                    round((span.end_time - span.start_time) / 1e6, 3),
                    "failed" if span.status.status_code == StatusCode.ERROR else "success",
                    error_code,
                    detail,
                    json.dumps(values, ensure_ascii=False),
                ),
            )

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.path, timeout=30)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT r.trace_id, r.started_at, r.status, r.error_code, r.attributes_json, "
                "EXISTS(SELECT 1 FROM request_log_spans s WHERE s.trace_id = r.trace_id "
                "AND s.status = 'failed') AS has_errors "
                "FROM request_log_spans r WHERE r.name = 'http.request' "
                "ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._request(row) for row in rows]

    def get(self, trace_id: str) -> dict[str, Any] | None:
        with closing(sqlite3.connect(self.path, timeout=30)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM request_log_spans WHERE trace_id = ? ORDER BY started_at, span_id",
                (trace_id,),
            ).fetchall()
        root = next((row for row in rows if row["name"] == "http.request"), None)
        if root is None:
            return None
        request = self._request(root)
        request["status"] = (
            "failed" if any(row["status"] == "failed" for row in rows) else "success"
        )
        request["spans"] = [
            {
                "span_id": row["span_id"],
                "parent_span_id": row["parent_span_id"],
                "name": row["name"],
                "started_at": row["started_at"],
                "duration_ms": row["duration_ms"],
                "status": row["status"],
                "error_code": row["error_code"],
                "error_detail": row["error_detail"],
                "attributes": json.loads(row["attributes_json"]),
            }
            for row in rows
        ]
        return request

    @staticmethod
    def _request(row: sqlite3.Row) -> dict[str, Any]:
        values = json.loads(row["attributes_json"])
        return {
            "request_id": row["trace_id"],
            "started_at": row["started_at"],
            "method": values.get("http.method", ""),
            "route": values.get("http.route", ""),
            "http_status": values.get("http.status_code", 0),
            "status": "failed"
            if "has_errors" in row.keys() and row["has_errors"]
            else row["status"],
            "error_code": row["error_code"],
        }
