"""Read-only diagnostic timeline for one user request."""

import re
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.adapters.request_log_store import RequestLogStore
from backend.config import Settings


class RequestLogSummary(BaseModel):
    request_id: str
    started_at: str
    method: str
    route: str
    http_status: int
    status: Literal["success", "failed"]
    error_code: str | None


class RequestLogSpan(BaseModel):
    span_id: str
    parent_span_id: str | None
    name: str
    started_at: str
    duration_ms: float
    status: Literal["success", "failed"]
    error_code: str | None
    error_detail: str | None
    attributes: dict[str, Any]


class RequestLogDetail(RequestLogSummary):
    spans: list[RequestLogSpan]


def create_request_log_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/request-logs", tags=["request-logs"])
    store = RequestLogStore(settings.data_dir)

    @router.get("", response_model=list[RequestLogSummary])
    def recent(limit: int = Query(default=50, ge=1, le=100)) -> list[dict[str, Any]]:
        return store.recent(limit)

    @router.get("/{request_id}", response_model=RequestLogDetail)
    def detail(request_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{32}", request_id):
            raise HTTPException(status_code=404, detail="请求日志不存在")
        result = store.get(request_id)
        if result is None:
            raise HTTPException(status_code=404, detail="请求日志不存在")
        return result

    return router
