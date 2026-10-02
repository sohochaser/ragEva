"""Online OpenAI-compatible model settings without credential exposure."""

from typing import Any
from urllib.parse import parse_qsl, urlsplit

from fastapi import APIRouter
from pydantic import BaseModel, Field, SecretStr, field_validator

from backend.adapters.model_store import OnlineModelStore
from backend.config import Settings


class OnlineModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    bearer_token: SecretStr | None = None
    timeout_seconds: float = Field(default=60, gt=0, le=180)

    @field_validator("name", "model_name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("名称不能为空")
        return value.strip()

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        parts = urlsplit(value)
        secrets = {"token", "api_key", "access_key", "secret", "password", "authorization"}
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.fragment
            or any(key.lower() in secrets for key, _ in parse_qsl(parts.query))
        ):
            raise ValueError("模型地址必须是无内嵌凭据的 HTTP(S) 地址")
        return value


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

    @router.post("", status_code=201, response_model=OnlineModelSummary)
    def create(request: OnlineModelCreate) -> dict[str, Any]:
        return store.create(
            request.name,
            request.base_url,
            request.model_name,
            request.bearer_token.get_secret_value() if request.bearer_token else None,
            request.timeout_seconds,
        )

    @router.get("", response_model=list[OnlineModelSummary])
    def list_models() -> list[dict[str, Any]]:
        return store.list_models()

    return router
