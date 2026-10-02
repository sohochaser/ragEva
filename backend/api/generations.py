"""Generation jobs and reviewable candidates."""

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.adapters.dataset_store import DatasetNotFound
from backend.adapters.document_store import CollectionNotFound
from backend.adapters.generation_store import (
    CandidateNotFound,
    DuplicateDecisionConflict,
    GenerationNotFound,
    GenerationStore,
    InvalidReview,
    RevisionConflict,
)
from backend.adapters.model_store import OnlineModelNotFound, OnlineModelStore
from backend.adapters.publication_store import (
    InvalidPublication,
    PublicationConflict,
    PublicationStore,
)
from backend.api.datasets import ImportFailure, ImportIssueResponse, VersionSummary
from backend.config import Settings
from backend.domain.candidate_review import ReviewAction
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
    collection_id: str
    revision: int
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


class CandidateReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    collection_id: str = Field(min_length=1)
    question: str = Field(max_length=2000)
    reference_answer: str = Field(max_length=10000)
    support_positions: list[int] = Field(max_length=1000)
    action: ReviewAction


class CandidateRevision(BaseModel):
    revision: int
    question: str
    reference_answer: str
    reference_chunks: list[CandidateChunk]
    support_positions: list[int]
    status: str
    created_at: str


class CandidateReviewIssue(BaseModel):
    field: str
    message: str


class CandidateReviewFailure(BaseModel):
    error: str
    issues: list[CandidateReviewIssue]


class DuplicateMatch(BaseModel):
    source_kind: str
    source_id: str
    question: str
    reference_answer: str
    verdict: str
    reason: str
    shared_source_count: int
    question_similarity: float
    term_similarity: float


class DuplicateCheck(BaseModel):
    id: int
    candidate_id: str
    revision: int
    verdict: str
    matches: list[DuplicateMatch]
    rule_version: str
    checked_at: str
    decision: str | None
    reason: str | None
    decided_at: str | None


class DuplicateDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: int = Field(gt=0)
    expected_revision: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=2000)


class PublicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_ids: list[str] = Field(min_length=1, max_length=1000)
    dataset_name: str | None = Field(default=None, max_length=120)
    dataset_id: str | None = None
    expected_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def valid_target(self) -> "PublicationRequest":
        if (bool(self.dataset_name and self.dataset_name.strip())) == bool(self.dataset_id):
            raise ValueError("需要填写新数据集名称或选择已有数据集")
        if self.dataset_id and self.expected_version is None:
            raise ValueError("追加数据集时需要当前版本号")
        if not self.dataset_id and self.expected_version is not None:
            raise ValueError("新数据集不应填写版本号")
        if self.dataset_name is not None:
            self.dataset_name = self.dataset_name.strip()
        return self


def create_generation_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["generations"])
    store = GenerationStore(settings.data_dir)
    publisher = PublicationStore(settings.data_dir)
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

    @router.get("/api/v1/candidates/{candidate_id}", response_model=GeneratedCandidate)
    def get_candidate(candidate_id: str) -> dict[str, Any]:
        try:
            return store.get_candidate(candidate_id)
        except CandidateNotFound as exc:
            raise HTTPException(status_code=404, detail="候选不存在") from exc

    @router.get(
        "/api/v1/candidates/{candidate_id}/revisions",
        response_model=list[CandidateRevision],
    )
    def get_candidate_revisions(candidate_id: str) -> list[dict[str, Any]]:
        try:
            return store.revisions(candidate_id)
        except CandidateNotFound as exc:
            raise HTTPException(status_code=404, detail="候选不存在") from exc

    @router.patch(
        "/api/v1/candidates/{candidate_id}",
        response_model=GeneratedCandidate,
        responses={422: {"model": CandidateReviewFailure}},
    )
    def review_candidate(
        candidate_id: str, request: CandidateReviewRequest
    ) -> dict[str, Any] | JSONResponse:
        try:
            return store.review(candidate_id, **request.model_dump())
        except CandidateNotFound as exc:
            raise HTTPException(status_code=404, detail="候选不存在") from exc
        except RevisionConflict as exc:
            raise HTTPException(status_code=409, detail="候选已被其他审核操作修改，请刷新") from exc
        except InvalidReview as exc:
            return JSONResponse(
                status_code=422,
                content=CandidateReviewFailure(
                    error="validation_failed",
                    issues=[CandidateReviewIssue(**vars(issue)) for issue in exc.issues],
                ).model_dump(),
            )

    @router.get(
        "/api/v1/candidates/{candidate_id}/duplicate-check",
        response_model=DuplicateCheck | None,
    )
    def get_duplicate_check(candidate_id: str) -> dict[str, Any] | None:
        try:
            return store.duplicate_check(candidate_id)
        except CandidateNotFound as exc:
            raise HTTPException(status_code=404, detail="候选不存在") from exc

    @router.get(
        "/api/v1/candidates/{candidate_id}/duplicate-history",
        response_model=list[DuplicateCheck],
    )
    def get_duplicate_history(candidate_id: str) -> list[dict[str, Any]]:
        try:
            return store.duplicate_history(candidate_id)
        except CandidateNotFound as exc:
            raise HTTPException(status_code=404, detail="候选不存在") from exc

    @router.post(
        "/api/v1/candidates/{candidate_id}/duplicate-check",
        response_model=DuplicateCheck,
    )
    def recheck_duplicate(candidate_id: str) -> dict[str, Any]:
        try:
            return store.check_duplicates(candidate_id)
        except CandidateNotFound as exc:
            raise HTTPException(status_code=404, detail="候选不存在") from exc

    @router.post(
        "/api/v1/candidates/{candidate_id}/duplicate-decision",
        response_model=DuplicateCheck,
    )
    def allow_suspected(candidate_id: str, request: DuplicateDecisionRequest) -> dict[str, Any]:
        try:
            return store.decide_duplicate(candidate_id, **request.model_dump())
        except CandidateNotFound as exc:
            raise HTTPException(status_code=404, detail="候选不存在") from exc
        except DuplicateDecisionConflict as exc:
            raise HTTPException(
                status_code=409, detail="查重结论已变化或候选尚未批准，请刷新"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post(
        "/api/v1/candidates/publish",
        response_model=VersionSummary,
        status_code=201,
        responses={422: {"model": ImportFailure}},
    )
    def publish_candidates(request: PublicationRequest) -> dict[str, Any] | JSONResponse:
        try:
            return publisher.publish(**request.model_dump())
        except CandidateNotFound as exc:
            raise HTTPException(status_code=404, detail=f"候选不存在：{exc}") from exc
        except DatasetNotFound as exc:
            raise HTTPException(status_code=404, detail="数据集不存在") from exc
        except PublicationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except InvalidPublication as exc:
            return JSONResponse(
                status_code=422,
                content=ImportFailure(
                    error="validation_failed",
                    issues=[ImportIssueResponse(**vars(issue)) for issue in exc.issues],
                ).model_dump(),
            )

    return router
