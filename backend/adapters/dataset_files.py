"""CSV and JSONL readers for gold cases."""

import csv
import io
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from backend.domain.datasets import ImportIssue, SourceRow


def read_rows(
    filename: str, content: bytes, mapping: Mapping[str, str], explicit_fields: set[str]
) -> tuple[list[SourceRow], list[ImportIssue]]:
    extension = Path(filename).suffix.lower()
    if extension not in {".csv", ".jsonl"}:
        return [], [ImportIssue(None, "file", "invalid_format", "仅支持 CSV 或 JSONL 文件")]
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], [ImportIssue(None, "file", "invalid_encoding", "文件必须使用 UTF-8 编码")]
    if extension == ".jsonl":
        return _read_jsonl(text)
    return _read_csv(text, mapping, explicit_fields)


def _read_jsonl(text: str) -> tuple[list[SourceRow], list[ImportIssue]]:
    rows: list[SourceRow] = []
    issues: list[ImportIssue] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value: Any = json.loads(line)
        except json.JSONDecodeError:
            issues.append(ImportIssue(line_number, None, "invalid_json", "该行不是合法 JSON"))
            continue
        if not isinstance(value, dict):
            issues.append(ImportIssue(line_number, None, "invalid_type", "每行必须是 JSON 对象"))
            continue
        rows.append(SourceRow(line_number, value))
    return rows, issues


def _read_csv(
    text: str, mapping: Mapping[str, str], explicit_fields: set[str]
) -> tuple[list[SourceRow], list[ImportIssue]]:
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    try:
        header = reader.fieldnames
        if header is None:
            return [], [ImportIssue(None, "file", "empty_file", "文件中没有样本")]
        if len(header) != len(set(header)):
            return [], [ImportIssue(1, None, "duplicate_column", "CSV 表头列名重复")]
        missing = [
            field
            for field in ("case_id", "question", *sorted(explicit_fields))
            if mapping[field] not in header
        ]
        if missing:
            return [], [
                ImportIssue(1, field, "missing_column", f"缺少映射列 {mapping[field]}")
                for field in dict.fromkeys(missing)
            ]
        rows: list[SourceRow] = []
        issues: list[ImportIssue] = []
        for line_number, value in enumerate(reader, start=2):
            if None in value:
                issues.append(ImportIssue(line_number, None, "invalid_csv", "CSV 行的列数多于表头"))
            else:
                rows.append(SourceRow(line_number, value))
        return rows, issues
    except csv.Error:
        return [], [ImportIssue(reader.line_num or None, None, "invalid_csv", "CSV 格式不合法")]
