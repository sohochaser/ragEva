import io
import json
from dataclasses import asdict
from pathlib import Path

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.config import Settings
from backend.worker.run_processor import process_run


class FakeEncoder:
    calls = 0

    def __init__(self, model_name: str, _cache: Path, _path: Path | None, _offline: bool):
        type(self).calls += 1
        self.model_id = model_name

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        return [np.array([1.0, 0.0], dtype=np.float32) for _ in texts]


def test_rescore_reuses_saved_matching_or_recalculates_for_new_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.api import runs

    monkeypatch.setattr(runs, "worker_is_ready", lambda *_: True)
    monkeypatch.setattr(runs, "score_run_task", lambda _run_id, _context=None: None)
    api = TestClient(create_app(Settings(data_dir=tmp_path)))
    dataset = api.post(
        "/api/v1/datasets/import",
        data={"dataset_name": "gold"},
        files={
            "file": (
                "gold.jsonl",
                io.BytesIO(
                    json.dumps(
                        {
                            "case_id": "q1",
                            "question": "Q1",
                            "reference_chunks": [{"text": "evidence", "document_id": "d"}],
                        }
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
                    json.dumps(
                        {
                            "case_id": "q1",
                            "contexts": [{"text": "evidence", "document_id": "d"}],
                        }
                    ).encode()
                ),
            )
        },
    ).json()
    created = api.post(
        "/api/v1/runs",
        json={"prediction_batch_id": batch["id"], "model_name": "fake", "threshold": 0.8},
    )
    assert created.status_code == 202, created.text
    source_id = created.json()["id"]
    assert api.post(f"/api/v1/runs/{source_id}/rescore", json={}).status_code == 422
    FakeEncoder.calls = 0
    process_run(source_id, tmp_path, encoder_factory=FakeEncoder)
    assert FakeEncoder.calls == 1
    original = api.get(f"/api/v1/runs/{source_id}").json()
    original_case = api.get(f"/api/v1/runs/{source_id}/cases").json()["cases"][0]

    reused_response = api.post(f"/api/v1/runs/{source_id}/rescore", json={})
    assert reused_response.status_code == 202, reused_response.text
    reused_id = reused_response.json()["id"]
    assert reused_response.json()["prediction_batch_id"] == batch["id"]
    assert reused_response.json()["config"]["reuse_retrieval_from_run_id"] == source_id
    process_run(reused_id, tmp_path, encoder_factory=FakeEncoder)
    assert FakeEncoder.calls == 1
    reused = api.get(f"/api/v1/runs/{reused_id}").json()
    assert reused["status"] == "completed"
    assert reused["model_id"] == original["model_id"]
    assert (
        api.get(f"/api/v1/runs/{reused_id}/cases").json()["cases"][0]["score"]
        == (original_case["score"])
    )

    changed_response = api.post(f"/api/v1/runs/{source_id}/rescore", json={"threshold": 1.0})
    assert changed_response.status_code == 202, changed_response.text
    changed_id = changed_response.json()["id"]
    assert "reuse_retrieval_from_run_id" not in changed_response.json()["config"]
    process_run(changed_id, tmp_path, encoder_factory=FakeEncoder)
    assert FakeEncoder.calls == 2
    changed_case = api.get(f"/api/v1/runs/{changed_id}/cases").json()["cases"][0]
    assert changed_case["score"]["threshold"] == 1.0
    assert api.get(f"/api/v1/runs/{source_id}").json() == original
    assert api.get(f"/api/v1/runs/{source_id}/cases").json()["cases"][0] == original_case
    assert api.get(f"/api/v1/predictions/{batch['id']}").status_code == 200
    assert api.post("/api/v1/runs/missing/rescore", json={}).status_code == 404
    assert (
        api.post(
            f"/api/v1/runs/{source_id}/rescore", json={"match_rule_version": "future"}
        ).status_code
        == 422
    )


def test_rescore_uses_new_scenario_snapshot_without_changing_old_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.api import runs

    monkeypatch.setattr(runs, "worker_is_ready", lambda *_: True)
    monkeypatch.setattr(runs, "score_run_task", lambda _run_id, _context=None: None)
    api = TestClient(create_app(Settings(data_dir=tmp_path)))
    dataset = api.post(
        "/api/v1/datasets/import",
        data={"dataset_name": "gold"},
        files={
            "file": (
                "gold.jsonl",
                io.BytesIO(b'{"case_id":"q1","question":"Q","reference_answer":"A"}'),
            )
        },
    ).json()
    batch = api.post(
        "/api/v1/predictions/import",
        data={"dataset_id": dataset["dataset_id"], "evaluation_type": "answer"},
        files={
            "file": (
                "pred.jsonl",
                io.BytesIO(
                    b'{"case_id":"q1","answer":"A","contexts":[{"text":"A","document_id":"d"}]}'
                ),
            )
        },
    ).json()
    scenario = api.post(
        "/api/v1/scenarios",
        json={"name": "support", "faithfulness": "old", "relevance": "old", "correctness": "old"},
    ).json()
    model = api.post(
        "/api/v1/online-models",
        json={"name": "judge", "base_url": "https://model.example/v1", "model_name": "fake"},
    ).json()
    source = api.post(
        "/api/v1/runs",
        json={
            "prediction_batch_id": batch["id"],
            "mode": "answer",
            "scenario_id": scenario["scenario_id"],
            "scenario_version": 1,
            "judge_model_id": model["id"],
        },
    ).json()
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        criteria = json.loads(json.loads(request.content)["messages"][1]["content"])["criteria"]
        calls.append(criteria)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps({"score": 0.5, "reason": criteria})}}
                ]
            },
        )

    def client_factory() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(respond))

    process_run(source["id"], tmp_path, client_factory=client_factory)
    original = api.get(f"/api/v1/runs/{source['id']}").json()
    original_case = api.get(f"/api/v1/runs/{source['id']}/cases").json()["cases"][0]
    updated = api.put(
        f"/api/v1/scenarios/{scenario['scenario_id']}",
        json={"faithfulness": "new", "relevance": "new", "correctness": "new"},
    )
    assert updated.status_code == 200
    changed = api.post(f"/api/v1/runs/{source['id']}/rescore", json={"scenario_version": 2})
    assert changed.status_code == 202, changed.text
    changed_id = changed.json()["id"]
    assert changed.json()["prediction_batch_id"] == batch["id"]
    assert changed.json()["config"]["answer"]["criteria"]["relevance"] == "new"
    process_run(changed_id, tmp_path, client_factory=client_factory)
    changed_case = api.get(f"/api/v1/runs/{changed_id}/cases").json()["cases"][0]
    assert changed_case["answer_metrics"]["relevance"]["reason"] == "new"
    assert original_case["answer_metrics"]["relevance"]["reason"] == "old"
    assert api.get(f"/api/v1/runs/{source['id']}").json() == original
    assert api.get(f"/api/v1/runs/{source['id']}/cases").json()["cases"][0] == original_case
    assert calls == ["old"] * 3 + ["new"] * 3


def test_partial_reuse_recalculates_when_model_fingerprint_changed(tmp_path: Path) -> None:
    from backend.adapters.dataset_store import DatasetStore
    from backend.adapters.prediction_store import PredictionStore
    from backend.adapters.run_store import RunStore
    from backend.domain.datasets import EvaluationCase, ReferenceChunk
    from backend.domain.matching import CandidatePair
    from backend.domain.predictions import PredictedChunk, Prediction
    from backend.domain.retrieval_scoring import score_retrieval

    class NewEncoder(FakeEncoder):
        def __init__(self, name: str, cache: Path, path: Path | None, offline: bool):
            super().__init__(name, cache, path, offline)
            self.model_id = "new-fingerprint"

    dataset = DatasetStore(tmp_path).import_cases(
        "gold",
        None,
        "gold.jsonl",
        [
            EvaluationCase(case_id, case_id, None, (ReferenceChunk("evidence", "d"),))
            for case_id in ("q1", "q2")
        ],
    )
    batch = PredictionStore(tmp_path).import_batch(
        dataset["dataset_id"],
        1,
        None,
        "pred.jsonl",
        "retrieval",
        [
            Prediction(case_id, None, (PredictedChunk("evidence", "d"),), None)
            for case_id in ("q1", "q2")
        ],
        None,
    )
    store = RunStore(tmp_path)
    source = store.create_run(batch["id"], "fake", None, False, 0.8, ["map"])
    assert store.claim(source["id"])
    store.set_model_id(source["id"], "old-fingerprint")
    score = score_retrieval(
        [ReferenceChunk("evidence", "d")],
        [PredictedChunk("evidence", "d")],
        [CandidatePair(0, 0, 1.0, True, "candidate")],
        "old-fingerprint",
        0.8,
    )
    assert store.record_case(source["id"], "q1", "success", score=asdict(score))
    assert store.record_case(source["id"], "q2", "failed", error="temporary")
    store.finish(source["id"])
    rescored = store.create_run(
        batch["id"], "fake", None, False, 0.8, ["map"], source_run_id=source["id"]
    )
    assert rescored["config"]["reuse_retrieval_from_run_id"] == source["id"]
    process_run(rescored["id"], tmp_path, encoder_factory=NewEncoder)
    cases = store.get_cases(rescored["id"], 0, 10)["cases"]
    assert [case["score"]["model_id"] for case in cases] == [
        "new-fingerprint",
        "new-fingerprint",
    ]
    assert store.get_cases(source["id"], 0, 10)["cases"][0]["score"]["model_id"] == (
        "old-fingerprint"
    )
