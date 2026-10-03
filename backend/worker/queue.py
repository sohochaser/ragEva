"""Shared Huey queue for durable evaluation tasks."""

from huey import SqliteHuey

from backend.adapters.request_log_store import RequestLogStore
from backend.config import Settings
from backend.tracing import (
    attributes,
    business_span,
    configure_tracing,
    received,
    request_log_scope,
)

settings = Settings.from_env()
settings.data_dir.mkdir(parents=True, exist_ok=True)
huey = SqliteHuey("rageva", filename=str(settings.data_dir / "queue.sqlite3"))


@huey.task()
def score_run_task(run_id: str, trace_context: dict[str, str] | None = None) -> None:
    from backend.worker.run_processor import process_run

    configure_tracing(settings, "rageva-worker")
    with (
        request_log_scope(RequestLogStore(settings.data_dir)),
        received(trace_context),
        business_span("run.worker") as span,
    ):
        attributes(span, **{"run.id": run_id})
        process_run(run_id, settings.data_dir)


@huey.task()
def collect_target_task(job_id: str, trace_context: dict[str, str] | None = None) -> None:
    from backend.worker.target_collector import collect_target_job

    configure_tracing(settings, "rageva-worker")
    with (
        request_log_scope(RequestLogStore(settings.data_dir)),
        received(trace_context),
        business_span("target.worker") as span,
    ):
        attributes(span, **{"job.id": job_id})
        collect_target_job(job_id, settings.data_dir)


@huey.task()
def generate_candidates_task(run_id: str, trace_context: dict[str, str] | None = None) -> None:
    from backend.worker.generation_processor import process_generation

    configure_tracing(settings, "rageva-worker")
    with (
        request_log_scope(RequestLogStore(settings.data_dir)),
        received(trace_context),
        business_span("generation.worker") as span,
    ):
        attributes(span, **{"generation.id": run_id})
        process_generation(run_id, settings.data_dir)
