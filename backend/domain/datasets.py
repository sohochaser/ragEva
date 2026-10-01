"""Gold case validation shared by imports and future candidate publication."""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

FIELDS = ("case_id", "question", "reference_answer", "reference_chunks")


@dataclass(frozen=True)
class ImportIssue:
    line: int | None
    field: str | None
    code: str
    message: str


@dataclass(frozen=True)
class SourceRow:
    line: int
    values: Mapping[str, Any]


@dataclass(frozen=True)
class ReferenceChunk:
    text: str
    document_id: str


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    question: str
    reference_answer: str | None
    reference_chunks: tuple[ReferenceChunk, ...] | None


def parse_field_mapping(
    raw: str | None, fields: tuple[str, ...] = FIELDS
) -> tuple[dict[str, str], list[ImportIssue]]:
    mapping = {field: field for field in fields}
    if raw is None or not raw.strip():
        return mapping, []
    try:
        supplied = json.loads(raw)
    except json.JSONDecodeError:
        return mapping, [
            ImportIssue(None, "mapping", "invalid_mapping", "字段映射必须是 JSON 对象")
        ]
    if not isinstance(supplied, dict):
        return mapping, [
            ImportIssue(None, "mapping", "invalid_mapping", "字段映射必须是 JSON 对象")
        ]
    issues: list[ImportIssue] = []
    for field, source in supplied.items():
        if field not in fields or not isinstance(source, str) or not source.strip():
            issues.append(
                ImportIssue(None, "mapping", "invalid_mapping", f"无效的字段映射：{field}")
            )
        else:
            mapping[field] = source.strip()
    if len(set(mapping.values())) != len(mapping):
        issues.append(ImportIssue(None, "mapping", "duplicate_mapping", "不同字段不能映射到同一列"))
    return mapping, issues


def _string(
    value: Any, line: int, field: str, required: bool
) -> tuple[str | None, list[ImportIssue]]:
    if value is None or value == "":
        if required:
            return None, [ImportIssue(line, field, "missing_field", f"{field} 不能为空")]
        return None, []
    if not isinstance(value, str):
        return None, [ImportIssue(line, field, "invalid_type", f"{field} 必须是文本")]
    normalized = value.strip()
    if not normalized:
        if required:
            return None, [ImportIssue(line, field, "missing_field", f"{field} 不能为空")]
        return None, []
    return normalized, []


def _chunks(value: Any, line: int) -> tuple[tuple[ReferenceChunk, ...] | None, list[ImportIssue]]:
    if value is None or value == "":
        return None, []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None, [
                ImportIssue(
                    line, "reference_chunks", "invalid_json", "参考 chunk 不是合法的 JSON 数组"
                )
            ]
    if not isinstance(value, list):
        return None, [
            ImportIssue(line, "reference_chunks", "invalid_type", "参考 chunk 必须是数组")
        ]
    if not value:
        return None, [
            ImportIssue(
                line, "reference_chunks", "empty_reference_chunks", "参考 chunk 列表不能为空"
            )
        ]

    chunks: list[ReferenceChunk] = []
    issues: list[ImportIssue] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(value):
        field = f"reference_chunks[{index}]"
        if not isinstance(item, dict):
            issues.append(ImportIssue(line, field, "invalid_type", "参考 chunk 必须是对象"))
            continue
        text, text_issues = _string(item.get("text"), line, f"{field}.text", True)
        document_id, document_issues = _string(
            item.get("document_id"), line, f"{field}.document_id", True
        )
        issues.extend(text_issues)
        issues.extend(document_issues)
        if text is None or document_id is None:
            continue
        key = (document_id, re.sub(r"\s+", " ", text))
        if key in seen:
            issues.append(
                ImportIssue(
                    line, field, "duplicate_reference_chunk", "同一文档中参考 chunk 正文重复"
                )
            )
            continue
        seen.add(key)
        chunks.append(ReferenceChunk(text=text, document_id=document_id))
    return tuple(chunks) if not issues else None, issues


def validate_cases(
    rows: Sequence[SourceRow], mapping: Mapping[str, str]
) -> tuple[list[EvaluationCase], list[ImportIssue]]:
    cases: list[EvaluationCase] = []
    issues: list[ImportIssue] = []
    seen_ids: set[str] = set()
    for row in rows:
        values = row.values
        case_id, case_issues = _string(values.get(mapping["case_id"]), row.line, "case_id", True)
        question, question_issues = _string(
            values.get(mapping["question"]), row.line, "question", True
        )
        answer, answer_issues = _string(
            values.get(mapping["reference_answer"]), row.line, "reference_answer", False
        )
        chunks, chunk_issues = _chunks(values.get(mapping["reference_chunks"]), row.line)
        row_issues = case_issues + question_issues + answer_issues + chunk_issues
        if case_id is not None:
            if case_id in seen_ids:
                row_issues.append(
                    ImportIssue(row.line, "case_id", "duplicate_case_id", f"case_id {case_id} 重复")
                )
            seen_ids.add(case_id)
        if answer is None and chunks is None:
            row_issues.append(
                ImportIssue(row.line, None, "missing_annotation", "需要标准答案或参考 chunk")
            )
        issues.extend(row_issues)
        if not row_issues and case_id is not None and question is not None:
            cases.append(EvaluationCase(case_id, question, answer, chunks))
    if not rows and not issues:
        issues.append(ImportIssue(None, None, "empty_file", "文件中没有样本"))
    return cases, issues
