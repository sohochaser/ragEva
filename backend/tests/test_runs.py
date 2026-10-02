import io
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.config import Settings
from backend.domain.datasets import ReferenceChunk
from backend.domain.matching import CandidatePair
from backend.domain.predictions import PredictedChunk
from backend.domain.retrieval_scoring import score_retrieval


class FakeEncoder:
    def __init__(self, model_name: str, cache_dir: Path, model_path: Path | None, offline: bool):
        self.model_id = model_name

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        if "bad" in texts:
            raise RuntimeError("simulated encoding failure")
        return [np.array([1.0, 0.0], dtype=np.float32) for _ in texts]


def api_with_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str]:
    from backend.api import runs

    monkeypatch.setattr(runs, "worker_is_ready", lambda *_: True)
    monkeypatch.setattr(runs, "score_run_task", lambda _run_id: None)
    api = TestClient(create_app(Settings(data_dir=tmp_path)))
    gold_rows = [
        {
            "case_id": "q1",
            "question": "Q1",
            "reference_chunks": [{"text": "good", "document_id": "d"}],
        },
        {"case_id": "q2", "question": "Q2", "reference_answer": "A2"},
    ]
    dataset = api.post(
        "/api/v1/datasets/import",
        data={"dataset_name": "gold"},
        files={
            "file": (
                "gold.jsonl",
                io.BytesIO("\n".join(json.dumps(row) for row in gold_rows).encode()),
            )
        },
    ).json()
    prediction_rows = [
        {"case_id": "q1", "contexts": [{"text": "good", "document_id": "d"}]},
        {"case_id": "q2", "contexts": [{"text": "other", "document_id": "d"}]},
    ]
    batch = api.post(
        "/api/v1/predictions/import",
        data={"dataset_id": dataset["dataset_id"], "evaluation_type": "retrieval"},
        files={
            "file": (
                "pred.jsonl",
                io.BytesIO("\n".join(json.dumps(row) for row in prediction_rows).encode()),
            )
        },
    ).json()
    return api, batch["id"]


def create_run(api: TestClient, batch_id: str) -> dict[str, object]:
    response = api.post(
        "/api/v1/runs",
        json={
            "prediction_batch_id": batch_id,
            "model_name": "fake-v1",
            "threshold": 0.8,
            "metrics": ["precision", "map", "ndcg"],
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_async_run_progress_results_and_duplicate_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.worker.run_processor import process_run

    api, batch_id = api_with_batch(tmp_path, monkeypatch)
    created = create_run(api, batch_id)
    run_id = str(created["id"])
    assert created["status"] == "queued"
    assert created["processed_count"] == 0

    process_run(run_id, tmp_path, encoder_factory=FakeEncoder)
    result = api.get(f"/api/v1/runs/{run_id}").json()
    assert result["status"] == "completed"
    assert result["processed_count"] == 2
    assert result["success_count"] == 1
    assert result["not_applicable_count"] == 1
    assert result["aggregate"]["map_at_k"]["10"] == 1
    assert result["aggregate"]["precision_at_k"]["10"] == 0.1
    detail = api.get(f"/api/v1/runs/{run_id}/cases").json()
    assert [item["status"] for item in detail["cases"]] == ["success", "not_applicable"]
    assert detail["cases"][0]["score"]["scores"]["10"]["matches"][0]["reference_index"] == 0
    assert detail["cases"][0]["score"]["model_id"] == "fake-v1"

    process_run(run_id, tmp_path, encoder_factory=FakeEncoder)
    assert api.get(f"/api/v1/runs/{run_id}").json() == result
    assert len(api.get("/api/v1/runs").json()) == 1


def test_cancel_queued_run_leaves_no_success_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.worker.run_processor import process_run

    api, batch_id = api_with_batch(tmp_path, monkeypatch)
    run_id = str(create_run(api, batch_id)["id"])
    cancelled = api.post(f"/api/v1/runs/{run_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    process_run(run_id, tmp_path, encoder_factory=FakeEncoder)
    assert api.get(f"/api/v1/runs/{run_id}").json()["success_count"] == 0
    assert all(
        item["status"] == "cancelled"
        for item in api.get(f"/api/v1/runs/{run_id}/cases").json()["cases"]
    )


def test_cancel_running_run_preserves_completed_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.adapters.run_store import RunStore

    api, batch_id = api_with_batch(tmp_path, monkeypatch)
    run_id = str(create_run(api, batch_id)["id"])
    store = RunStore(tmp_path)
    assert store.claim(run_id)
    score = score_retrieval(
        [ReferenceChunk("good", "d")],
        [PredictedChunk("good", "d")],
        [CandidatePair(0, 0, 1.0, True, "candidate")],
        "fake-v1",
        0.8,
    )
    assert store.record_case(run_id, "q1", "success", score=asdict(score))
    requested = api.post(f"/api/v1/runs/{run_id}/cancel").json()
    assert requested["status"] == "running"
    assert requested["cancel_requested"] is True
    assert store.record_case(run_id, "q2", "not_applicable") is False
    store.fail_pending(run_id, "model_unavailable")
    store.finish(run_id)
    result = api.get(f"/api/v1/runs/{run_id}").json()
    assert result["status"] == "cancelled"
    assert result["success_count"] == 1
    assert result["cancelled_count"] == 1


def test_case_failure_is_isolated_and_excluded_from_average(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.worker.run_processor import process_run

    api, batch_id = api_with_batch(tmp_path, monkeypatch)
    run_id = str(create_run(api, batch_id)["id"])
    process_run(run_id, tmp_path, encoder_factory=FakeEncoder)
    assert api.get(f"/api/v1/runs/{run_id}").json()["status"] == "completed"

    # A second batch with an encoding failure leaves its other case intact.
    dataset_id = api.get(f"/api/v1/predictions/{batch_id}").json()["dataset_id"]
    second_batch = api.post(
        "/api/v1/predictions/import",
        data={"dataset_id": dataset_id, "evaluation_type": "retrieval"},
        files={
            "file": (
                "bad.jsonl",
                io.BytesIO(
                    b'{"case_id":"q1","contexts":[{"text":"bad","document_id":"d"}]}\n'
                    b'{"case_id":"q2","contexts":[{"text":"other","document_id":"d"}]}'
                ),
            )
        },
    ).json()
    second_id = str(create_run(api, second_batch["id"])["id"])
    process_run(second_id, tmp_path, encoder_factory=FakeEncoder)
    result = api.get(f"/api/v1/runs/{second_id}").json()
    assert result["status"] == "failed"
    assert result["failed_count"] == 1
    assert result["not_applicable_count"] == 1
    assert result["aggregate"]["map_at_k"]["10"] is None


def test_missing_worker_or_mismatched_batch_returns_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.api import runs

    api, batch_id = api_with_batch(tmp_path, monkeypatch)
    monkeypatch.setattr(runs, "worker_is_ready", lambda *_: False)
    assert (
        api.post(
            "/api/v1/runs",
            json={
                "prediction_batch_id": batch_id,
                "model_name": "fake",
                "threshold": 0.8,
                "metrics": ["map"],
            },
        ).status_code
        == 503
    )
    monkeypatch.setattr(runs, "worker_is_ready", lambda *_: True)
    assert (
        api.post(
            "/api/v1/runs",
            json={
                "prediction_batch_id": "missing",
                "model_name": "fake",
                "threshold": 0.8,
                "metrics": ["map"],
            },
        ).status_code
        == 404
    )
