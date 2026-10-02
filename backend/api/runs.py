"""Asynchronous retrieval runs and durable result access."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from backend.adapters.run_store import RunInputError, RunNotFound, RunStore
from backend.config import Settings
from backend.domain.runs import MetricKey
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
    aggregate: dict[str, Any] | None
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
    cases: list[dict[str, Any]]


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
    ) -> dict[str, Any]:
        try:
            return store.get_cases(run_id, offset, limit)
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="评测运行不存在") from exc

    @router.post("/{run_id}/cancel", response_model=RunSummary)
    def cancel(run_id: str) -> dict[str, Any]:
        try:
            return store.cancel(run_id)
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="评测运行不存在") from exc

    return router
