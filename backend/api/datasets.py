"""Gold dataset import and read-only version API."""

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.adapters.dataset_files import read_rows
from backend.adapters.dataset_store import DatasetNotFound, DatasetStore
from backend.adapters.trace_store import TraceStore
from backend.config import Settings
from backend.domain.datasets import ImportIssue, parse_field_mapping, validate_cases
from backend.tracing import attributes, business_span

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class ImportIssueResponse(BaseModel):
    line: int | None
    field: str | None
    code: str
    message: str


class ImportFailure(BaseModel):
    error: str
    issues: list[ImportIssueResponse]


class ReferenceChunkResponse(BaseModel):
    text: str
    document_id: str


class CaseResponse(BaseModel):
    case_id: str
    question: str
    reference_answer: str | None
    reference_chunks: list[ReferenceChunkResponse] | None


class DatasetSummary(BaseModel):
    id: str
    name: str
    created_at: str
    version_count: int
    latest_version: int
    latest_case_count: int


class VersionSummary(BaseModel):
    id: str
    dataset_id: str
    version: int
    case_count: int
    source_filename: str
    created_at: str
    source_collection_ids: list[str] = Field(default_factory=list)


class VersionDetail(VersionSummary):
    total: int
    offset: int
    limit: int
    cases: list[CaseResponse]


def _failure(issues: list[ImportIssue]) -> JSONResponse:
    body = ImportFailure(
        error="validation_failed",
        issues=[ImportIssueResponse(**vars(issue)) for issue in issues],
    )
    return JSONResponse(status_code=422, content=body.model_dump())


def create_dataset_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"])
    store = DatasetStore(settings.data_dir)
    traces = TraceStore(settings.data_dir)

    @router.post(
        "/import",
        response_model=VersionSummary,
        status_code=201,
        responses={422: {"model": ImportFailure}},
    )
    async def import_dataset(
        file: Annotated[UploadFile, File()],
        dataset_name: Annotated[str | None, Form()] = None,
        dataset_id: Annotated[str | None, Form()] = None,
        mapping: Annotated[str | None, Form()] = None,
    ) -> VersionSummary | JSONResponse:
        name = dataset_name.strip() if dataset_name else None
        target_id = dataset_id.strip() if dataset_id else None
        if target_id is None and not name:
            return _failure(
                [ImportIssue(None, "dataset_name", "missing_field", "新建数据集需要名称")]
            )
        filename = Path(file.filename or "").name
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            return _failure([ImportIssue(None, "file", "file_too_large", "文件不得超过 25 MiB")])
        fields, mapping_issues = parse_field_mapping(mapping)
        if mapping_issues:
            return _failure(mapping_issues)
        explicit_fields: set[str] = set()
        if mapping:
            explicit_fields = set(json.loads(mapping))
        rows, file_issues = read_rows(filename, content, fields, explicit_fields)
        if file_issues and not rows:
            return _failure(file_issues)
        cases, case_issues = validate_cases(rows, fields)
        issues = file_issues + case_issues
        if issues:
            return _failure(issues)
        try:
            with business_span("dataset.import") as span:
                summary = store.import_cases(name, target_id, filename, cases)
                attributes(span, **{"dataset.id": summary["dataset_id"], "count": len(cases)})
                traces.record("dataset_version", summary["id"], span)
        except DatasetNotFound as exc:
            raise HTTPException(status_code=404, detail="数据集不存在") from exc
        return VersionSummary(**summary)

    @router.get("", response_model=list[DatasetSummary])
    def list_datasets() -> list[DatasetSummary]:
        return [DatasetSummary(**item) for item in store.list_datasets()]

    @router.get("/{dataset_id}/versions", response_model=list[VersionSummary])
    def list_versions(dataset_id: str) -> list[VersionSummary]:
        try:
            return [VersionSummary(**item) for item in store.list_versions(dataset_id)]
        except DatasetNotFound as exc:
            raise HTTPException(status_code=404, detail="数据集不存在") from exc

    @router.get("/{dataset_id}/versions/{version}", response_model=VersionDetail)
    def get_version(
        dataset_id: str,
        version: int,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
    ) -> VersionDetail:
        try:
            return VersionDetail(**store.get_version(dataset_id, version, offset, limit))
        except DatasetNotFound as exc:
            raise HTTPException(status_code=404, detail="数据集版本不存在") from exc

    @router.get("/{dataset_id}/versions/{version}/cases/{case_id}", response_model=CaseResponse)
    def get_case(dataset_id: str, version: int, case_id: str) -> CaseResponse:
        try:
            return CaseResponse(**store.get_case(dataset_id, version, case_id))
        except DatasetNotFound as exc:
            raise HTTPException(status_code=404, detail="样本不存在") from exc

    return router
