"""Versioned management API and health contract."""

from typing import Literal

from fastapi import FastAPI, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.api.datasets import create_dataset_router
from backend.api.document_collections import create_document_collection_router
from backend.api.generations import create_generation_router
from backend.api.matching import create_matching_router
from backend.api.online_models import create_model_router
from backend.api.predictions import create_prediction_router
from backend.api.runs import create_run_router
from backend.api.scenarios import create_scenario_router
from backend.api.targets import create_target_job_router, create_target_router
from backend.config import Settings
from backend.health import worker_is_ready
from backend.tracing import configure_tracing


class HealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    component: Literal["api", "worker"]


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    configure_tracing(config, "rageva-api")
    application = FastAPI(title="ragEva API", version="0.1.0")
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

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> Response:
        if request.url.path.startswith("/api/v1/online-models"):
            details = [
                {key: value for key, value in issue.items() if key in {"type", "loc", "msg"}}
                for issue in error.errors()
            ]
            return JSONResponse(status_code=422, content={"detail": details})
        return await request_validation_exception_handler(request, error)

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
