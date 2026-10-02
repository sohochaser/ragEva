"""Versioned answer criteria and single-case scoring preview."""

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.adapters.answer_model import AnswerModelError, evaluate_answer_metric
from backend.adapters.model_store import OnlineModelNotFound, OnlineModelStore
from backend.adapters.scenario_store import ScenarioNotFound, ScenarioStore
from backend.config import Settings
from backend.domain.answer_prompts import (
    OUTPUT_SCHEMA,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    VARIABLES,
    AnswerMetric,
    AnswerSample,
    applicability,
)


class ScenarioCriteria(BaseModel):
    faithfulness: str = Field(min_length=1, max_length=4000)
    relevance: str = Field(min_length=1, max_length=4000)
    correctness: str = Field(min_length=1, max_length=4000)

    @field_validator("faithfulness", "relevance", "correctness")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("评价标准不能为空")
        return value.strip()


class ScenarioCreate(ScenarioCriteria):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("场景名称不能为空")
        return value.strip()


class ScenarioVersion(BaseModel):
    scenario_id: str
    id: str
    name: str
    version: int
    faithfulness: str
    relevance: str
    correctness: str
    prompt_version: str
    created_at: str


class PromptTemplate(BaseModel):
    version: str
    system_prompt: str
    variables: list[str]
    output_schema: dict[str, str]


class ScenarioPreviewRequest(BaseModel):
    model_id: str = Field(min_length=1)
    version: int | None = Field(default=None, ge=1)
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    reference_answer: str = Field(min_length=1)
    contexts: list[str] = Field(min_length=1)

    @field_validator("question", "answer", "reference_answer")
    @classmethod
    def nonblank_sample(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("预览输入不能为空")
        return value.strip()

    @field_validator("contexts")
    @classmethod
    def nonblank_contexts(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("上下文不能为空")
        return value


class PreviewMetric(BaseModel):
    status: str
    score: float | None
    reason: str | None
    raw_response: str | None
    usage: dict[str, int] | None


class ScenarioPreviewResponse(BaseModel):
    scenario_id: str
    version: int
    prompt_version: str
    model_name: str
    metrics: dict[AnswerMetric, PreviewMetric]


def create_scenario_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/scenarios", tags=["scenarios"])
    store = ScenarioStore(settings.data_dir)
    models = OnlineModelStore(settings.data_dir)

    @router.get("/template", response_model=PromptTemplate)
    def template() -> PromptTemplate:
        return PromptTemplate(
            version=PROMPT_VERSION,
            system_prompt=SYSTEM_PROMPT,
            variables=VARIABLES,
            output_schema=OUTPUT_SCHEMA,
        )

    @router.post("", status_code=201, response_model=ScenarioVersion)
    def create(request: ScenarioCreate) -> dict[str, Any]:
        return store.create(
            request.name, request.faithfulness, request.relevance, request.correctness
        )

    @router.get("", response_model=list[ScenarioVersion])
    def list_scenarios() -> list[dict[str, Any]]:
        return store.list_scenarios()

    @router.get("/{scenario_id}/versions", response_model=list[ScenarioVersion])
    def list_versions(scenario_id: str) -> list[dict[str, Any]]:
        try:
            return store.list_versions(scenario_id)
        except ScenarioNotFound as exc:
            raise HTTPException(status_code=404, detail="场景不存在") from exc

    @router.put("/{scenario_id}", response_model=ScenarioVersion)
    def update(scenario_id: str, request: ScenarioCriteria) -> dict[str, Any]:
        try:
            return store.update(
                scenario_id, request.faithfulness, request.relevance, request.correctness
            )
        except ScenarioNotFound as exc:
            raise HTTPException(status_code=404, detail="场景不存在") from exc

    @router.post("/{scenario_id}/preview", response_model=ScenarioPreviewResponse)
    def preview(scenario_id: str, request: ScenarioPreviewRequest) -> ScenarioPreviewResponse:
        try:
            version = (
                store.get_scenario_version(scenario_id, request.version)
                if request.version is not None
                else store.list_versions(scenario_id)[0]
            )
            model = models.get(request.model_id)
            token = models.token(request.model_id)
        except ScenarioNotFound as exc:
            raise HTTPException(status_code=404, detail="场景不存在") from exc
        except OnlineModelNotFound as exc:
            raise HTTPException(status_code=404, detail="在线模型不存在") from exc
        sample = AnswerSample(
            request.question,
            request.answer,
            request.reference_answer,
            tuple(request.contexts),
        )
        output: dict[AnswerMetric, PreviewMetric] = {}
        try:
            with httpx.Client() as client:
                for metric in ("faithfulness", "relevance", "correctness"):
                    missing = applicability(metric, sample)
                    if missing:
                        output[metric] = PreviewMetric(
                            status="not_applicable",
                            score=None,
                            reason=missing,
                            raw_response=None,
                            usage=None,
                        )
                        continue
                    result = evaluate_answer_metric(
                        client,
                        model["base_url"],
                        model["model_name"],
                        token,
                        model["timeout_seconds"],
                        metric,
                        version[metric],
                        sample,
                    )
                    output[metric] = PreviewMetric(
                        status="success",
                        score=result.score,
                        reason=result.reason,
                        raw_response=result.raw_response,
                        usage=result.usage,
                    )
        except AnswerModelError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return ScenarioPreviewResponse(
            scenario_id=scenario_id,
            version=version["version"],
            prompt_version=version["prompt_version"],
            model_name=model["model_name"],
            metrics=output,
        )

    return router
