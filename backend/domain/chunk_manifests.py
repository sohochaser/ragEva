"""Validation for ordered, chunk-only collection imports."""

import re
from dataclasses import dataclass

from backend.domain.datasets import ImportIssue, SourceRow


@dataclass(frozen=True)
class ManifestChunk:
    position: int
    document_id: str
    text: str


def validate_manifest(rows: list[SourceRow]) -> tuple[list[ManifestChunk], list[ImportIssue]]:
    if not rows:
        return [], [ImportIssue(None, "file", "empty_manifest", "清单至少需要一个 chunk")]

    chunks: list[ManifestChunk] = []
    issues: list[ImportIssue] = []
    seen: set[tuple[str, str]] = set()
    for expected, row in enumerate(rows):
        raw_position = row.values.get("position")
        if isinstance(raw_position, bool):
            position = None
        elif isinstance(raw_position, int):
            position = raw_position
        elif isinstance(raw_position, str) and raw_position.strip().isdecimal():
            position = int(raw_position.strip())
        else:
            position = None
        if position is None:
            issues.append(
                ImportIssue(row.line, "position", "invalid_position", "position 须为非负整数")
            )
        elif position != expected:
            issues.append(
                ImportIssue(row.line, "position", "invalid_order", f"position 应为 {expected}")
            )

        raw_id = row.values.get("document_id")
        document_id = raw_id.strip() if isinstance(raw_id, str) else ""
        if not document_id:
            issues.append(
                ImportIssue(row.line, "document_id", "missing_document_id", "document_id 不能为空")
            )

        raw_text = row.values.get("text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            issues.append(ImportIssue(row.line, "text", "missing_text", "chunk 正文不能为空"))
            continue
        if not document_id:
            continue
        key = (document_id, re.sub(r"\s+", " ", raw_text.strip()))
        if key in seen:
            issues.append(
                ImportIssue(row.line, "text", "duplicate_chunk", "同一文档中 chunk 正文重复")
            )
        seen.add(key)
        if position is not None:
            chunks.append(ManifestChunk(position, document_id, raw_text))
    return ([], issues) if issues else (chunks, [])
