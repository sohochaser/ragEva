"""OpenTelemetry setup and a strict attribute boundary for business spans."""

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from typing import Any

from opentelemetry import context, propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

from backend.config import Settings

_setup_lock = Lock()
_configured = False
_ATTRIBUTES = frozenset(
    {
        "run.id",
        "generation.id",
        "batch.id",
        "job.id",
        "case.id",
        "attempt.number",
        "slot.index",
        "operation",
        "status",
        "error.code",
        "model.id",
        "metric",
        "token.input",
        "token.output",
        "elapsed.ms",
        "count",
        "protocol",
        "dataset.id",
        "collection.id",
        "target.id",
    }
)


def configure_tracing(settings: Settings, service: str) -> None:
    global _configured
    with _setup_lock:
        if _configured:
            return
        provider = TracerProvider(resource=Resource.create({"service.name": service}))
        if settings.otlp_traces_endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_traces_endpoint))
            )
        trace.set_tracer_provider(provider)
        _configured = True


def tracer() -> trace.Tracer:
    return trace.get_tracer("rageva")


@contextmanager
def business_span(name: str) -> Iterator[Span]:
    with tracer().start_as_current_span(
        name, record_exception=False, set_status_on_exception=False
    ) as active:
        yield active


def attributes(span: Span, **values: Any) -> None:
    unknown = set(values) - _ATTRIBUTES
    if unknown:
        raise ValueError(f"Disallowed trace attributes: {sorted(unknown)}")
    for key, value in values.items():
        if value is not None and isinstance(value, (str, int, float, bool)):
            span.set_attribute(key, value)


def fail(span: Span, code: str) -> None:
    # Store only controlled error codes; exception messages may include request content.
    category = code.split(":", 1)[0]
    allowed_prefixes = (
        "model_",
        "invalid_",
        "missing_",
        "scoring_",
        "collection_",
        "generation_",
        "stream_",
        "call_",
        "worker_",
        "http_",
        "incomplete_",
    )
    safe_code = (
        category
        if category.isascii()
        and category.replace("_", "").isalnum()
        and (
            category.startswith(allowed_prefixes)
            or category in {"timeout", "connection_error", "metric_failed"}
        )
        else "operation_error"
    )
    attributes(span, **{"status": "failed", "error.code": safe_code[:80]})
    span.set_status(Status(StatusCode.ERROR))


def carrier() -> dict[str, str]:
    result: dict[str, str] = {}
    propagate.inject(result)
    return result


@contextmanager
def received(carried: dict[str, str] | None) -> Iterator[None]:
    token = context.attach(propagate.extract(carried or {}))
    try:
        yield
    finally:
        context.detach(token)
