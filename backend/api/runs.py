"""Asynchronous retrieval runs and durable result access."""

import csv
import io
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field, ValidationError, field_validator

from backend.adapters.model_store import OnlineModelNotFound, OnlineModelStore
from backend.adapters.run_store import RunInputError, RunNotFound, RunStore
from backend.adapters.scenario_store import ScenarioNotFound, ScenarioStore
from backend.api.matching import ChunkInput, KScoreResponse
from backend.api.predictions import PredictedChunkResponse
from backend.config import Settings
from backend.domain.runs import CaseStatus, MetricKey
from backend.health import worker_is_ready
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
    match_rule_version: Literal["one-to-one-v1"] = "one-to-one-v1"
    gain_rule_version: Literal["ordered-linear-v1"] = "ordered-linear-v1"

    @field_validator("metrics")
    @classmethod
    def validate_metrics(cls, value: list[MetricKey]) -> list[MetricKey]:
        if not value or len(set(value)) != len(value):
            raise ValueError("至少选择一个不重复的检索指标")
        return value


def default_metrics() -> list[MetricKey]:
    return ["precision", "map", "ndcg"]


class RunRescore(BaseModel):
    mode: Literal["retrieval", "answer", "both"] | None = None
    scenario_id: str | None = None
    scenario_version: int | None = Field(default=None, ge=1)
    judge_model_id: str | None = None
    model_name: str | None = None
    model_path: str | None = None
    offline: bool | None = None
    threshold: float | None = Field(default=None, ge=-1, le=1)
    metrics: list[MetricKey] | None = None
    match_rule_version: Literal["one-to-one-v1"] | None = None
    gain_rule_version: Literal["ordered-linear-v1"] | None = None


class RunSummary(BaseModel):
    id: str
    prediction_batch_id: str
    dataset_id: str
    dataset_version: int
    status: str
    config: dict[str, Any]
    estimated_external_calls: int
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


def create_run_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/runs", tags=["runs"])
    store = RunStore(settings.data_dir)
    scenarios = ScenarioStore(settings.data_dir)
    models = OnlineModelStore(settings.data_dir)

    def start_run(request: RunCreate, source_run_id: str | None = None) -> dict[str, Any]:
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
            result = store.create_run(
                request.prediction_batch_id,
                request.model_name,
                model_path,
                request.offline,
                request.threshold,
                request.metrics,
                request.mode,
                answer_config,
                source_run_id,
                request.match_rule_version,
                request.gain_rule_version,
            )
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="预测批次不存在") from exc
        except RunInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ScenarioNotFound as exc:
            raise HTTPException(status_code=404, detail="场景版本不存在") from exc
        except OnlineModelNotFound as exc:
            raise HTTPException(status_code=404, detail="评分模型不存在") from exc
        score_run_task(result["id"])
        return result

    @router.post("", status_code=202, response_model=RunSummary)
    def create(request: RunCreate) -> dict[str, Any]:
        return start_run(request)

    @router.post("/{run_id}/rescore", status_code=202, response_model=RunSummary)
    def rescore(run_id: str, request: RunRescore) -> dict[str, Any]:
        try:
            source = store.get_run(run_id)
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="原运行不存在") from exc
        previous = source["config"]
        answer = previous.get("answer") or {}
        values = {
            "prediction_batch_id": source["prediction_batch_id"],
            "mode": previous.get("mode", "retrieval"),
            "scenario_id": answer.get("scenario_id"),
            "scenario_version": answer.get("scenario_version"),
            "judge_model_id": answer.get("judge_model_id"),
            "model_name": previous["model_name"],
            "model_path": previous["model_path"],
            "offline": previous["offline"],
            "threshold": previous["threshold"],
            "metrics": previous["metrics"],
            "match_rule_version": previous["match_rule_version"],
            "gain_rule_version": previous["gain_rule_version"],
        }
        changes = request.model_dump(exclude_unset=True)
        if "scenario_id" in changes and "scenario_version" not in changes:
            values["scenario_version"] = None
        try:
            effective = RunCreate.model_validate({**values, **changes})
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        return start_run(effective, run_id)

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
            "answer_metrics",
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
            return store.cancel(run_id)
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="评测运行不存在") from exc

    return router
