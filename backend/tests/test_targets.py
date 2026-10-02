import io
import json
import stat
import threading
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.adapters.http_target import TargetAttempt, TargetCall
from backend.api.main import create_app
from backend.config import Settings
from backend.worker.target_collector import collect_target_job


def test_target_secret_connection_test_and_json_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.api import targets

    api = TestClient(create_app(Settings(data_dir=tmp_path)))
    rows = [
        {
            "case_id": "q1",
            "question": "first",
            "reference_chunks": [{"text": "good", "document_id": "d"}],
        },
        {
            "case_id": "q2",
            "question": "second",
            "reference_chunks": [{"text": "good", "document_id": "d"}],
        },
    ]
    dataset = api.post(
        "/api/v1/datasets/import",
        data={"dataset_name": "gold"},
        files={
            "file": ("gold.jsonl", io.BytesIO("\n".join(json.dumps(row) for row in rows).encode()))
        },
    ).json()
    created = api.post(
        "/api/v1/targets",
        json={
            "name": "fake target",
            "url": "https://example.test/rag",
            "bearer_token": "private-token",
            "timeout_seconds": 2,
            "retries": 0,
        },
    )
    assert created.status_code == 201
    assert (
        api.post(
            "/api/v1/targets",
            json={
                "name": "unsafe",
                "url": "https://example.test/rag?api_key=secret",
            },
        ).status_code
        == 422
    )
    target = created.json()
    assert target["has_token"] is True
    assert "private-token" not in created.text
    assert "private-token" not in api.get("/api/v1/targets").text
    secret = tmp_path / "secrets" / "targets" / target["id"]
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600

    seen_token: list[str | None] = []

    def fake_test(
        _client: httpx.Client, _url: str, token: str | None, *_args: object
    ) -> TargetCall:
        seen_token.append(token)
        return TargetCall(
            None, (TargetAttempt(1, "http_error", 401, 1, "http_401"),), "http_401", None
        )

    monkeypatch.setattr(targets, "call_json_target", fake_test)
    tested = api.post(
        f"/api/v1/targets/{target['id']}/test",
        json={
            "case_id": "q1",
            "question": "first",
            "evaluation_type": "retrieval",
        },
    )
    assert tested.status_code == 200
    assert tested.json()["error"] == "http_401"
    assert seen_token == ["private-token"]
    assert "private-token" not in tested.text

    monkeypatch.setattr(targets, "worker_is_ready", lambda *_: True)
    monkeypatch.setattr(targets, "collect_target_task", lambda _id, _context=None: None)
    job_response = api.post(
        "/api/v1/target-jobs",
        json={
            "target_id": target["id"],
            "dataset_id": dataset["dataset_id"],
            "dataset_version": 1,
            "evaluation_type": "retrieval",
        },
    )
    assert job_response.status_code == 202, job_response.text
    job_id = job_response.json()["id"]
    requests: list[dict[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer private-token"
        body = json.loads(request.content)
        requests.append(body)
        if body["case_id"] == "q2":
            return httpx.Response(401)
        return httpx.Response(
            200,
            json={
                "contexts": [{"text": "good", "document_id": "d"}],
                "usage": {"input_tokens": 5, "output_tokens": 2},
            },
        )

    collect_target_job(
        job_id,
        tmp_path,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(respond)),
    )
    assert {item["case_id"] for item in requests} == {"q1", "q2"}
    job = api.get(f"/api/v1/target-jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert job["success_count"] == 1
    assert job["failed_count"] == 1
    cases = api.get(f"/api/v1/target-jobs/{job_id}/cases").json()
    assert cases[0]["usage"] == {"input_tokens": 5, "output_tokens": 2}
    assert cases[1]["error"] == "http_401"
    usage = api.get(f"/api/v1/target-jobs/{job_id}/usage").json()
    assert usage["call_count"] == 2
    assert usage["totals"]["input"]["actual"] == {"calls": 1, "tokens": 5}
    assert usage["totals"]["output"]["actual"] == {"calls": 1, "tokens": 2}
    assert usage["totals"]["input"]["unknown"]["calls"] == 1
    batch = api.get(f"/api/v1/predictions/{job['batch_id']}").json()
    assert batch["record_count"] == 1
    assert batch["matched_count"] == 1
    assert [item["case_id"] for item in batch["predictions"]] == ["q1"]
    assert "private-token" not in json.dumps({"job": job, "cases": cases, "batch": batch})

    # A failed target case remains visible when this batch is scored later.
    from backend.adapters.run_store import RunStore

    run = RunStore(tmp_path).create_run(job["batch_id"], "fake", None, True, 0.8, ["map"])
    result = api.get(f"/api/v1/runs/{run['id']}/cases").json()
    assert result["cases"][1]["error"] == "http_401"
    run_usage = api.get(f"/api/v1/runs/{run['id']}/usage").json()
    assert run_usage["call_count"] == 2
    assert {call["operation"] for call in run_usage["calls"]} == {"target_rag"}


def test_collector_caps_simultaneous_http_requests(tmp_path: Path) -> None:
    from backend.adapters.dataset_store import DatasetStore
    from backend.adapters.target_store import TargetStore
    from backend.domain.datasets import EvaluationCase, ReferenceChunk

    dataset = DatasetStore(tmp_path).import_cases(
        "load",
        None,
        "generated",
        [EvaluationCase(f"q{i}", f"Q{i}", None, (ReferenceChunk("A", "d"),)) for i in range(12)],
    )
    store = TargetStore(tmp_path)
    target = store.create_target("local", "https://example.test/rag", None, 2, 0)
    job = store.create_job(target["id"], dataset["dataset_id"], 1, "retrieval")
    lock = threading.Lock()
    active = 0
    maximum = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return httpx.Response(200, json={"contexts": [{"text": "A", "document_id": "d"}]})

    collect_target_job(
        job["id"],
        tmp_path,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(respond)),
    )
    assert maximum <= 4
    assert maximum > 1
    assert store.get_job(job["id"])["status"] == "completed"


def test_sse_collection_persists_equivalent_prediction_and_timings(tmp_path: Path) -> None:
    from backend.adapters.dataset_store import DatasetStore
    from backend.adapters.target_store import TargetStore
    from backend.domain.datasets import EvaluationCase, ReferenceChunk

    dataset = DatasetStore(tmp_path).import_cases(
        "stream",
        None,
        "generated",
        [EvaluationCase("q1", "Q", "A", (ReferenceChunk("context", "d"),))],
    )
    store = TargetStore(tmp_path)
    target = store.create_target("stream", "https://example.test/rag", None, 2, 0, "sse")
    assert store.get_target(target["id"])["protocol"] == "sse"
    job = store.create_job(target["id"], dataset["dataset_id"], 1, "both")

    def respond(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            text='event: answer.delta\ndata: {"text":"A"}\n\n'
            'event: contexts\ndata: {"items":[{"text":"context","document_id":"d"}]}\n\n'
            'event: completed\ndata: {"usage":{"input_tokens":2,"output_tokens":1}}\n\n',
        )

    collect_target_job(
        job["id"],
        tmp_path,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(respond)),
    )
    completed = store.get_job(job["id"])
    assert completed["status"] == "completed"
    prediction = store.get_batch(completed["batch_id"], 0, 10)["predictions"][0]
    assert prediction["answer"] == "A"
    assert prediction["contexts"][0]["text"] == "context"
    attempt = store.job_cases(job["id"])[0]["attempts"][0]
    assert attempt["ttft_ms"] is not None
    assert attempt["ttlt_ms"] is not None
    assert attempt["stream_completed_ms"] is not None
