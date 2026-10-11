"""OpenTelemetry setup and a strict attribute boundary for business spans."""

import logging
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from typing import Any

from opentelemetry import context, propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

from backend.adapters.request_log_store import RequestLogStore
from backend.config import Settings

_setup_lock = Lock()
_configured = False
_request_log_store: ContextVar[RequestLogStore | None] = ContextVar(
    "request_log_store", default=None
)
_logger = logging.getLogger(__name__)
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
        "http.method",
        "http.route",
        "http.status_code",
        "error.type",
    }
)
_SAFE_ERROR_CODES = frozenset(
    {
        "call_error",
        "collection_error",
        "connection_error",
        "generation_error",
        "generation_worker_error",
        "incomplete_stream",
        "invalid_answer_delta",
        "invalid_content_type",
        "invalid_error_event",
        "invalid_event_json",
        "invalid_event_payload",
        "invalid_json",
        "invalid_response",
        "invalid_score",
        "invalid_usage",
        "metric_failed",
        "missing_answer",
        "missing_completed",
        "missing_contexts",
        "missing_generation_dependency",
        "missing_reference_answer",
        "model_error",
        "model_unavailable",
        "operation_error",
        "scoring_error",
        "stream_error",
        "timeout",
    }
)


class RequestLogProcessor(SpanProcessor):
    def on_end(self, span: ReadableSpan) -> None:
        if span.instrumentation_scope is None or span.instrumentation_scope.name != "rageva":
            return
        store = _request_log_store.get()
        if store is not None:
            try:
                store.record_span(span, _ATTRIBUTES)
            except sqlite3.Error:
                _logger.warning("Request log persistence failed")


@contextmanager
def request_log_scope(store: RequestLogStore) -> Iterator[None]:
    token = _request_log_store.set(store)
    try:
        yield
    finally:
        _request_log_store.reset(token)


def configure_tracing(settings: Settings, service: str) -> None:
    global _configured
    with _setup_lock:
        if _configured:
            return
        provider = TracerProvider(resource=Resource.create({"service.name": service}))
        provider.add_span_processor(RequestLogProcessor())
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
        try:
            yield active
        except Exception as exc:
            status = getattr(active, "status", None)
            if status is None or status.status_code != StatusCode.ERROR:
                fail(active, "operation_error")
            attributes(active, **{"error.type": type(exc).__name__[:80]})
            raise


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
    safe_code = (
        category
        if category in _SAFE_ERROR_CODES or re.fullmatch(r"http_[1-5][0-9]{2}", category)
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
