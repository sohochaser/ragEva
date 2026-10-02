import json
import platform
import threading
import time
from pathlib import Path

import httpx
import numpy as np
from fastapi.testclient import TestClient

from backend.adapters.dataset_store import DatasetStore
from backend.adapters.model_store import OnlineModelStore
from backend.adapters.run_store import RunStore
from backend.adapters.scenario_store import ScenarioStore
from backend.adapters.target_store import TargetStore
from backend.api.main import create_app
from backend.config import Settings
from backend.domain.datasets import EvaluationCase, ReferenceChunk
from backend.worker.run_processor import process_run
from backend.worker.target_collector import collect_target_job


class ScaleEncoder:
    def __init__(self, _name: str, _cache: Path, _path: Path | None, _offline: bool):
        self.model_id = "scale-vector"

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        return [np.array([1.0, 0.0], dtype=np.float32) for _ in texts]


def test_thousand_cases_complete_with_bounded_faults_and_exports(tmp_path: Path) -> None:
    started = time.monotonic()
    count = 1000
    cases = [
        EvaluationCase(
            f"q{i}",
            f"Question {i}",
            None if i % 4 == 0 else f"Answer {i}",
            None if i % 4 == 1 else (ReferenceChunk(f"Answer {i}", f"doc-{i}"),),
        )
        for i in range(count)
    ]
    dataset = DatasetStore(tmp_path).import_cases("scale", None, "scale", cases)
    target_store = TargetStore(tmp_path)
    target = target_store.create_target(
        "fake-rag", "https://rag.example/api", None, 2, 1, max_concurrency=4
    )
    job = target_store.create_job(target["id"], dataset["dataset_id"], 1, "both")
    lock = threading.Lock()
    attempts: dict[str, int] = {}
    active = 0
    peak = 0

    def rag(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        case_id = json.loads(request.content)["case_id"]
        number = int(case_id[1:])
        with lock:
            active += 1
            peak = max(peak, active)
            attempts[case_id] = attempts.get(case_id, 0) + 1
            attempt = attempts[case_id]
        try:
            time.sleep(0.0002)
            if number % 149 == 0:
                raise httpx.ReadTimeout("rate limited target")
            if number % 97 == 0 and attempt == 1:
                return httpx.Response(429)
            return httpx.Response(
                200,
                json={
                    "answer": f"Answer {number}",
                    "contexts": [{"text": f"Answer {number}", "document_id": f"doc-{number}"}],
                },
            )
        finally:
            with lock:
                active -= 1

    collect_target_job(
        job["id"], tmp_path, client_factory=lambda: httpx.Client(transport=httpx.MockTransport(rag))
    )
    collected = target_store.get_job(job["id"])
    assert collected["status"] == "failed"
    assert collected["total_count"] == count
    assert collected["processed_count"] == count
    assert collected["failed_count"] == len([i for i in range(count) if i % 149 == 0])
    assert collected["estimated_external_calls"] == count * 2
    assert peak <= 4
    assert len(attempts) == count
    assert target_store.get_job(job["id"])["batch_id"] == collected["batch_id"]

    scenario = ScenarioStore(tmp_path).create("scale", "faithful", "relevant", "correct")
    model = OnlineModelStore(tmp_path).create("judge", "https://model.example/v1", "judge", None, 5)
    config = {
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
    run_store = RunStore(tmp_path)
    run = run_store.create_run(
        collected["batch_id"],
        "scale-vector",
        None,
        True,
        0.8,
        ["precision", "map", "ndcg"],
        "both",
        config,
    )

    def judge(request: httpx.Request) -> httpx.Response:
        sample = json.loads(json.loads(request.content)["messages"][1]["content"])
        if sample["question"] == "Question 17" and sample["metric"] == "relevance":
            raise httpx.ReadTimeout("judge timeout")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"score":0.5,"reason":"ok"}'}}]}
        )

    process_run(
        run["id"],
        tmp_path,
        encoder_factory=ScaleEncoder,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(judge)),
    )
    result = run_store.get_run(run["id"])
    assert result["status"] == "failed"
    assert result["total_count"] == count
    assert result["processed_count"] == count
    assert result["failed_count"] == collected["failed_count"]
    assert (
        result["aggregate"]["answer_metrics"]["relevance"]["valid_count"]
        == collected["success_count"] - 1
    )
    assert result["aggregate"]["answer_metrics"]["relevance"]["failed_count"] == 1
    rows = run_store.get_cases(run["id"], 0, count)["cases"]
    assert len(rows) == len({row["case_id"] for row in rows}) == count
    assert all(
        row["status"] in {"success", "failed", "not_applicable", "cancelled"} for row in rows
    )
    api = TestClient(create_app(Settings(data_dir=tmp_path)))
    exported = api.get(f"/api/v1/runs/{run['id']}/export?format=json")
    assert exported.status_code == 200
    assert len(exported.json()["cases"]) == count
    assert len({row["case_id"] for row in exported.json()["cases"]}) == count
    csv_export = api.get(f"/api/v1/runs/{run['id']}/export?format=csv")
    assert csv_export.status_code == 200
    assert len(csv_export.text.splitlines()) == count + 1
    elapsed = time.monotonic() - started
    print(
        f"US-023 load: {count} cases, {elapsed:.2f}s, "
        f"Python {platform.python_version()}, {platform.platform()}"
    )
    assert elapsed < 600
