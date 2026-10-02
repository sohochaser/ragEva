"""Immutable source document collection API."""

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.adapters.dataset_files import read_rows
from backend.adapters.document_store import CollectionNotFound, DocumentStore
from backend.adapters.document_text import extract_document_text
from backend.config import Settings
from backend.domain.chunk_manifests import validate_manifest
from backend.domain.datasets import ImportIssue
from backend.domain.document_collections import DocumentIssue, validate_documents

MAX_FILE_BYTES = 25 * 1024 * 1024


class DocumentIssueResponse(BaseModel):
    file_index: int | None
    filename: str | None
    field: str
    code: str
    message: str


class CollectionImportFailure(BaseModel):
    error: str
    issues: list[DocumentIssueResponse]


class SourceChunkResponse(BaseModel):
    position: int
    text: str


class SourceDocumentResponse(BaseModel):
    filename: str | None
    document_id: str
    checksum: str | None
    byte_count: int | None
    has_original_file: bool
    chunks: list[SourceChunkResponse]


class CollectionChunkResponse(SourceChunkResponse):
    document_id: str


class ChunkImportIssueResponse(BaseModel):
    line: int | None
    field: str | None
    code: str
    message: str


class ChunkImportFailure(BaseModel):
    error: str
    issues: list[ChunkImportIssueResponse]


class CollectionSummary(BaseModel):
    id: str
    name: str
    source_kind: str
    chunk_size: int
    chunk_overlap: int
    created_at: str
    document_count: int


class CollectionDetail(CollectionSummary):
    documents: list[SourceDocumentResponse]
    chunks: list[CollectionChunkResponse]


def _failure(issues: list[DocumentIssue]) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=CollectionImportFailure(
            error="validation_failed",
            issues=[DocumentIssueResponse(**vars(issue)) for issue in issues],
        ).model_dump(),
    )


def _chunk_failure(issues: list[ImportIssue]) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=ChunkImportFailure(
            error="validation_failed",
            issues=[ChunkImportIssueResponse(**vars(issue)) for issue in issues],
        ).model_dump(),
    )


def create_document_collection_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/document-collections", tags=["document-collections"])
    store = DocumentStore(settings.data_dir)

    @router.post(
        "",
        response_model=CollectionDetail,
        status_code=201,
        responses={422: {"model": CollectionImportFailure}},
    )
    async def create_collection(
        files: Annotated[list[UploadFile], File()],
        name: Annotated[str, Form()],
        chunk_size: Annotated[int, Form()] = 1000,
        chunk_overlap: Annotated[int, Form()] = 100,
        document_ids: Annotated[str | None, Form()] = None,
    ) -> CollectionDetail | JSONResponse:
        issues: list[DocumentIssue] = []
        if not name.strip():
            issues.append(DocumentIssue(None, None, "name", "empty_name", "集合名称不能为空"))
        if len(name.strip()) > 120:
            issues.append(
                DocumentIssue(None, None, "name", "name_too_long", "集合名称不得超过 120 字符")
            )
        parsed_ids: list[str | None] | None = None
        if document_ids is not None:
            try:
                value = json.loads(document_ids)
                if not isinstance(value, list) or any(
                    item is not None and not isinstance(item, str) for item in value
                ):
                    raise ValueError
                parsed_ids = value
            except (ValueError, json.JSONDecodeError):
                issues.append(
                    DocumentIssue(
                        None,
                        None,
                        "document_ids",
                        "invalid_document_ids",
                        "文档 ID 须为文本或 null 的 JSON 列表",
                    )
                )
        if issues:
            return _failure(issues)
        uploads: list[tuple[str, bytes]] = []
        for index, file in enumerate(files):
            content = await file.read(MAX_FILE_BYTES + 1)
            if len(content) > MAX_FILE_BYTES:
                issues.append(
                    DocumentIssue(
                        index,
                        Path(file.filename or "").name,
                        "file",
                        "file_too_large",
                        "单个文件不得超过 25 MiB",
                    )
                )
            uploads.append((file.filename or "", content))
        if issues:
            return _failure(issues)
        documents, issues = validate_documents(
            uploads, parsed_ids, chunk_size, chunk_overlap, extract_document_text
        )
        if issues:
            return _failure(issues)
        return CollectionDetail(**store.create(name.strip(), documents, chunk_size, chunk_overlap))

    @router.post(
        "/import-chunks",
        response_model=CollectionDetail,
        status_code=201,
        responses={422: {"model": ChunkImportFailure}},
    )
    async def import_chunks(
        file: Annotated[UploadFile, File()], name: Annotated[str, Form()]
    ) -> CollectionDetail | JSONResponse:
        if not name.strip() or len(name.strip()) > 120:
            return _chunk_failure(
                [ImportIssue(None, "name", "invalid_name", "集合名称须为 1–120 字符")]
            )
        content = await file.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            return _chunk_failure(
                [ImportIssue(None, "file", "file_too_large", "文件不得超过 25 MiB")]
            )
        filename = Path(file.filename or "").name
        fields = {field: field for field in ("position", "document_id", "text")}
        rows, file_issues = read_rows(filename, content, fields, set(fields), tuple(fields))
        chunks, chunk_issues = validate_manifest(rows) if rows else ([], [])
        issues = file_issues + chunk_issues
        if not rows and not file_issues:
            issues.append(ImportIssue(None, "file", "empty_manifest", "清单至少需要一个 chunk"))
        if issues:
            return _chunk_failure(issues)
        return CollectionDetail(**store.create_from_chunks(name.strip(), chunks))

    @router.get("", response_model=list[CollectionSummary])
    def list_collections() -> list[CollectionSummary]:
        return [CollectionSummary(**item) for item in store.list()]

    @router.get("/{collection_id}", response_model=CollectionDetail)
    def get_collection(collection_id: str) -> CollectionDetail:
        try:
            return CollectionDetail(**store.get(collection_id))
        except CollectionNotFound as exc:
            raise HTTPException(status_code=404, detail="文档集合不存在") from exc

    return router
