from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.config import Settings


class FakeEncoder:
    calls: list[list[str]] = []

    def __init__(self, model_name: str, cache_dir: Path, model_path: Path | None, offline: bool):
        self.model_id = model_name + (f":{model_path}" if model_path else "")
        self.model_name = model_name
        self.offline = offline

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        self.calls.append(texts)
        lookup = {
            "high": np.array([1.0, 0.0], dtype=np.float32),
            "boundary": np.array([0.8, 0.6], dtype=np.float32),
            "low": np.array([0.0, 1.0], dtype=np.float32),
        }
        return [lookup[text] for text in texts]


def test_preview_filters_documents_and_applies_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.api import matching

    FakeEncoder.calls = []
    monkeypatch.setattr(matching, "FastEmbedEncoder", FakeEncoder)
    api = TestClient(create_app(Settings(data_dir=tmp_path)))
    payload = {
        "model_name": "fake-v1",
        "threshold": 0.8,
        "reference_chunks": [
            {"text": "high", "document_id": "doc-a"},
            {"text": "low", "document_id": "doc-b"},
        ],
        "predicted_chunks": [
            {"text": "boundary", "document_id": "doc-a"},
            {"text": "high", "document_id": "doc-b"},
        ],
    }
    result = api.post("/api/v1/matching/preview", json=payload)
    assert result.status_code == 200, result.text
    edges = result.json()["pairs"]
    assert edges[0] == {
        "reference_index": 0,
        "predicted_index": 0,
        "similarity": 0.8,
        "candidate": True,
        "reason": "candidate",
    }
    assert edges[1]["reason"] == "document_mismatch"
    assert edges[1]["similarity"] is None
    assert edges[2]["reason"] == "document_mismatch"
    assert edges[3]["reason"] == "below_threshold"
    assert result.json()["model_id"] == "fake-v1"

    second = api.post("/api/v1/matching/preview", json=payload)
    assert second.status_code == 200
    assert len(FakeEncoder.calls) == 1
    payload["threshold"] = 0.9
    third = api.post("/api/v1/matching/preview", json=payload)
    assert third.json()["pairs"][0]["candidate"] is False
    assert len(FakeEncoder.calls) == 1
    payload["model_name"] = "fake-v2"
    assert api.post("/api/v1/matching/preview", json=payload).status_code == 200
    assert len(FakeEncoder.calls) == 2


def test_missing_offline_model_returns_diagnostic(tmp_path: Path) -> None:
    from backend.adapters.local_embeddings import FastEmbedEncoder, ModelUnavailable

    missing = tmp_path / "missing-model"
    try:
        FastEmbedEncoder("BAAI/bge-small-zh-v1.5", tmp_path / "cache", missing, True)
    except ModelUnavailable as exc:
        assert "模型目录不存在" in str(exc)
    else:
        raise AssertionError("missing offline model was accepted")


def test_bad_threshold_does_not_load_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.api import matching

    def fail_encoder(*args: object) -> None:
        raise AssertionError("encoder must not load")

    monkeypatch.setattr(matching, "FastEmbedEncoder", fail_encoder)
    api = TestClient(create_app(Settings(data_dir=tmp_path)))
    result = api.post(
        "/api/v1/matching/preview",
        json={
            "model_name": "fake",
            "threshold": 2,
            "reference_chunks": [{"text": "a", "document_id": "d"}],
            "predicted_chunks": [{"text": "b", "document_id": "d"}],
        },
    )
    assert result.status_code == 422


def test_case_lookup_for_matching_preview(tmp_path: Path) -> None:
    api = TestClient(create_app(Settings(data_dir=tmp_path)))
    imported = api.post(
        "/api/v1/datasets/import",
        data={"dataset_name": "preview"},
        files={
            "file": (
                "cases.jsonl",
                b'{"case_id":"q1","question":"Q","reference_chunks":'
                b'[{"text":"A","document_id":"doc"}]}',
            )
        },
    ).json()
    dataset_id = imported["dataset_id"]
    result = api.get(f"/api/v1/datasets/{dataset_id}/versions/1/cases/q1")
    assert result.status_code == 200
    assert result.json()["reference_chunks"] == [{"text": "A", "document_id": "doc"}]
    assert api.get(f"/api/v1/datasets/{dataset_id}/versions/1/cases/missing").status_code == 404
