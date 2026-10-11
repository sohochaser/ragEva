import json
import stat
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.adapters.answer_model import AnswerModelError, evaluate_answer_metric
from backend.api.main import create_app
from backend.config import Settings
from backend.domain.answer_prompts import AnswerMetric, AnswerSample, render_messages


def test_scenario_versions_model_secret_and_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.api import online_models

    monkeypatch.setattr(online_models, "probe_online_model", lambda *_: None)
    api = TestClient(create_app(Settings(data_dir=tmp_path)))
    model_response = api.post(
        "/api/v1/online-models",
        json={
            "name": "judge",
            "base_url": "https://model.example/v1",
            "model_name": "judge-v1",
            "bearer_token": "private-key",
        },
    )
    assert model_response.status_code == 201
    model = model_response.json()
    assert "private-key" not in model_response.text
    assert "private-key" not in api.get("/api/v1/online-models").text
    assert stat.S_IMODE((tmp_path / "secrets" / "models" / model["id"]).stat().st_mode) == 0o600
    assert (
        api.post(
            "/api/v1/online-models",
            json={"name": "bad", "base_url": "https://x/v1?api_key=leak", "model_name": "x"},
        ).status_code
        == 422
    )

    criteria = {
        "faithfulness": "Only context evidence",
        "relevance": "Address question",
        "correctness": "Agree with reference",
    }
    created = api.post("/api/v1/scenarios", json={"name": "Support", **criteria})
    assert created.status_code == 201, created.text
    first = created.json()
    scenario_id = first["scenario_id"]
    updated = api.put(
        f"/api/v1/scenarios/{scenario_id}", json={**criteria, "relevance": "New rule"}
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert [
        item["relevance"] for item in api.get(f"/api/v1/scenarios/{scenario_id}/versions").json()
    ] == ["New rule", "Address question"]
    assert api.get("/api/v1/scenarios/template").json()["system_prompt"]
    assert (
        api.put(f"/api/v1/scenarios/{scenario_id}", json={**criteria, "relevance": " "}).status_code
        == 422
    )
    assert (
        api.post(
            f"/api/v1/scenarios/{scenario_id}/preview",
            json={"model_id": model["id"], "question": "Q", "answer": "A"},
        ).status_code
        == 422
    )

    from backend.api import scenarios

    captured: list[tuple[str, str, str | None]] = []

    def fake_evaluate(
        _client: httpx.Client,
        _url: str,
        name: str,
        token: str | None,
        _timeout: float,
        metric: AnswerMetric,
        rule: str,
        _sample: AnswerSample,
    ) -> object:
        from backend.adapters.answer_model import AnswerModelResult

        captured.append((metric, rule, token))
        return AnswerModelResult(
            metric,
            0.7,
            "grounded",
            '{"score":0.7,"reason":"grounded"}',
            {"input_tokens": 10, "output_tokens": 4},
            name,
            "answer-eval-v1",
        )

    monkeypatch.setattr(scenarios, "evaluate_answer_metric", fake_evaluate)
    preview_request = {
        "model_id": model["id"],
        "version": 1,
        "question": "Q",
        "answer": "A",
        "reference_answer": "A",
        "contexts": ["A"],
    }
    preview = api.post(f"/api/v1/scenarios/{scenario_id}/preview", json=preview_request)
    assert preview.status_code == 200, preview.text
    assert preview.json()["metrics"]["faithfulness"]["score"] == 0.7
    assert [item[1] for item in captured] == list(criteria.values())
    assert {item[2] for item in captured} == {"private-key"}

    def broken(*_args: object) -> object:
        raise AnswerModelError("invalid_score")

    monkeypatch.setattr(scenarios, "evaluate_answer_metric", broken)
    failed = api.post(f"/api/v1/scenarios/{scenario_id}/preview", json=preview_request)
    assert failed.status_code == 502
    assert [
        item["version"] for item in api.get(f"/api/v1/scenarios/{scenario_id}/versions").json()
    ] == [2, 1]


def test_fixed_prompt_and_model_response_contract() -> None:
    sample = AnswerSample("Q", "A", "reference", ("context",))
    messages = render_messages("faithfulness", "Must cite context", sample)
    assert "Must cite context" not in messages[0]["content"]
    assert json.loads(messages[1]["content"])["criteria"] == "Must cite context"

    def response(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"score":1,"reason":"correct"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        result = evaluate_answer_metric(
            client,
            "https://model.example/v1",
            "judge",
            "secret",
            5,
            "correctness",
            "Compare",
            sample,
        )
    assert result.score == 1
    assert result.usage == {"input_tokens": 12, "output_tokens": 3}

    for content in (
        '{"score":-0.1,"reason":"bad"}',
        '{"score":true,"reason":"bad"}',
        '{"score":0.5}',
        "not json",
    ):
        with (
            httpx.Client(
                transport=httpx.MockTransport(
                    lambda _, body=content: httpx.Response(
                        200, json={"choices": [{"message": {"content": body}}]}
                    )
                )
            ) as client,
            pytest.raises(AnswerModelError),
        ):
            evaluate_answer_metric(
                client,
                "https://model.example/v1",
                "judge",
                None,
                5,
                "correctness",
                "Compare",
                sample,
            )
