import io
import json
import sqlite3
import stat
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.adapters.document_store import DocumentStore
from backend.adapters.generation_store import GenerationStore
from backend.adapters.model_probe import ModelValidationError, probe_online_model
from backend.adapters.model_store import OnlineModelStore
from backend.adapters.run_store import RunStore
from backend.api.main import create_app
from backend.config import Settings
from backend.domain.chunk_manifests import ManifestChunk


def test_probe_checks_model_token_json_mode_and_response() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        probe_online_model(client, "https://model.test/v1", "generator-v1", "private", 5)
    assert seen[0].url.path == "/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer private"
    payload = json.loads(seen[0].content)
    assert payload["model"] == "generator-v1"
    assert payload["response_format"] == {"type": "json_object"}

    for response, reason in (
        (httpx.Response(401, text="secret leaked by provider"), "model_http_401"),
        (httpx.Response(200, json={"choices": []}), "invalid_model_response"),
        (
            httpx.Response(200, json={"choices": [{"message": {"content": "plain text"}}]}),
            "invalid_model_response",
        ),
        (
            httpx.Response(200, json={"choices": [{"message": {"content": "[]"}}]}),
            "invalid_model_response",
        ),
    ):

        def respond_with_result(
            _request: httpx.Request, *, result: httpx.Response = response
        ) -> httpx.Response:
            return result

        with (
            httpx.Client(transport=httpx.MockTransport(respond_with_result)) as client,
            pytest.raises(ModelValidationError, match=reason) as error,
        ):
            probe_online_model(client, "https://model.test/v1", "generator-v1", None, 5)
        assert "secret leaked" not in str(error.value)

    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("late", request=request))
            )
        ) as client,
        pytest.raises(ModelValidationError, match="model_timeout"),
    ):
        probe_online_model(client, "https://model.test/v1", "generator-v1", None, 5)

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with (
        httpx.Client(transport=httpx.MockTransport(unavailable)) as client,
        pytest.raises(ModelValidationError, match="model_connection_error"),
    ):
        probe_online_model(client, "https://model.test/v1", "generator-v1", None, 5)


def test_model_api_validates_before_save_and_maintains_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.api import online_models

    calls: list[tuple[str, str, str | None, float]] = []

    def probe(
        _client: httpx.Client, url: str, model: str, token: str | None, timeout: float
    ) -> None:
        calls.append((url, model, token, timeout))
        if model == "missing":
            raise ModelValidationError("model_http_404")

    monkeypatch.setattr(online_models, "probe_online_model", probe)
    api = TestClient(create_app(Settings(data_dir=tmp_path)))
    payload = {
        "name": "Generator",
        "base_url": "https://model.test/v1",
        "model_name": "generator-v1",
        "bearer_token": "private-token",
        "timeout_seconds": 12,
    }
    bad = api.post("/api/v1/online-models", json={**payload, "model_name": "missing"})
    assert bad.status_code == 422
    assert "private-token" not in bad.text
    assert api.get("/api/v1/online-models").json() == []
    assert not (tmp_path / "secrets" / "models").exists()
    for invalid in (
        {**payload, "base_url": "https://model.test/v1?key=secret"},
        {**payload, "model_name": " "},
        {**payload, "timeout_seconds": 0},
    ):
        assert api.post("/api/v1/online-models", json=invalid).status_code == 422
    secret_url = api.post(
        "/api/v1/online-models",
        json={**payload, "base_url": "https://model.test/v1?api_key=hidden-value"},
    )
    assert secret_url.status_code == 422
    assert "hidden-value" not in secret_url.text

    created = api.post("/api/v1/online-models", json=payload)
    assert created.status_code == 201, created.text
    model_id = created.json()["id"]
    secret = tmp_path / "secrets" / "models" / model_id
    assert secret.read_text() == "private-token"
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600
    assert "private-token" not in created.text + api.get("/api/v1/online-models").text

    renamed = {**payload, "name": "Updated", "model_name": "generator-v2"}
    renamed.pop("bearer_token")
    response = api.put(f"/api/v1/online-models/{model_id}", json=renamed)
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Updated"
    assert secret.read_text() == "private-token"
    assert calls[-1] == ("https://model.test/v1", "generator-v2", "private-token", 12)

    failed = api.put(
        f"/api/v1/online-models/{model_id}",
        json={**payload, "model_name": "missing", "bearer_token": "replacement"},
    )
    assert failed.status_code == 422
    assert "replacement" not in failed.text
    assert secret.read_text() == "private-token"
    assert api.get("/api/v1/online-models").json()[0]["name"] == "Updated"

    replaced = api.put(
        f"/api/v1/online-models/{model_id}", json={**payload, "bearer_token": "replacement"}
    )
    assert replaced.status_code == 200
    assert secret.read_text() == "replacement"
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600
    cleared = api.put(f"/api/v1/online-models/{model_id}", json={**payload, "bearer_token": None})
    assert cleared.status_code == 200
    assert not cleared.json()["has_token"]
    assert calls[-1][2] is None
    assert not secret.exists()

    assert api.delete("/api/v1/online-models/missing").status_code == 404
    assert api.put("/api/v1/online-models/missing", json=payload).status_code == 404
    assert api.delete(f"/api/v1/online-models/{model_id}").status_code == 204
    assert api.get("/api/v1/online-models").json() == []


def test_active_generation_blocks_model_edits_and_deletion_preserves_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.api import online_models

    probes: list[str] = []
    monkeypatch.setattr(online_models, "probe_online_model", lambda *_: probes.append("called"))
    api = TestClient(create_app(Settings(data_dir=tmp_path)))
    payload = {
        "name": "Generator",
        "base_url": "https://model.test/v1",
        "model_name": "generator-v1",
        "bearer_token": "private-token",
    }
    model_id = api.post("/api/v1/online-models", json=payload).json()["id"]
    collection = DocumentStore(tmp_path).create_from_chunks(
        "Source", [ManifestChunk(0, "doc-a", "Evidence")]
    )
    runs = GenerationStore(tmp_path)
    run = runs.create_run(
        collection["id"], {"model_id": model_id, "model_name": "generator-v1"}, 1, 0, 1, 1
    )
    assert api.put(f"/api/v1/online-models/{model_id}", json=payload).status_code == 409
    assert probes == ["called"]
    assert api.delete(f"/api/v1/online-models/{model_id}").status_code == 409
    assert OnlineModelStore(tmp_path).token(model_id) == "private-token"
    with sqlite3.connect(tmp_path / "rageva.sqlite3") as connection:
        connection.execute(
            "UPDATE generation_runs SET status = 'completed' WHERE id = ?", (run["id"],)
        )
    assert api.delete(f"/api/v1/online-models/{model_id}").status_code == 204
    assert not (tmp_path / "secrets" / "models" / model_id).exists()
    assert runs.get(run["id"])["config"]["model_name"] == "generator-v1"


def test_active_answer_run_blocks_model_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.api import online_models, runs

    monkeypatch.setattr(online_models, "probe_online_model", lambda *_: None)
    monkeypatch.setattr(runs, "worker_is_ready", lambda *_: True)
    monkeypatch.setattr(runs, "score_run_task", lambda *_: None)
    api = TestClient(create_app(Settings(data_dir=tmp_path)))
    payload = {"name": "Judge", "base_url": "https://model.test/v1", "model_name": "judge-v1"}
    model_id = api.post("/api/v1/online-models", json=payload).json()["id"]
    dataset = api.post(
        "/api/v1/datasets/import",
        data={"dataset_name": "Gold"},
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
        files={"file": ("pred.jsonl", io.BytesIO(b'{"case_id":"q1","answer":"A"}'))},
    ).json()
    scenario = api.post(
        "/api/v1/scenarios",
        json={
            "name": "Judge",
            "faithfulness": "evidence",
            "relevance": "question",
            "correctness": "answer",
        },
    ).json()
    response = api.post(
        "/api/v1/runs",
        json={
            "prediction_batch_id": batch["id"],
            "mode": "answer",
            "scenario_id": scenario["scenario_id"],
            "judge_model_id": model_id,
        },
    )
    assert response.status_code == 202, response.text
    assert api.put(f"/api/v1/online-models/{model_id}", json=payload).status_code == 409
    assert api.delete(f"/api/v1/online-models/{model_id}").status_code == 409
    with sqlite3.connect(tmp_path / "rageva.sqlite3") as connection:
        connection.execute(
            "UPDATE evaluation_runs SET status = 'completed' WHERE id = ?", (response.json()["id"],)
        )
    assert api.delete(f"/api/v1/online-models/{model_id}").status_code == 204
    assert (
        RunStore(tmp_path).get_run(response.json()["id"])["config"]["answer"]["model_name"]
        == "judge-v1"
    )
