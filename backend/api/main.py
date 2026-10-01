"""Versioned management API and health contract."""

from typing import Literal

from fastapi import FastAPI, Response
from pydantic import BaseModel

from backend.config import Settings
from backend.health import worker_is_ready


class HealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    component: Literal["api", "worker"]


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    application = FastAPI(title="ragEva API", version="0.1.0")

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
