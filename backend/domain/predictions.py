"""Canonical saved predictions from files and future HTTP adapters."""

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from backend.domain.datasets import ImportIssue, SourceRow, _string

PREDICTION_FIELDS = ("case_id", "answer", "contexts", "latency_ms")
EvaluationType = Literal["answer", "retrieval", "both"]


@dataclass(frozen=True)
class PredictedChunk:
    text: str
    document_id: str
    chunk_id: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class Prediction:
    case_id: str
    answer: str | None
    contexts: tuple[PredictedChunk, ...] | None
    latency_ms: float | None


def _contexts(value: Any, line: int) -> tuple[tuple[PredictedChunk, ...] | None, list[ImportIssue]]:
    if value is None or value == "":
        return None, []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None, [
                ImportIssue(line, "contexts", "invalid_json", "预测 chunk 不是合法的 JSON 数组")
            ]
    if not isinstance(value, list):
        return None, [ImportIssue(line, "contexts", "invalid_type", "预测 chunk 必须是数组")]
    if not value:
        return None, [ImportIssue(line, "contexts", "empty_contexts", "预测 chunk 列表不能为空")]
    chunks: list[PredictedChunk] = []
    issues: list[ImportIssue] = []
    for index, item in enumerate(value):
        field = f"contexts[{index}]"
        if not isinstance(item, dict):
            issues.append(ImportIssue(line, field, "invalid_type", "预测 chunk 必须是对象"))
            continue
        text, text_issues = _string(item.get("text"), line, f"{field}.text", True)
        document_id, document_issues = _string(
            item.get("document_id"), line, f"{field}.document_id", True
        )
        chunk_id, chunk_id_issues = _string(item.get("chunk_id"), line, f"{field}.chunk_id", False)
        source, source_issues = _string(item.get("source"), line, f"{field}.source", False)
        issues.extend(text_issues + document_issues + chunk_id_issues + source_issues)
        if text is not None and document_id is not None:
            chunks.append(PredictedChunk(text, document_id, chunk_id, source))
    return tuple(chunks) if not issues else None, issues


def _latency(value: Any, line: int) -> tuple[float | None, list[ImportIssue]]:
    if value is None or value == "":
        return None, []
    if isinstance(value, bool):
        return None, [ImportIssue(line, "latency_ms", "invalid_type", "耗时必须是非负数")]
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None, [ImportIssue(line, "latency_ms", "invalid_type", "耗时必须是非负数")]
    if not math.isfinite(number) or number < 0:
        return None, [ImportIssue(line, "latency_ms", "invalid_type", "耗时必须是非负数")]
    return number, []


def validate_predictions(
    rows: Sequence[SourceRow],
    mapping: Mapping[str, str],
    evaluation_type: EvaluationType,
    known_case_ids: set[str] | None,
) -> tuple[list[Prediction], list[ImportIssue]]:
    predictions: list[Prediction] = []
    issues: list[ImportIssue] = []
    seen: set[str] = set()
    for row in rows:
        case_id, id_issues = _string(row.values.get(mapping["case_id"]), row.line, "case_id", True)
        answer, answer_issues = _string(
            row.values.get(mapping["answer"]), row.line, "answer", False
        )
        contexts, context_issues = _contexts(row.values.get(mapping["contexts"]), row.line)
        latency_ms, latency_issues = _latency(row.values.get(mapping["latency_ms"]), row.line)
        row_issues = id_issues + answer_issues + context_issues + latency_issues
        if case_id is not None:
            if case_id in seen:
                row_issues.append(
                    ImportIssue(row.line, "case_id", "duplicate_case_id", f"case_id {case_id} 重复")
                )
            if known_case_ids is not None and case_id not in known_case_ids:
                row_issues.append(
                    ImportIssue(
                        row.line,
                        "case_id",
                        "unknown_case_id",
                        f"case_id {case_id} 不在数据集版本中",
                    )
                )
            seen.add(case_id)
        if evaluation_type in {"answer", "both"} and answer is None:
            row_issues.append(
                ImportIssue(row.line, "answer", "missing_answer", "回答评测需要预测答案")
            )
        if evaluation_type in {"retrieval", "both"} and contexts is None and not context_issues:
            row_issues.append(
                ImportIssue(row.line, "contexts", "missing_contexts", "检索评测需要预测 chunk")
            )
        issues.extend(row_issues)
        if not row_issues and case_id is not None:
            predictions.append(Prediction(case_id, answer, contexts, latency_ms))
    if not rows and not issues:
        issues.append(ImportIssue(None, None, "empty_file", "文件中没有预测记录"))
    return predictions, issues
