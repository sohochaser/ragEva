import io
import json
from pathlib import Path

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.config import Settings
from backend.worker.run_processor import process_run


def test_answer_run_isolates_metrics_and_aggregates_only_valid_scores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.api import runs

    monkeypatch.setattr(runs, "worker_is_ready", lambda *_: True)
    monkeypatch.setattr(runs, "score_run_task", lambda _id, _context=None: None)
    api = TestClient(create_app(Settings(data_dir=tmp_path)))
    gold = [
        {"case_id": "q1", "question": "What?", "reference_answer": "Yes"},
        {
            "case_id": "q2",
            "question": "Why?",
            "reference_chunks": [{"text": "Other evidence", "document_id": "d"}],
        },
    ]
    dataset = api.post(
        "/api/v1/datasets/import",
        data={"dataset_name": "gold"},
        files={
            "file": ("gold.jsonl", io.BytesIO("\n".join(json.dumps(row) for row in gold).encode()))
        },
    ).json()
    predictions = [
        {"case_id": "q1", "answer": "Yes", "contexts": [{"text": "Yes", "document_id": "d"}]},
        {"case_id": "q2", "answer": "Maybe"},
    ]
    batch = api.post(
        "/api/v1/predictions/import",
        data={"dataset_id": dataset["dataset_id"], "evaluation_type": "answer"},
        files={
            "file": (
                "pred.jsonl",
                io.BytesIO("\n".join(json.dumps(row) for row in predictions).encode()),
            )
        },
    ).json()
    scenario = api.post(
        "/api/v1/scenarios",
        json={
            "name": "support",
            "faithfulness": "evidence",
            "relevance": "question",
            "correctness": "reference",
        },
    ).json()
    model = api.post(
        "/api/v1/online-models",
        json={
            "name": "judge",
            "base_url": "https://model.example/v1",
            "model_name": "judge-v1",
            "bearer_token": "secret",
        },
    ).json()
    invalid = api.post(
        "/api/v1/runs",
        json={
            "prediction_batch_id": batch["id"],
            "mode": "answer",
        },
    )
    assert invalid.status_code == 422
    created = api.post(
        "/api/v1/runs",
        json={
            "prediction_batch_id": batch["id"],
            "mode": "answer",
            "scenario_id": scenario["scenario_id"],
            "scenario_version": 1,
            "judge_model_id": model["id"],
        },
    )
    assert created.status_code == 202, created.text
    run_id = created.json()["id"]
    snapshot = created.json()["config"]["answer"]
    assert snapshot["criteria"]["relevance"] == "question"
    assert snapshot["temperature"] == 0
    assert "secret" not in created.text
    api.put(
        f"/api/v1/scenarios/{scenario['scenario_id']}",
        json={
            "faithfulness": "new",
            "relevance": "new",
            "correctness": "new",
        },
    )
    seen: list[tuple[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        payload = json.loads(request.content)
        user = json.loads(payload["messages"][1]["content"])
        seen.append((user["question"], user["metric"]))
        assert user["criteria"] in {"evidence", "question", "reference"}
        if user["question"] == "What?" and user["metric"] == "relevance":
            content = '{"score":2,"reason":"invalid"}'
        elif user["metric"] == "faithfulness":
            content = '{"score":0,"reason":"unsupported"}'
        else:
            content = '{"score":1,"reason":"valid"}'
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3},
            },
        )

    process_run(
        run_id,
        tmp_path,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(respond)),
    )
    run = api.get(f"/api/v1/runs/{run_id}").json()
    assert run["status"] == "failed"
    assert run["config"]["answer"] == snapshot
    aggregate = run["aggregate"]["answer_metrics"]
    assert aggregate["faithfulness"] == {
        "valid_count": 1,
        "failed_count": 0,
        "not_applicable_count": 1,
        "mean_score": 0,
    }
    assert aggregate["relevance"]["valid_count"] == 1
    assert aggregate["relevance"]["failed_count"] == 1
    assert aggregate["correctness"]["not_applicable_count"] == 1
    cases = api.get(f"/api/v1/runs/{run_id}/cases").json()["cases"]
    assert cases[0]["answer_metrics"]["faithfulness"]["score"] == 0
    assert cases[0]["answer_metrics"]["relevance"]["status"] == "failed"
    assert cases[0]["answer_metrics"]["relevance"]["score"] is None
    assert cases[0]["answer_metrics"]["relevance"]["error"] == "invalid_score"
    assert cases[0]["answer_metrics"]["correctness"]["usage"] == {
        "input_tokens": 11,
        "output_tokens": 3,
    }
    assert cases[1]["answer_metrics"]["faithfulness"]["status"] == "not_applicable"
    assert cases[1]["answer_metrics"]["correctness"]["reason"] == "missing_reference_answer"
    assert "answer_metrics" in api.get(f"/api/v1/runs/{run_id}/export?format=csv").text
    assert len(seen) == 4
    usage = api.get(f"/api/v1/runs/{run_id}/usage").json()
    assert usage["call_count"] == 4
    assert usage["totals"]["input"]["actual"] == {"calls": 4, "tokens": 44}
    assert usage["totals"]["output"]["actual"] == {"calls": 4, "tokens": 12}
    assert "secret" not in json.dumps(usage)
    process_run(
        run_id,
        tmp_path,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(respond)),
    )
    assert len(seen) == 4


def test_combined_run_keeps_retrieval_not_applicable_count(tmp_path: Path) -> None:
    from backend.adapters.dataset_store import DatasetStore
    from backend.adapters.model_store import OnlineModelStore
    from backend.adapters.prediction_store import PredictionStore
    from backend.adapters.run_store import RunStore
    from backend.adapters.scenario_store import ScenarioStore
    from backend.domain.datasets import EvaluationCase, ReferenceChunk
    from backend.domain.predictions import PredictedChunk, Prediction

    class FakeEncoder:
        def __init__(self, _name: str, _cache: Path, _path: Path | None, _offline: bool):
            self.model_id = "fake-vector"

        def embed(self, texts: list[str]) -> list[np.ndarray]:
            return [np.array([1.0, 0.0], dtype=np.float32) for _ in texts]

    dataset = DatasetStore(tmp_path).import_cases(
        "gold",
        None,
        "gold.jsonl",
        [
            EvaluationCase("q1", "Q1", "A1", (ReferenceChunk("evidence", "d"),)),
            EvaluationCase("q2", "Q2", "A2", None),
        ],
    )
    batch = PredictionStore(tmp_path).import_batch(
        dataset["dataset_id"],
        1,
        None,
        "pred.jsonl",
        "both",
        [
            Prediction("q1", "A1", (PredictedChunk("evidence", "d"),), None),
            Prediction("q2", "A2", (PredictedChunk("other", "d"),), None),
        ],
        None,
    )
    scenario = ScenarioStore(tmp_path).create("support", "faithful", "relevant", "correct")
    model = OnlineModelStore(tmp_path).create(
        "judge", "https://model.example/v1", "judge-v1", None, 5
    )
    answer_config = {
        "scenario_id": scenario["scenario_id"],
        "scenario_version": 1,
        "prompt_version": scenario["prompt_version"],
        "criteria": {
            metric: scenario[metric] for metric in ("faithfulness", "relevance", "correctness")
        },
        "judge_model_id": model["id"],
        "model_name": model["model_name"],
        "base_url": model["base_url"],
        "timeout_seconds": 5,
    }
    store = RunStore(tmp_path)
    run = store.create_run(
        batch["id"], "fake-vector", None, True, 0.8, ["map"], "both", answer_config
    )
    process_run(
        run["id"],
        tmp_path,
        encoder_factory=FakeEncoder,
        client_factory=lambda: httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"choices": [{"message": {"content": '{"score":0.5,"reason":"ok"}'}}]}
                )
            )
        ),
    )
    result = store.get_run(run["id"])
    assert result["status"] == "completed"
    assert result["aggregate"]["valid_count"] == 1
    assert result["aggregate"]["not_applicable_count"] == 1
    assert result["aggregate"]["answer_metrics"]["relevance"]["valid_count"] == 2
    cases = store.get_cases(run["id"], 0, 10)["cases"]
    assert cases[0]["score"] is not None
    assert cases[1]["score"] is None
    assert cases[1]["answer_metrics"]["relevance"]["score"] == 0.5
    from backend.adapters.usage_store import UsageStore

    usage = UsageStore(tmp_path).for_owner("run", run["id"])
    assert usage["totals"]["input"]["estimated"]["calls"] >= 1
    assert usage["totals"]["output"]["not_applicable"]["calls"] >= 1
    assert any(call["operation"] == "embedding" for call in usage["calls"])
