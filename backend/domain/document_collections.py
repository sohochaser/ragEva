"""Validation and deterministic chunking for immutable source documents."""

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True)
class DocumentIssue:
    file_index: int | None
    filename: str | None
    field: str
    code: str
    message: str


@dataclass(frozen=True)
class SourceDocument:
    filename: str
    document_id: str
    content: bytes
    checksum: str
    chunks: tuple[str, ...]


class DocumentTextError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def validate_documents(
    uploads: list[tuple[str, bytes]],
    document_ids: list[str | None] | None,
    chunk_size: int,
    chunk_overlap: int,
    extract_binary_text: Callable[[str, bytes], str] | None = None,
) -> tuple[list[SourceDocument], list[DocumentIssue]]:
    issues: list[DocumentIssue] = []
    if not uploads:
        issues.append(DocumentIssue(None, None, "files", "missing_files", "至少上传一个文件"))
    if chunk_size < 1 or chunk_size > 10000:
        issues.append(
            DocumentIssue(None, None, "chunk_size", "invalid_chunk_size", "切块大小须为 1–10000")
        )
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        issues.append(
            DocumentIssue(
                None,
                None,
                "chunk_overlap",
                "invalid_chunk_overlap",
                "重叠量须小于切块大小且不能为负数",
            )
        )
    if document_ids is not None and len(document_ids) != len(uploads):
        issues.append(
            DocumentIssue(
                None, None, "document_ids", "invalid_document_ids", "文档 ID 数量须与文件数量一致"
            )
        )
    if issues:
        return [], issues

    documents: list[SourceDocument] = []
    used_ids: set[str] = set()
    reserved_ids = {value.strip() for value in document_ids or [] if value is not None}
    generated_counts: dict[str, int] = {}
    for index, (raw_name, content) in enumerate(uploads):
        filename = Path(raw_name).name
        supplied_id = document_ids[index] if document_ids is not None else None
        if supplied_id is None:
            base = Path(filename).stem.strip()
            generated_counts[base] = generated_counts.get(base, 0) + 1
            document_id = f"{base}-{generated_counts[base]}"
            while document_id in used_ids or document_id in reserved_ids:
                generated_counts[base] += 1
                document_id = f"{base}-{generated_counts[base]}"
        else:
            document_id = supplied_id.strip()
        if not document_id:
            issues.append(
                DocumentIssue(
                    index, filename, "document_id", "empty_document_id", "文档 ID 不能为空"
                )
            )
        elif document_id in used_ids:
            issues.append(
                DocumentIssue(
                    index, filename, "document_id", "duplicate_document_id", "文档 ID 重复"
                )
            )
        else:
            used_ids.add(document_id)
        suffix = Path(filename).suffix.lower()
        if suffix not in {".txt", ".md", ".markdown", ".docx", ".pdf"}:
            issues.append(
                DocumentIssue(
                    index,
                    filename,
                    "file",
                    "unsupported_format",
                    "仅支持 TXT、Markdown、DOCX 或文本 PDF",
                )
            )
            continue
        if not content:
            issues.append(DocumentIssue(index, filename, "file", "empty_file", "文件不能为空"))
            continue
        if suffix in {".docx", ".pdf"}:
            if extract_binary_text is None:
                raise ValueError("binary text extractor is required for DOCX/PDF")
            try:
                text = extract_binary_text(filename, content)
            except DocumentTextError as exc:
                issues.append(DocumentIssue(index, filename, "file", exc.code, exc.message))
                continue
        else:
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                issues.append(
                    DocumentIssue(
                        index, filename, "file", "invalid_encoding", "文件必须使用 UTF-8 编码"
                    )
                )
                continue
        if not text.strip():
            issues.append(DocumentIssue(index, filename, "file", "empty_file", "文件没有可用文本"))
            continue
        chunks_list: list[str] = []
        start = 0
        while start < len(text):
            chunks_list.append(text[start : start + chunk_size])
            if start + chunk_size >= len(text):
                break
            start += chunk_size - chunk_overlap
        documents.append(
            SourceDocument(
                filename, document_id, content, sha256(content).hexdigest(), tuple(chunks_list)
            )
        )
    return ([], issues) if issues else (documents, [])
