"""Asynchronous retrieval runs and durable result access."""

import csv
import io
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator

from backend.adapters.model_store import OnlineModelNotFound, OnlineModelStore
from backend.adapters.run_store import RunInputError, RunNotFound, RunStore
from backend.adapters.scenario_store import ScenarioNotFound, ScenarioStore
from backend.adapters.target_store import TargetStore
from backend.adapters.trace_store import TraceStore
from backend.adapters.usage_store import UsageStore, summarize_calls
from backend.api.matching import ChunkInput, KScoreResponse
from backend.api.predictions import PredictedChunkResponse
from backend.api.trace import TraceReference
from backend.api.usage import UsageSummary
from backend.config import Settings
from backend.domain.runs import CaseStatus, MetricKey
from backend.health import worker_is_ready
from backend.tracing import attributes, business_span, carrier
from backend.worker.queue import score_run_task


class RunCreate(BaseModel):
    prediction_batch_id: str = Field(min_length=1)
    mode: Literal["retrieval", "answer", "both"] = "retrieval"
    scenario_id: str | None = None
    scenario_version: int | None = Field(default=None, ge=1)
    judge_model_id: str | None = None
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
    trace: TraceReference | None = None
    prediction_trace: TraceReference | None = None
    dataset_trace: TraceReference | None = None


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
    answer_metrics: dict[str, "AnswerAggregate"] = Field(default_factory=dict)


class AnswerAggregate(BaseModel):
    valid_count: int
    failed_count: int
    not_applicable_count: int
    mean_score: float | None


class AnswerMetricResponse(BaseModel):
    status: Literal["success", "failed", "not_applicable"]
    score: float | None
    reason: str | None
    raw_response: str | None
    error: str | None
    usage: dict[str, int] | None
    model_name: str
    prompt_version: str
    criteria: str


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
    answer_metrics: dict[str, AnswerMetricResponse] = Field(default_factory=dict)
    question: str
    reference_answer: str | None
    reference_chunks: list[ChunkInput] | None
    answer: str | None
    contexts: list[PredictedChunkResponse] | None
    target_latency_ms: float | None
    target_attempts: list[dict[str, Any]] | None = None
    target_usage: dict[str, int] | None = None
    trace: TraceReference | None = None
    target_trace: TraceReference | None = None


def create_run_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/runs", tags=["runs"])
    store = RunStore(settings.data_dir)
    scenarios = ScenarioStore(settings.data_dir)
    models = OnlineModelStore(settings.data_dir)
    usages = UsageStore(settings.data_dir)
    targets = TargetStore(settings.data_dir)
    traces = TraceStore(settings.data_dir)

    def traced_run(run: dict[str, Any]) -> dict[str, Any]:
        run["trace"] = traces.get("run", run["id"], settings)
        run["prediction_trace"] = traces.get("batch", run["prediction_batch_id"], settings)
        run["dataset_trace"] = traces.get(
            "dataset_version", run["config"]["dataset_version_id"], settings
        )
        return run

    def traced_cases(run_id: str, page: dict[str, Any]) -> dict[str, Any]:
        job_id = targets.job_for_batch(store.get_run(run_id)["prediction_batch_id"])
        for item in page["cases"]:
            item["trace"] = traces.get("run_case", f"{run_id}:{item['case_id']}", settings)
            item["target_trace"] = (
                traces.get("target_case", f"{job_id}:{item['case_id']}", settings)
                if job_id
                else None
            )
        return page

    @router.post("", status_code=202, response_model=RunSummary)
    def create(request: RunCreate) -> dict[str, Any]:
        if not worker_is_ready(settings.data_dir, settings.worker_stale_after):
            raise HTTPException(status_code=503, detail="Worker 不可用")
        try:
            answer_config = None
            if request.mode in {"answer", "both"}:
                if not request.scenario_id or not request.judge_model_id:
                    raise RunInputError("回答评测需要场景和评分模型")
                scenario = (
                    scenarios.get_scenario_version(request.scenario_id, request.scenario_version)
                    if request.scenario_version is not None
                    else scenarios.list_versions(request.scenario_id)[0]
                )
                model = models.get(request.judge_model_id)
                answer_config = {
                    "scenario_id": scenario["scenario_id"],
                    "scenario_version": scenario["version"],
                    "prompt_version": scenario["prompt_version"],
                    "criteria": {
                        key: scenario[key] for key in ("faithfulness", "relevance", "correctness")
                    },
                    "judge_model_id": model["id"],
                    "model_name": model["model_name"],
                    "base_url": model["base_url"],
                    "timeout_seconds": model["timeout_seconds"],
                    "temperature": 0,
                    "response_format": "json_object",
                }
            model_path = (
                str(Path(request.model_path).expanduser().resolve()) if request.model_path else None
            )
            with business_span("run.create") as span:
                result = store.create_run(
                    request.prediction_batch_id,
                    request.model_name,
                    model_path,
                    request.offline,
                    request.threshold,
                    request.metrics,
                    request.mode,
                    answer_config,
                )
                attributes(
                    span, **{"run.id": result["id"], "batch.id": request.prediction_batch_id}
                )
                traces.record("run", result["id"], span)
                score_run_task(result["id"], carrier())
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="预测批次不存在") from exc
        except RunInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ScenarioNotFound as exc:
            raise HTTPException(status_code=404, detail="场景版本不存在") from exc
        except OnlineModelNotFound as exc:
            raise HTTPException(status_code=404, detail="评分模型不存在") from exc
        return traced_run(result)

    @router.get("", response_model=list[RunSummary])
    def list_runs() -> list[dict[str, Any]]:
        return [traced_run(run) for run in store.list_runs()]

    @router.get("/{run_id}", response_model=RunSummary)
    def get_run(run_id: str) -> dict[str, Any]:
        try:
            return traced_run(store.get_run(run_id))
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
            return traced_cases(run_id, store.get_cases(run_id, offset, limit, status))
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="评测运行不存在") from exc

    @router.get("/{run_id}/usage", response_model=UsageSummary)
    def get_usage(run_id: str) -> dict[str, Any]:
        try:
            run = store.get_run(run_id)
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="评测运行不存在") from exc
        calls = usages.for_owner("run", run_id)["calls"]
        target_job_id = targets.job_for_batch(run["prediction_batch_id"])
        if target_job_id:
            calls.extend(usages.for_owner("target_job", target_job_id)["calls"])
            calls.sort(key=lambda item: (item["created_at"], item["id"]))
        return summarize_calls(calls)

    @router.get("/{run_id}/export")
    def export(
        run_id: str,
        format: Literal["json", "csv"] = "json",
        status: CaseStatus | None = None,
    ) -> Response:
        try:
            run = traced_run(store.get_run(run_id))
            cases: list[dict[str, Any]] = []
            while True:
                page = traced_cases(run_id, store.get_cases(run_id, len(cases), 1000, status))
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
            "trace_id",
            "target_trace_id",
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
            "answer_metrics",
        ]
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for case in cases:
            score = case["score"]
            row = {key: case[key] for key in columns[:8]}
            row["trace_id"] = case["trace"]["trace_id"] if case["trace"] else None
            row["target_trace_id"] = (
                case["target_trace"]["trace_id"] if case["target_trace"] else None
            )
            for k in (10, 20):
                at_k = score["scores"].get(str(k)) if score else None
                for field, source in (("precision", "precision"), ("ap", "ap"), ("ndcg", "ndcg")):
                    row[f"{field}_at_{k}"] = at_k[source] if at_k else None
            for key in (
                "reference_chunks",
                "contexts",
                "score",
                "target_attempts",
                "target_usage",
                "answer_metrics",
            ):
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
            return traced_run(store.cancel(run_id))
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="评测运行不存在") from exc

    return router
