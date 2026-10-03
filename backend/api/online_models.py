"""Online OpenAI-compatible model settings without credential exposure."""

from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, SecretStr, field_validator

from backend.adapters.model_probe import ModelValidationError, probe_online_model
from backend.adapters.model_store import OnlineModelInUse, OnlineModelNotFound, OnlineModelStore
from backend.config import Settings


class OnlineModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=2048)
    model_name: str = Field(min_length=1, max_length=200)
    bearer_token: SecretStr | None = None
    timeout_seconds: float = Field(default=60, gt=0, le=180, allow_inf_nan=False)

    @field_validator("name", "model_name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("名称不能为空")
        return value.strip()

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        value = value.strip()
        try:
            parts = urlsplit(value)
            host = parts.hostname
            port = parts.port
        except ValueError as exc:
            raise ValueError("模型地址无效") from exc
        if (
            parts.scheme not in {"http", "https"}
            or not host
            or port == 0
            or parts.username
            or parts.password
            or parts.fragment
            or parts.query
        ):
            raise ValueError("模型地址必须是无内嵌凭据和查询参数的 HTTP(S) 地址")
        return value

    @field_validator("bearer_token")
    @classmethod
    def valid_token(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().strip():
            raise ValueError("令牌不能为空白")
        return value


class OnlineModelUpdate(OnlineModelCreate):
    pass


class OnlineModelSummary(BaseModel):
    id: str
    name: str
    base_url: str
    model_name: str
    has_token: bool
    timeout_seconds: float
    created_at: str


def create_model_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/online-models", tags=["online-models"])
    store = OnlineModelStore(settings.data_dir)

    def verify(request: OnlineModelCreate, token: str | None) -> None:
        try:
            with httpx.Client() as client:
                probe_online_model(
                    client,
                    request.base_url,
                    request.model_name,
                    token,
                    request.timeout_seconds,
                )
        except ModelValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Model verification failed（模型校验失败）: {exc}",
            ) from exc

    @router.post("", status_code=201, response_model=OnlineModelSummary)
    def create(request: OnlineModelCreate) -> dict[str, Any]:
        token = request.bearer_token.get_secret_value() if request.bearer_token else None
        verify(request, token)
        return store.create(
            request.name,
            request.base_url,
            request.model_name,
            token,
            request.timeout_seconds,
        )

    @router.get("", response_model=list[OnlineModelSummary])
    def list_models() -> list[dict[str, Any]]:
        return store.list_models()

    @router.put("/{model_id}", response_model=OnlineModelSummary)
    def update(model_id: str, request: OnlineModelUpdate) -> dict[str, Any]:
        try:
            current_token = store.token(model_id)
            store.ensure_idle(model_id)
            change_token = "bearer_token" in request.model_fields_set
            token = (
                (
                    request.bearer_token.get_secret_value()
                    if request.bearer_token is not None
                    else None
                )
                if change_token
                else current_token
            )
            verify(request, token)
            return store.update(
                model_id,
                request.name,
                request.base_url,
                request.model_name,
                request.timeout_seconds,
                change_token=change_token,
                token=token,
            )
        except OnlineModelNotFound as exc:
            raise HTTPException(status_code=404, detail="Model not found（模型不存在）") from exc
        except OnlineModelInUse as exc:
            raise HTTPException(
                status_code=409,
                detail="Model is used by an active task（模型正被进行中的任务使用）",
            ) from exc

    @router.delete("/{model_id}", status_code=204)
    def delete(model_id: str) -> None:
        try:
            store.delete(model_id)
        except OnlineModelNotFound as exc:
            raise HTTPException(status_code=404, detail="Model not found（模型不存在）") from exc
        except OnlineModelInUse as exc:
            raise HTTPException(
                status_code=409,
                detail="Model is used by an active task（模型正被进行中的任务使用）",
            ) from exc

    return router
