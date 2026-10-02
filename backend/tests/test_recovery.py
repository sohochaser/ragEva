import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from backend.adapters.http_target import TargetCall
from backend.adapters.model_store import OnlineModelStore
from backend.adapters.prediction_store import PredictionStore
from backend.adapters.run_store import RunStore
from backend.adapters.scenario_store import ScenarioStore
from backend.adapters.target_store import TargetStore
from backend.api.main import create_app
from backend.config import Settings
from backend.domain.datasets import EvaluationCase, ReferenceChunk
from backend.domain.predictions import PredictedChunk, Prediction
from backend.worker.__main__ import recover_work
from backend.worker.run_processor import process_run
from backend.worker.target_collector import collect_target_job


def _source(tmp_path: Path) -> tuple[str, str]:
    from backend.adapters.dataset_store import DatasetStore

    dataset = DatasetStore(tmp_path).import_cases(
        "gold",
        None,
        "source",
        [
            EvaluationCase("q1", "Q1", "A1", (ReferenceChunk("A1", "d"),)),
            EvaluationCase("q2", "Q2", "A2", (ReferenceChunk("A2", "d"),)),
            EvaluationCase("q3", "Q3", "A3", (ReferenceChunk("A3", "d"),)),
        ],
    )
    batch = PredictionStore(tmp_path).import_batch(
        dataset["dataset_id"],
        1,
        None,
        "pred",
        "answer",
        [Prediction(f"q{i}", f"A{i}", (PredictedChunk(f"A{i}", "d"),), None) for i in range(1, 4)],
        None,
    )
    return dataset["dataset_id"], batch["id"]


def _answer_config(tmp_path: Path) -> dict[str, object]:
    scenario = ScenarioStore(tmp_path).create("support", "faithful", "relevant", "correct")
    model = OnlineModelStore(tmp_path).create(
        "judge", "https://model.example/v1", "judge-v1", None, 5
    )
    return {
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


def test_recovery_reuses_saved_metric_and_resumes_pending_cases(tmp_path: Path) -> None:
    dataset_id, batch_id = _source(tmp_path)
    store = RunStore(tmp_path)
    run = store.create_run(
        batch_id, "unused", None, True, 0.8, ["map"], "answer", _answer_config(tmp_path)
    )
    run_id = run["id"]
    assert store.claim(run_id)
    store.record_answer_metric(
        run_id,
        "q1",
        "faithfulness",
        {
            "status": "success",
            "score": 0.25,
            "reason": "prior",
            "raw_response": "prior",
            "error": None,
            "usage": None,
            "model_name": "judge-v1",
            "prompt_version": "answer-eval-v1",
            "criteria": "faithful",
        },
    )
    target = TargetStore(tmp_path).create_target("rag", "https://rag.example/api", None, 2, 0)
    job = TargetStore(tmp_path).create_job(target["id"], dataset_id, 1, "answer")
    assert TargetStore(tmp_path).claim_job(job["id"])
    saved = TargetCall(Prediction("q1", "A1", None, None), (), None, None)
    TargetStore(tmp_path).record_case(job["id"], "q1", saved)

    run_tasks: list[str] = []
    target_tasks: list[str] = []
    assert recover_work(tmp_path, run_tasks.append, target_tasks.append) == (1, 1)
    assert run_tasks == [run_id]
    assert target_tasks == [job["id"]]
    calls: list[tuple[str, str]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        calls.append((payload["question"], payload["metric"]))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"score":0.5,"reason":"ok"}'}}]}
        )

    process_run(
        run_id, tmp_path, client_factory=lambda: httpx.Client(transport=httpx.MockTransport(answer))
    )
    assert store.get_run(run_id)["status"] == "completed"
    assert len(calls) == 8
    assert ("Q1", "faithfulness") not in calls
    assert (
        store.get_cases(run_id, 0, 10)["cases"][0]["answer_metrics"]["faithfulness"]["score"]
        == 0.25
    )

    target_calls: list[str] = []

    def rag(request: httpx.Request) -> httpx.Response:
        case_id = json.loads(request.content)["case_id"]
        target_calls.append(case_id)
        return httpx.Response(200, json={"answer": f"A{case_id[-1]}"})

    collect_target_job(
        job["id"], tmp_path, client_factory=lambda: httpx.Client(transport=httpx.MockTransport(rag))
    )
    job_result = TargetStore(tmp_path).get_job(job["id"])
    assert job_result["status"] == "completed"
    assert job_result["success_count"] == 3
    assert sorted(target_calls) == ["q2", "q3"]
    assert PredictionStore(tmp_path).get_batch(job_result["batch_id"], 0, 10)["record_count"] == 3


def test_target_cancel_preserves_partial_batch_and_stops_new_calls(tmp_path: Path) -> None:
    dataset_id, _ = _source(tmp_path)
    store = TargetStore(tmp_path)
    target = store.create_target("rag", "https://rag.example/api", None, 2, 0, max_concurrency=1)
    queued = store.create_job(target["id"], dataset_id, 1, "answer")
    api = TestClient(create_app(Settings(data_dir=tmp_path)))
    cancelled = api.post(f"/api/v1/target-jobs/{queued['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert store.claim_job(queued["id"]) is False
    assert store.get_job(queued["id"])["cancelled_count"] == 3

    running = store.create_job(target["id"], dataset_id, 1, "answer")
    seen: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        case_id = json.loads(request.content)["case_id"]
        seen.append(case_id)
        if case_id == "q2":
            store.cancel_job(running["id"])
        return httpx.Response(200, json={"answer": "A"})

    collect_target_job(
        running["id"],
        tmp_path,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(respond)),
    )
    result = store.get_job(running["id"])
    assert result["status"] == "cancelled"
    assert result["success_count"] == 1
    assert result["cancelled_count"] == 2
    assert result["batch_id"] is not None
    assert PredictionStore(tmp_path).get_batch(result["batch_id"], 0, 10)["record_count"] == 1
    assert seen == ["q1", "q2"]
    collect_target_job(
        running["id"],
        tmp_path,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(respond)),
    )
    assert seen == ["q1", "q2"]

    interrupted = store.create_job(target["id"], dataset_id, 1, "answer")
    assert store.claim_job(interrupted["id"])
    store.record_case(
        interrupted["id"],
        "q1",
        TargetCall(Prediction("q1", "A1", None, None), (), None, None),
    )
    store.cancel_job(interrupted["id"])
    assert interrupted["id"] not in store.requeue_unfinished()
    recovered = store.get_job(interrupted["id"])
    assert recovered["status"] == "cancelled"
    assert recovered["success_count"] == 1
    assert PredictionStore(tmp_path).get_batch(recovered["batch_id"], 0, 10)["record_count"] == 1


def test_run_cancel_stops_remaining_model_calls(tmp_path: Path) -> None:
    _, batch_id = _source(tmp_path)
    store = RunStore(tmp_path)
    run = store.create_run(
        batch_id, "unused", None, True, 0.8, ["map"], "answer", _answer_config(tmp_path)
    )
    calls = 0

    def answer(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        store.cancel(run["id"])
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"score":0.5,"reason":"ok"}'}}]}
        )

    process_run(
        run["id"],
        tmp_path,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(answer)),
    )
    result = store.get_run(run["id"])
    assert result["status"] == "cancelled"
    assert result["cancelled_count"] == 3
    assert calls == 1
