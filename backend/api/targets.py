"""Local HTTP target configuration, connection test, and collection jobs."""

from dataclasses import asdict
from typing import Any, Literal
from urllib.parse import parse_qsl, urlsplit

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, SecretStr, field_validator

from backend.adapters.http_target import call_json_target
from backend.adapters.sse_target import call_sse_target
from backend.adapters.target_store import TargetJobNotFound, TargetNotFound, TargetStore
from backend.adapters.usage_store import UsageStore
from backend.api.usage import UsageSummary
from backend.config import Settings
from backend.domain.predictions import EvaluationType
from backend.health import worker_is_ready
from backend.worker.queue import collect_target_task


class TargetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1)
    bearer_token: SecretStr | None = None
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    retries: int = Field(default=1, ge=0, le=3)
    max_concurrency: int = Field(default=4, ge=1, le=8)
    protocol: Literal["json", "sse"] = "json"

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("目标名称不能为空")
        return value.strip()

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
        ):
            raise ValueError("目标 URL 必须是无内嵌凭据的 HTTP(S) 地址")
        secret_keys = {"token", "api_key", "access_key", "secret", "password", "authorization"}
        if parts.fragment or any(key.lower() in secret_keys for key, _ in parse_qsl(parts.query)):
            raise ValueError("目标 URL 不能包含凭据或片段标识")
        return value


class TargetSummary(BaseModel):
    id: str
    name: str
    url: str
    has_token: bool
    timeout_seconds: float
    retries: int
    max_concurrency: int
    protocol: Literal["json", "sse"]
    created_at: str


class TargetTestRequest(BaseModel):
    case_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    evaluation_type: EvaluationType = "both"


class TargetTestResponse(BaseModel):
    success: bool
    error: str | None
    answer: str | None
    contexts: list[dict[str, Any]] | None
    usage: dict[str, int] | None
    attempts: list[dict[str, Any]]


class TargetJobCreate(BaseModel):
    target_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    dataset_version: int = Field(ge=1)
    evaluation_type: EvaluationType = "both"


class TargetJobSummary(BaseModel):
    id: str
    target_id: str
    dataset_id: str
    dataset_version: int
    evaluation_type: EvaluationType
    status: str
    batch_id: str | None
    total_count: int
    processed_count: int
    success_count: int
    failed_count: int
    cancelled_count: int
    cancel_requested: bool
    estimated_external_calls: int
    created_at: str
    started_at: str | None
    finished_at: str | None


class TargetJobCase(BaseModel):
    case_id: str
    status: str
    error: str | None
    attempts: list[dict[str, Any]] | None
    usage: dict[str, int] | None
    elapsed_ms: float | None


def create_target_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/targets", tags=["targets"])
    store = TargetStore(settings.data_dir)

    @router.post("", status_code=201, response_model=TargetSummary)
    def create(request: TargetCreate) -> dict[str, Any]:
        return store.create_target(
            request.name.strip(),
            request.url,
            request.bearer_token.get_secret_value() if request.bearer_token else None,
            request.timeout_seconds,
            request.retries,
            request.protocol,
            request.max_concurrency,
        )

    @router.get("", response_model=list[TargetSummary])
    def list_targets() -> list[dict[str, Any]]:
        return store.list_targets()

    @router.post("/{target_id}/test", response_model=TargetTestResponse)
    def test(target_id: str, request: TargetTestRequest) -> dict[str, Any]:
        try:
            target = store.get_target(target_id)
            token = store.token(target_id)
        except TargetNotFound as exc:
            raise HTTPException(status_code=404, detail="目标不存在") from exc
        with httpx.Client() as client:
            caller = call_sse_target if target["protocol"] == "sse" else call_json_target
            result = caller(
                client,
                target["url"],
                token,
                request.case_id,
                request.question,
                request.evaluation_type,
                target["timeout_seconds"],
                target["retries"],
            )
        return {
            "success": result.prediction is not None,
            "error": result.error,
            "answer": result.prediction.answer if result.prediction else None,
            "contexts": [asdict(item) for item in result.prediction.contexts]
            if result.prediction and result.prediction.contexts
            else None,
            "usage": result.usage,
            "attempts": [asdict(item) for item in result.attempts],
        }

    return router


def create_target_job_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/target-jobs", tags=["target-jobs"])
    store = TargetStore(settings.data_dir)
    usages = UsageStore(settings.data_dir)

    @router.post("", status_code=202, response_model=TargetJobSummary)
    def create(request: TargetJobCreate) -> dict[str, Any]:
        if not worker_is_ready(settings.data_dir, settings.worker_stale_after):
            raise HTTPException(status_code=503, detail="Worker 不可用")
        try:
            job = store.create_job(
                request.target_id,
                request.dataset_id,
                request.dataset_version,
                request.evaluation_type,
            )
        except TargetNotFound as exc:
            raise HTTPException(status_code=404, detail="目标不存在") from exc
        except TargetJobNotFound as exc:
            raise HTTPException(status_code=404, detail="数据集版本不存在") from exc
        collect_target_task(job["id"])
        return job

    @router.get("", response_model=list[TargetJobSummary])
    def list_jobs() -> list[dict[str, Any]]:
        return store.list_jobs()

    @router.get("/{job_id}", response_model=TargetJobSummary)
    def get_job(job_id: str) -> dict[str, Any]:
        try:
            return store.get_job(job_id)
        except TargetJobNotFound as exc:
            raise HTTPException(status_code=404, detail="采集任务不存在") from exc

    @router.post("/{job_id}/cancel", response_model=TargetJobSummary)
    def cancel_job(job_id: str) -> dict[str, Any]:
        try:
            return store.cancel_job(job_id)
        except TargetJobNotFound as exc:
            raise HTTPException(status_code=404, detail="采集任务不存在") from exc

    @router.get("/{job_id}/cases", response_model=list[TargetJobCase])
    def job_cases(job_id: str) -> list[dict[str, Any]]:
        try:
            return store.job_cases(job_id)
        except TargetJobNotFound as exc:
            raise HTTPException(status_code=404, detail="采集任务不存在") from exc

    @router.get("/{job_id}/usage", response_model=UsageSummary)
    def job_usage(job_id: str) -> dict[str, Any]:
        try:
            store.get_job(job_id)
        except TargetJobNotFound as exc:
            raise HTTPException(status_code=404, detail="采集任务不存在") from exc
        return usages.for_owner("target_job", job_id)

    return router
