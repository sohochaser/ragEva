"""Trace propagation, privacy, and retention contracts."""

import io
import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from backend.adapters.dataset_store import DatasetStore
from backend.adapters.request_log_store import RequestLogStore
from backend.adapters.target_store import TargetStore
from backend.adapters.trace_store import TraceStore
from backend.api.main import create_app
from backend.config import Settings
from backend.domain.datasets import EvaluationCase, ReferenceChunk
from backend.tracing import attributes, business_span, fail, received, request_log_scope, tracer
from backend.worker.run_processor import process_run
from backend.worker.target_collector import collect_target_job


class Encoder:
    def __init__(self, *_args: object) -> None:
        self.model_id = "fake-model"

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        if "BAD" in texts:
            raise RuntimeError("PRIVATE_RESPONSE")
        return [np.array([1.0, 0.0], dtype=np.float32) for _ in texts]


def test_queue_context_case_spans_and_sensitive_field_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.api import runs

    settings = Settings(
        data_dir=tmp_path,
        jaeger_url="http://127.0.0.1:9",
        otlp_traces_endpoint="http://127.0.0.1:9/v1/traces",
    )
    api = TestClient(create_app(settings))
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    queued: list[dict[str, str]] = []
    monkeypatch.setattr(runs, "worker_is_ready", lambda *_: True)
    monkeypatch.setattr(runs, "score_run_task", lambda _id, carried: queued.append(carried))

    dataset = api.post(
        "/api/v1/datasets/import",
        data={"dataset_name": "test"},
        files={
            "file": (
                "gold.jsonl",
                io.BytesIO(
                    "\n".join(
                        json.dumps(row)
                        for row in [
                            {
                                "case_id": "c1",
                                "question": "TOP_SECRET_QUESTION",
                                "reference_chunks": [
                                    {"document_id": "d1", "text": "TOP_SECRET_CHUNK"}
                                ],
                            },
                            {
                                "case_id": "c2",
                                "question": "PRIVATE_QUESTION",
                                "reference_chunks": [{"document_id": "d1", "text": "BAD"}],
                            },
                        ]
                    ).encode()
                ),
            )
        },
    ).json()
    batch = api.post(
        "/api/v1/predictions/import",
        data={"dataset_id": dataset["dataset_id"], "evaluation_type": "retrieval"},
        files={
            "file": (
                "pred.jsonl",
                io.BytesIO(
                    "\n".join(
                        json.dumps(row)
                        for row in [
                            {
                                "case_id": "c1",
                                "contexts": [{"document_id": "d1", "text": "TOP_SECRET_CHUNK"}],
                            },
                            {"case_id": "c2", "contexts": [{"document_id": "d1", "text": "BAD"}]},
                        ]
                    ).encode()
                ),
            )
        },
    ).json()
    created = api.post("/api/v1/runs", json={"prediction_batch_id": batch["id"]})
    assert created.status_code == 202
    run = created.json()
    request_id = created.headers["x-request-id"]
    assert request_id == run["trace"]["trace_id"]
    assert run["trace"]["status"] == "available"
    assert run["dataset_trace"]["trace_id"] != run["trace"]["trace_id"]
    assert run["prediction_trace"]["trace_id"] != run["trace"]["trace_id"]
    assert queued[0]["traceparent"].split("-")[1] == run["trace"]["trace_id"]

    with (
        request_log_scope(RequestLogStore(tmp_path)),
        received(queued[0]),
        tracer().start_as_current_span("run.worker"),
    ):
        process_run(run["id"], tmp_path, encoder_factory=Encoder)

    log_response = api.get(f"/api/v1/request-logs/{request_id}")
    assert log_response.status_code == 200
    request_log = log_response.json()
    assert request_log["status"] == "failed"
    assert {step["name"] for step in request_log["spans"]} >= {
        "http.request",
        "run.create",
        "run.worker",
        "run.case",
        "retrieval.embed",
        "run.persist",
    }
    errors = [step for step in request_log["spans"] if step["status"] == "failed"]
    assert any(step["error_code"] == "model_error" for step in errors)
    assert all(step["error_detail"] for step in errors)
    assert "PRIVATE_RESPONSE" not in log_response.text
    assert "TOP_SECRET" not in log_response.text
    assert api.get("/api/v1/request-logs").json()[0]["request_id"] == request_id

    cases = api.get(f"/api/v1/runs/{run['id']}/cases").json()["cases"]
    case = cases[0]
    assert case["status"] == "success"
    assert cases[1]["status"] == "failed"
    assert case["trace"]["trace_id"] == run["trace"]["trace_id"]
    spans = [
        span
        for span in exporter.get_finished_spans()
        if span.context.trace_id == int(run["trace"]["trace_id"], 16)
    ]
    names = {span.name for span in spans}
    assert {
        "run.create",
        "run.worker",
        "run.case",
        "retrieval.embed",
        "retrieval.match",
        "run.persist",
    } <= names
    assert any(
        span.name == "run.case" and span.status.status_code == trace.StatusCode.ERROR
        for span in spans
    )
    assert str({span.name: span.attributes for span in spans}).find("TOP_SECRET") == -1
    assert api.get(f"/api/v1/runs/{run['id']}/export").json()["cases"][0]["trace"] == case["trace"]


def test_trace_retention_and_unavailable_jaeger_do_not_hide_evidence(tmp_path: Path) -> None:
    assert Settings.from_env({"RAGEVA_DATA_DIR": str(tmp_path)}).trace_retention_days == 30
    assert (
        Settings.from_env(
            {"RAGEVA_DATA_DIR": str(tmp_path), "RAGEVA_TRACE_RETENTION_DAYS": "7"}
        ).trace_retention_days
        == 7
    )
    store = TraceStore(tmp_path)
    with tracer().start_as_current_span("test") as span:
        store.record("run", "one", span)
    settings = Settings(
        data_dir=tmp_path,
        jaeger_url="http://127.0.0.1:9",
        otlp_traces_endpoint="http://127.0.0.1:9/v1/traces",
    )
    reference = store.get("run", "one", settings)
    assert reference is not None
    expiry = datetime.fromisoformat(reference["expires_at"])
    assert reference["url"].endswith(reference["trace_id"])
    before_expiry = store.get("run", "one", settings, expiry - timedelta(microseconds=1))
    assert before_expiry is not None and before_expiry["status"] == "available"
    expired = store.get("run", "one", settings, expiry)
    assert expired is not None and expired["status"] == "expired" and expired["url"] is None
    unconfigured = store.get("run", "one", Settings(data_dir=tmp_path))
    assert unconfigured is not None and unconfigured["status"] == "unconfigured"


def test_request_logs_include_http_errors_and_reject_unknown_ids(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path))

    @app.get("/api/v1/broken")
    def broken() -> None:
        raise RuntimeError("PRIVATE_EXCEPTION_TEXT")

    api = TestClient(app)
    response = api.post("/api/v1/runs", json={"prediction_batch_id": ""})
    assert response.status_code == 422
    request_id = response.headers["x-request-id"]
    detail = api.get(f"/api/v1/request-logs/{request_id}").json()
    assert detail["status"] == "failed"
    assert detail["http_status"] == 422
    assert detail["method"] == "POST" and detail["route"] == "/api/v1/runs"
    assert any(step["error_code"] == "http_422" for step in detail["spans"])
    assert api.get("/api/v1/request-logs/not-a-trace").status_code == 404
    assert api.get(f"/api/v1/request-logs/{'a' * 32}").status_code == 404
    assert api.get("/api/v1/request-logs").headers.get("x-request-id") is None
    failed = api.get("/api/v1/broken")
    assert failed.status_code == 500
    assert failed.headers["x-request-id"]
    log = api.get(f"/api/v1/request-logs/{failed.headers['x-request-id']}")
    assert log.json()["spans"][0]["error_detail"] == "HTTP 500 请求失败（RuntimeError）"
    assert "PRIVATE_EXCEPTION_TEXT" not in log.text


def test_target_retries_link_to_batch_and_scoring_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.api import runs, targets

    dataset = DatasetStore(tmp_path).import_cases(
        "target",
        None,
        "generated",
        [EvaluationCase("c1", "PRIVATE_QUESTION", None, (ReferenceChunk("PRIVATE_CHUNK", "d"),))],
    )
    target = TargetStore(tmp_path).create_target(
        "local", "https://example.test/rag", "PRIVATE_TOKEN", 2, 1
    )
    settings = Settings(
        data_dir=tmp_path,
        jaeger_url="http://127.0.0.1:9",
        otlp_traces_endpoint="http://127.0.0.1:9/v1/traces",
    )
    api = TestClient(create_app(settings))
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    carried: list[dict[str, str]] = []
    monkeypatch.setattr(targets, "worker_is_ready", lambda *_: True)
    monkeypatch.setattr(
        targets, "collect_target_task", lambda _id, context: carried.append(context)
    )
    job = api.post(
        "/api/v1/target-jobs",
        json={
            "target_id": target["id"],
            "dataset_id": dataset["dataset_id"],
            "dataset_version": 1,
            "evaluation_type": "retrieval",
        },
    ).json()
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.headers["authorization"] == "Bearer PRIVATE_TOKEN"
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(
            200, json={"contexts": [{"document_id": "d", "text": "PRIVATE_CHUNK"}]}
        )

    with received(carried[0]), tracer().start_as_current_span("target.worker"):
        collect_target_job(
            job["id"],
            tmp_path,
            client_factory=lambda: httpx.Client(transport=httpx.MockTransport(respond)),
        )
    complete = api.get(f"/api/v1/target-jobs/{job['id']}").json()
    assert complete["batch_id"] and complete["status"] == "completed"
    case = api.get(f"/api/v1/target-jobs/{job['id']}/cases").json()[0]
    assert case["trace"]["trace_id"] == job["trace"]["trace_id"]
    spans = [
        span
        for span in exporter.get_finished_spans()
        if span.context.trace_id == int(job["trace"]["trace_id"], 16)
    ]
    attempts = [span for span in spans if span.name == "target.attempt"]
    assert len(attempts) == 2
    assert attempts[0].status.status_code == trace.StatusCode.ERROR
    assert all(
        span.start_time is not None
        and span.end_time is not None
        and span.end_time > span.start_time
        for span in attempts
    )
    assert {span.name for span in spans} >= {
        "target.case",
        "target.persist",
        "target.batch.persist",
    }
    assert "PRIVATE_" not in str({span.name: span.attributes for span in spans})

    monkeypatch.setattr(runs, "worker_is_ready", lambda *_: True)
    monkeypatch.setattr(runs, "score_run_task", lambda _id, _context: None)
    run = api.post("/api/v1/runs", json={"prediction_batch_id": complete["batch_id"]}).json()
    assert run["prediction_trace"]["trace_id"] == job["trace"]["trace_id"]
    run_case = api.get(f"/api/v1/runs/{run['id']}/cases").json()["cases"][0]
    assert run_case["target_trace"]["trace_id"] == job["trace"]["trace_id"]


def test_trace_attributes_reject_body_or_auth_fields() -> None:
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with tracer().start_as_current_span("test") as span:
        with pytest.raises(ValueError, match="Disallowed"):
            attributes(span, question="secret")
        with pytest.raises(ValueError, match="Disallowed"):
            attributes(span, Authorization="Bearer secret")
        fail(span, "PRIVATE_SECRET")
        fail(span, "model_PRIVATE_TOKEN")
        fail(span, "http_PRIVATE_TOKEN")
    recorded = exporter.get_finished_spans()[-1]
    assert recorded.attributes is not None
    assert recorded.attributes["error.code"] == "operation_error"


def test_exception_details_are_not_auto_recorded() -> None:
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with pytest.raises(RuntimeError, match="PRIVATE_RESPONSE"):
        with business_span("private.failure"):
            raise RuntimeError("PRIVATE_RESPONSE")
    recorded = exporter.get_finished_spans()[-1]
    assert recorded.events == ()
    assert "PRIVATE_RESPONSE" not in str(recorded.status)


def test_exporter_failure_does_not_block_dataset_import(tmp_path: Path) -> None:
    class FailingExporter(SpanExporter):
        attempts = 0

        def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
            self.attempts += len(spans)
            return SpanExportResult.FAILURE

        def shutdown(self, timeout_millis: float = 30000) -> None:
            pass

    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    exporter = FailingExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    api = TestClient(create_app(Settings(data_dir=tmp_path)))
    imported = api.post(
        "/api/v1/datasets/import",
        data={"dataset_name": "offline-jaeger"},
        files={
            "file": (
                "gold.jsonl",
                io.BytesIO(
                    json.dumps(
                        {
                            "case_id": "c1",
                            "question": "Q",
                            "reference_answer": "A",
                        }
                    ).encode()
                ),
            )
        },
    )
    assert imported.status_code == 201
    assert exporter.attempts > 0
    dataset_id = imported.json()["dataset_id"]
    detail = api.get(f"/api/v1/datasets/{dataset_id}/versions/1")
    assert detail.status_code == 200
    assert detail.json()["cases"][0]["question"] == "Q"
