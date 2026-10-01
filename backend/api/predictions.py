"""Import and browse immutable prediction batches."""

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.adapters.dataset_files import read_rows
from backend.adapters.dataset_store import DatasetNotFound
from backend.adapters.prediction_store import PredictionNotFound, PredictionStore
from backend.api.datasets import ImportFailure, _failure
from backend.config import Settings
from backend.domain.datasets import FIELDS, ImportIssue, parse_field_mapping, validate_cases
from backend.domain.predictions import PREDICTION_FIELDS, EvaluationType, validate_predictions

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALL_FIELDS = tuple(dict.fromkeys((*FIELDS, *PREDICTION_FIELDS)))


class PredictedChunkResponse(BaseModel):
    text: str
    document_id: str
    chunk_id: str | None
    source: str | None


class PredictionResponse(BaseModel):
    case_id: str
    answer: str | None
    contexts: list[PredictedChunkResponse] | None
    latency_ms: float | None


class PredictionBatchSummary(BaseModel):
    id: str
    dataset_id: str
    dataset_version: int
    evaluation_type: EvaluationType
    source_filename: str
    created_at: str
    record_count: int
    matched_count: int
    missing_case_count: int


class PredictionBatchDetail(PredictionBatchSummary):
    offset: int
    limit: int
    predictions: list[PredictionResponse]


def create_prediction_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/predictions", tags=["predictions"])
    store = PredictionStore(settings.data_dir)

    @router.post(
        "/import",
        response_model=PredictionBatchSummary,
        status_code=201,
        responses={422: {"model": ImportFailure}},
    )
    async def import_predictions(
        file: Annotated[UploadFile, File()],
        evaluation_type: Annotated[EvaluationType, Form()],
        dataset_id: Annotated[str | None, Form()] = None,
        dataset_version: Annotated[int | None, Form()] = None,
        dataset_name: Annotated[str | None, Form()] = None,
        mapping: Annotated[str | None, Form()] = None,
    ) -> PredictionBatchSummary | JSONResponse:
        target_id = dataset_id.strip() if dataset_id else None
        name = dataset_name.strip() if dataset_name else None
        if bool(target_id) == bool(name):
            return _failure(
                [
                    ImportIssue(
                        None, "dataset", "invalid_target", "请选择已有数据集或填写新数据集名称"
                    )
                ]
            )
        if name and dataset_version is not None:
            return _failure(
                [ImportIssue(None, "dataset_version", "invalid_target", "新建数据集不能指定版本")]
            )
        filename = Path(file.filename or "").name
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            return _failure([ImportIssue(None, "file", "file_too_large", "文件不得超过 25 MiB")])
        fields, mapping_issues = parse_field_mapping(mapping, ALL_FIELDS)
        if mapping_issues:
            return _failure(mapping_issues)
        explicit_fields = set(json.loads(mapping)) if mapping else set()
        required_columns = ("case_id", "question") if name else ("case_id",)
        rows, file_issues = read_rows(filename, content, fields, explicit_fields, required_columns)
        if file_issues and not rows:
            return _failure(file_issues)
        try:
            resolved_version, known_ids = (
                store.resolve_version(target_id, dataset_version) if target_id else (None, None)
            )
        except DatasetNotFound as exc:
            raise HTTPException(status_code=404, detail="数据集版本不存在") from exc
        cases, case_issues = validate_cases(rows, fields) if name else (None, [])
        if cases is not None:
            known_ids = {case.case_id for case in cases}
        predictions, prediction_issues = validate_predictions(
            rows, fields, evaluation_type, known_ids
        )
        issues = file_issues + case_issues + prediction_issues
        if issues:
            return _failure(issues)
        try:
            summary = store.import_batch(
                target_id, resolved_version, name, filename, evaluation_type, predictions, cases
            )
        except DatasetNotFound as exc:
            raise HTTPException(status_code=404, detail="数据集版本不存在") from exc
        return PredictionBatchSummary(**summary)

    @router.get("", response_model=list[PredictionBatchSummary])
    def list_batches() -> list[PredictionBatchSummary]:
        return [PredictionBatchSummary(**item) for item in store.list_batches()]

    @router.get("/{batch_id}", response_model=PredictionBatchDetail)
    def get_batch(
        batch_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
    ) -> PredictionBatchDetail:
        try:
            return PredictionBatchDetail(**store.get_batch(batch_id, offset, limit))
        except PredictionNotFound as exc:
            raise HTTPException(status_code=404, detail="预测批次不存在") from exc

    return router
