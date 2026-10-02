"""Generation jobs and reviewable candidates."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.adapters.document_store import CollectionNotFound
from backend.adapters.generation_store import GenerationNotFound, GenerationStore
from backend.adapters.model_store import OnlineModelNotFound, OnlineModelStore
from backend.config import Settings
from backend.domain.generation import PROMPT_VERSION, multi_chunk_target
from backend.health import worker_is_ready
from backend.worker.queue import generate_candidates_task


class GenerationCreate(BaseModel):
    model_id: str = Field(min_length=1)
    target_count: int = Field(ge=1, le=1000)
    multi_chunk_ratio: float = Field(ge=0, le=1, allow_inf_nan=False)
    language: str = Field(min_length=1, max_length=80)
    question_type: str = Field(min_length=1, max_length=80)
    instructions: str = Field(default="", max_length=2000)
    max_calls: int | None = Field(default=None, ge=1, le=3000)
    max_concurrency: int = Field(default=4, ge=1, le=4)

    @field_validator("language", "question_type")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("不能为空")
        return value.strip()


class GenerationSummary(BaseModel):
    id: str
    collection_id: str
    status: str
    config: dict[str, Any]
    target_count: int
    target_multi_count: int
    max_calls: int
    max_concurrency: int
    attempted_count: int
    actual_count: int
    actual_multi_count: int
    shortfall_reasons: list[str]
    attempt_errors: dict[str, int]
    created_at: str
    started_at: str | None
    finished_at: str | None


class CandidateChunk(BaseModel):
    document_id: str
    text: str


class GeneratedCandidate(BaseModel):
    id: str
    run_id: str
    slot_index: int
    question: str
    reference_answer: str
    reference_chunks: list[CandidateChunk]
    support_positions: list[int]
    multi_chunk: bool
    status: str
    prompt_version: str
    model_name: str
    created_at: str


def create_generation_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["generations"])
    store = GenerationStore(settings.data_dir)
    models = OnlineModelStore(settings.data_dir)

    @router.post(
        "/api/v1/document-collections/{collection_id}/generations",
        response_model=GenerationSummary,
        status_code=202,
    )
    def create(collection_id: str, request: GenerationCreate) -> dict[str, Any]:
        if not worker_is_ready(settings.data_dir, settings.worker_stale_after):
            raise HTTPException(status_code=503, detail="Worker 不可用")
        try:
            collection = store.get_collection(collection_id)
            model = models.get(request.model_id)
        except CollectionNotFound as exc:
            raise HTTPException(status_code=404, detail="文档集合不存在") from exc
        except OnlineModelNotFound as exc:
            raise HTTPException(status_code=404, detail="生成模型不存在") from exc
        if not collection["chunks"]:
            raise HTTPException(status_code=422, detail="集合没有可用 chunk")
        max_calls = request.max_calls or min(request.target_count * 3, 3000)
        if max_calls < request.target_count:
            raise HTTPException(status_code=422, detail="最大调用次数不能小于目标条数")
        config = {
            "model_id": model["id"],
            "model_name": model["model_name"],
            "base_url": model["base_url"],
            "timeout_seconds": model["timeout_seconds"],
            "language": request.language,
            "question_type": request.question_type,
            "instructions": request.instructions.strip(),
            "multi_chunk_ratio": request.multi_chunk_ratio,
            "prompt_version": PROMPT_VERSION,
            "temperature": 0.3,
            "response_format": "json_object",
        }
        result = store.create_run(
            collection_id,
            config,
            request.target_count,
            multi_chunk_target(request.target_count, request.multi_chunk_ratio),
            max_calls,
            request.max_concurrency,
        )
        generate_candidates_task(result["id"])
        return result

    @router.get("/api/v1/generations", response_model=list[GenerationSummary])
    def list_runs() -> list[dict[str, Any]]:
        return store.list_runs()

    @router.get("/api/v1/generations/{run_id}", response_model=GenerationSummary)
    def get_run(run_id: str) -> dict[str, Any]:
        try:
            return store.get(run_id)
        except GenerationNotFound as exc:
            raise HTTPException(status_code=404, detail="生成任务不存在") from exc

    @router.get(
        "/api/v1/generations/{run_id}/candidates",
        response_model=list[GeneratedCandidate],
    )
    def get_candidates(run_id: str) -> list[dict[str, Any]]:
        try:
            return store.candidates(run_id)
        except GenerationNotFound as exc:
            raise HTTPException(status_code=404, detail="生成任务不存在") from exc

    return router
