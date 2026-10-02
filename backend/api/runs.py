"""Asynchronous retrieval runs and durable result access."""

import csv
import io
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator

from backend.adapters.run_store import RunInputError, RunNotFound, RunStore
from backend.api.matching import ChunkInput, KScoreResponse
from backend.api.predictions import PredictedChunkResponse
from backend.config import Settings
from backend.domain.runs import CaseStatus, MetricKey
from backend.health import worker_is_ready
from backend.worker.queue import score_run_task


class RunCreate(BaseModel):
    prediction_batch_id: str = Field(min_length=1)
    model_name: str = Field(default="BAAI/bge-small-zh-v1.5", min_length=1)
    model_path: str | None = None
    offline: bool = False
    threshold: float = Field(default=0.8, ge=-1, le=1)
    metrics: list[MetricKey] = Field(default_factory=lambda: default_metrics())

    @field_validator("metrics")
    @classmethod
    def validate_metrics(cls, value: list[MetricKey]) -> list[MetricKey]:
        if not value or len(set(value)) != len(value):
            raise ValueError("至少选择一个不重复的检索指标")
        return value


def default_metrics() -> list[MetricKey]:
    return ["precision", "map", "ndcg"]


class RunSummary(BaseModel):
    id: str
    prediction_batch_id: str
    dataset_id: str
    dataset_version: int
    status: str
    config: dict[str, Any]
    model_id: str | None
    aggregate: "RunAggregate | None"
    cancel_requested: bool
    total_count: int
    processed_count: int
    success_count: int
    failed_count: int
    not_applicable_count: int
    cancelled_count: int
    created_at: str
    started_at: str | None
    finished_at: str | None


class RunCasesPage(BaseModel):
    run_id: str
    total: int
    offset: int
    limit: int
    cases: list["RunCaseResponse"]


class RunAggregate(BaseModel):
    valid_count: int
    not_applicable_count: int
    precision_at_k: dict[str, float | None]
    map_at_k: dict[str, float | None]
    ndcg_at_k: dict[str, float | None]
    distribution: dict[str, dict[str, list[int]]] = Field(default_factory=dict)


class RetrievalScoreResponse(BaseModel):
    model_id: str
    threshold: float
    match_rule_version: str
    gain_rule_version: str
    scores: dict[str, KScoreResponse]


class RunCaseResponse(BaseModel):
    case_id: str
    status: CaseStatus
    error: str | None
    elapsed_ms: float | None
    score: RetrievalScoreResponse | None
    question: str
    reference_answer: str | None
    reference_chunks: list[ChunkInput] | None
    answer: str | None
    contexts: list[PredictedChunkResponse] | None
    target_latency_ms: float | None
    target_attempts: list[dict[str, Any]] | None = None
    target_usage: dict[str, int] | None = None


def create_run_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/runs", tags=["runs"])
    store = RunStore(settings.data_dir)

    @router.post("", status_code=202, response_model=RunSummary)
    def create(request: RunCreate) -> dict[str, Any]:
        if not worker_is_ready(settings.data_dir, settings.worker_stale_after):
            raise HTTPException(status_code=503, detail="Worker 不可用")
        try:
            model_path = (
                str(Path(request.model_path).expanduser().resolve()) if request.model_path else None
            )
            result = store.create_run(
                request.prediction_batch_id,
                request.model_name,
                model_path,
                request.offline,
                request.threshold,
                request.metrics,
            )
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="预测批次不存在") from exc
        except RunInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        score_run_task(result["id"])
        return result

    @router.get("", response_model=list[RunSummary])
    def list_runs() -> list[dict[str, Any]]:
        return store.list_runs()

    @router.get("/{run_id}", response_model=RunSummary)
    def get_run(run_id: str) -> dict[str, Any]:
        try:
            return store.get_run(run_id)
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="评测运行不存在") from exc

    @router.get("/{run_id}/cases", response_model=RunCasesPage)
    def get_cases(
        run_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=1000),
        status: CaseStatus | None = None,
    ) -> dict[str, Any]:
        try:
            return store.get_cases(run_id, offset, limit, status)
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="评测运行不存在") from exc

    @router.get("/{run_id}/export")
    def export(
        run_id: str,
        format: Literal["json", "csv"] = "json",
        status: CaseStatus | None = None,
    ) -> Response:
        try:
            run = store.get_run(run_id)
            cases: list[dict[str, Any]] = []
            while True:
                page = store.get_cases(run_id, len(cases), 1000, status)
                cases.extend(page["cases"])
                if len(cases) >= page["total"]:
                    break
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="评测运行不存在") from exc
        filename = f"rageva-{run_id}.{format}"
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        if format == "json":
            return Response(
                content=json.dumps({"run": run, "cases": cases}, ensure_ascii=False),
                media_type="application/json",
                headers=headers,
            )
        output = io.StringIO()
        columns = [
            "case_id",
            "status",
            "question",
            "reference_answer",
            "answer",
            "error",
            "target_latency_ms",
            "elapsed_ms",
            "precision_at_10",
            "precision_at_20",
            "ap_at_10",
            "ap_at_20",
            "ndcg_at_10",
            "ndcg_at_20",
            "reference_chunks",
            "contexts",
            "score",
            "target_attempts",
            "target_usage",
        ]
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for case in cases:
            score = case["score"]
            row = {key: case[key] for key in columns[:8]}
            for k in (10, 20):
                at_k = score["scores"].get(str(k)) if score else None
                for field, source in (("precision", "precision"), ("ap", "ap"), ("ndcg", "ndcg")):
                    row[f"{field}_at_{k}"] = at_k[source] if at_k else None
            for key in ("reference_chunks", "contexts", "score", "target_attempts", "target_usage"):
                row[key] = (
                    json.dumps(case[key], ensure_ascii=False) if case[key] is not None else None
                )
            for key in ("case_id", "question", "reference_answer", "answer"):
                value = row.get(key)
                if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
                    row[key] = "'" + value
            writer.writerow(row)
        return Response(
            content=output.getvalue(), media_type="text/csv; charset=utf-8", headers=headers
        )

    @router.post("/{run_id}/cancel", response_model=RunSummary)
    def cancel(run_id: str) -> dict[str, Any]:
        try:
            return store.cancel(run_id)
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="评测运行不存在") from exc

    return router
