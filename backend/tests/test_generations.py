import json
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.adapters.document_store import DocumentStore
from backend.adapters.model_store import OnlineModelStore
from backend.api.main import create_app
from backend.config import Settings
from backend.domain.chunk_manifests import ManifestChunk
from backend.domain.generation import (
    PROMPT_VERSION,
    multi_chunk_target,
    plan_slots,
    reference_chunks,
)
from backend.worker.generation_processor import process_generation


def setup_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    chunks: int = 4,
    target_count: int = 3,
    ratio: float = 0.5,
    max_calls: int | None = None,
    max_concurrency: int = 2,
) -> tuple[TestClient, str]:
    from backend.api import generations

    collection = DocumentStore(tmp_path).create_from_chunks(
        "来源",
        [ManifestChunk(i, "doc-a" if i < 2 else "doc-b", f"fact {i}") for i in range(chunks)],
    )
    model = OnlineModelStore(tmp_path).create(
        "生成模型", "https://model.example/v1", "generator-v1", "private-token", 2
    )
    monkeypatch.setattr(generations, "worker_is_ready", lambda *_: True)
    monkeypatch.setattr(generations, "generate_candidates_task", lambda _id: None)
    api = TestClient(create_app(Settings(data_dir=tmp_path)))
    response = api.post(
        f"/api/v1/document-collections/{collection['id']}/generations",
        json={
            "model_id": model["id"],
            "target_count": target_count,
            "multi_chunk_ratio": ratio,
            "language": "中文",
            "question_type": "事实问答",
            "instructions": "简洁",
            "max_calls": max_calls,
            "max_concurrency": max_concurrency,
        },
    )
    assert response.status_code == 202, response.text
    assert "private-token" not in response.text
    return api, response.json()["id"]


def test_source_allocation_covers_documents_and_preserves_relevance_order() -> None:
    chunks = [
        {"position": i, "document_id": "doc-a" if i < 2 else "doc-b", "text": f"fact {i}"}
        for i in range(4)
    ]
    slots, unavailable = plan_slots(chunks, 2, 1)
    assert unavailable == 0
    assert [slot.sources[0]["position"] for slot in slots] == [0, 2]
    assert reference_chunks((2, 0), slots[0].sources, True) == [
        {"document_id": "doc-b", "text": "fact 2"},
        {"document_id": "doc-a", "text": "fact 0"},
    ]


def test_quota_sources_prompt_snapshot_and_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api, run_id = setup_run(tmp_path, monkeypatch)
    seen: list[dict[str, Any]] = []
    active = 0
    peak = 0
    lock = threading.Lock()

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        assert request.headers["authorization"] == "Bearer private-token"
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        prompt = json.loads(body["messages"][1]["content"])
        with lock:
            active += 1
            peak = max(peak, active)
            seen.append(prompt)
        time.sleep(0.01)
        with lock:
            active -= 1
        positions = [item["position"] for item in prompt["sources"]]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "question": f"Question {positions[0]}",
                                    "reference_answer": "Grounded answer",
                                    "support_positions": positions,
                                }
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            },
        )

    def factory() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(respond))

    process_generation(run_id, tmp_path, client_factory=factory)
    process_generation(run_id, tmp_path, client_factory=factory)
    run = api.get(f"/api/v1/generations/{run_id}").json()
    candidates = api.get(f"/api/v1/generations/{run_id}/candidates").json()
    assert run["status"] == "completed"
    assert run["target_multi_count"] == multi_chunk_target(3, 0.5) == 2
    assert run["actual_count"] == 3
    assert run["actual_multi_count"] == 2
    assert run["attempted_count"] == 3
    assert run["config"]["prompt_version"] == PROMPT_VERSION
    assert [item["multi_chunk"] for item in candidates] == [True, True, False]
    assert [len(item["reference_chunks"]) for item in candidates] == [2, 2, 1]
    assert candidates[0]["reference_chunks"] == [
        {"document_id": "doc-a", "text": "fact 0"},
        {"document_id": "doc-b", "text": "fact 2"},
    ]
    assert all(item["status"] == "pending_review" for item in candidates)
    assert sorted(item["required_support_chunks"] for item in seen) == [1, 2, 2]
    assert max(item["sources"][0]["position"] for item in seen) >= 2
    assert peak <= 2
    assert "private-token" not in api.get("/api/v1/generations").text


def test_multi_chunk_shortage_preserves_single_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api, run_id = setup_run(tmp_path, monkeypatch, chunks=1, target_count=4, ratio=0.5)

    def respond(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(json.loads(request.content)["messages"][1]["content"])
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "question": "What fact?",
                                    "reference_answer": "fact 0",
                                    "support_positions": [prompt["sources"][0]["position"]],
                                }
                            )
                        }
                    }
                ]
            },
        )

    process_generation(
        run_id,
        tmp_path,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(respond)),
    )
    run = api.get(f"/api/v1/generations/{run_id}").json()
    assert run["status"] == "partial"
    assert run["actual_count"] == 2
    assert run["actual_multi_count"] == 0
    assert run["target_multi_count"] == 2
    assert run["shortfall_reasons"] == ["insufficient_source_chunks"]
    assert len(api.get(f"/api/v1/generations/{run_id}/candidates").json()) == 2


def test_bad_model_output_stops_at_call_limit_and_keeps_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api, run_id = setup_run(tmp_path, monkeypatch, chunks=2, target_count=1, ratio=1, max_calls=2)
    calls = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "question": "Q",
                                    "reference_answer": "A",
                                    "support_positions": [0],
                                }
                            )
                        }
                    }
                ]
            },
        )

    process_generation(
        run_id,
        tmp_path,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(respond)),
    )
    run = api.get(f"/api/v1/generations/{run_id}").json()
    assert calls == 2
    assert run["status"] == "failed"
    assert run["attempted_count"] == 2
    assert run["attempt_errors"] == {"insufficient_multi_chunk_support": 2}
    assert run["shortfall_reasons"] == ["call_limit_reached", "model_or_validation_errors"]
    assert api.get(f"/api/v1/generations/{run_id}/candidates").json() == []


def test_generation_api_rejects_invalid_inputs_and_missing_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api, run_id = setup_run(tmp_path, monkeypatch, target_count=1, ratio=0)
    run = api.get(f"/api/v1/generations/{run_id}").json()
    path = f"/api/v1/document-collections/{run['collection_id']}/generations"
    model_id = run["config"]["model_id"]
    assert (
        api.post(
            path,
            json={
                "model_id": model_id,
                "target_count": 1,
                "multi_chunk_ratio": 1.2,
                "language": "中文",
                "question_type": "问答",
            },
        ).status_code
        == 422
    )
    assert (
        api.post(
            path,
            json={
                "model_id": model_id,
                "target_count": 2,
                "multi_chunk_ratio": 0,
                "language": "中文",
                "question_type": "问答",
                "max_calls": 1,
            },
        ).status_code
        == 422
    )
    assert (
        api.post(
            "/api/v1/document-collections/missing/generations",
            json={
                "model_id": model_id,
                "target_count": 1,
                "multi_chunk_ratio": 0,
                "language": "中文",
                "question_type": "问答",
            },
        ).status_code
        == 404
    )
    assert api.get("/api/v1/generations/missing").status_code == 404
    assert api.get("/api/v1/generations/missing/candidates").status_code == 404
