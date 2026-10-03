"""Versioned management API and health contract."""

from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.adapters.request_log_store import RequestLogStore
from backend.api.datasets import create_dataset_router
from backend.api.document_collections import create_document_collection_router
from backend.api.generations import create_generation_router
from backend.api.matching import create_matching_router
from backend.api.online_models import create_model_router
from backend.api.predictions import create_prediction_router
from backend.api.request_logs import create_request_log_router
from backend.api.runs import create_run_router
from backend.api.scenarios import create_scenario_router
from backend.api.targets import create_target_job_router, create_target_router
from backend.config import Settings
from backend.health import worker_is_ready
from backend.tracing import attributes, business_span, configure_tracing, fail, request_log_scope


class HealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    component: Literal["api", "worker"]


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    configure_tracing(config, "rageva-api")
    application = FastAPI(title="ragEva API", version="0.1.0")
    request_logs = RequestLogStore(config.data_dir)
    application.include_router(create_dataset_router(config))
    application.include_router(create_document_collection_router(config))
    application.include_router(create_generation_router(config))
    application.include_router(create_prediction_router(config))
    application.include_router(create_matching_router(config))
    application.include_router(create_run_router(config))
    application.include_router(create_target_router(config))
    application.include_router(create_target_job_router(config))
    application.include_router(create_model_router(config))
    application.include_router(create_scenario_router(config))
    application.include_router(create_request_log_router(config))

    @application.middleware("http")
    async def log_request(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not request.url.path.startswith("/api/v1/") or request.url.path.startswith(
            ("/api/v1/health/", "/api/v1/request-logs")
        ):
            return await call_next(request)
        with request_log_scope(request_logs), business_span("http.request") as span:
            attributes(span, **{"http.method": request.method})
            try:
                response = await call_next(request)
            except Exception as exc:
                fail(span, "http_500")
                attributes(span, **{"error.type": type(exc).__name__[:80]})
                response = JSONResponse(status_code=500, content={"detail": "内部服务器错误"})
            route = request.scope.get("route")
            attributes(
                span,
                **{
                    "http.route": getattr(route, "path", "/unmatched"),
                    "http.status_code": response.status_code,
                },
            )
            if response.status_code >= 400:
                fail(span, f"http_{response.status_code}")
            response.headers["X-Request-ID"] = f"{span.get_span_context().trace_id:032x}"
            return response

    @application.get("/api/v1/health/live", response_model=HealthResponse, tags=["health"])
    def live() -> HealthResponse:
        return HealthResponse(status="ok", component="api")

    @application.get(
        "/api/v1/health/ready",
        response_model=HealthResponse,
        responses={503: {"model": HealthResponse}},
        tags=["health"],
    )
    def ready(response: Response) -> HealthResponse:
        if worker_is_ready(config.data_dir, config.worker_stale_after):
            return HealthResponse(status="ok", component="worker")
        response.status_code = 503
        return HealthResponse(status="unavailable", component="worker")

    return application


app = create_app()
