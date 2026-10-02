import io
import json
from pathlib import Path

import pytest

from backend.adapters.document_store import DocumentStore
from backend.adapters.publication_store import PublicationStore
from backend.domain.chunk_manifests import ManifestChunk
from backend.tests.test_candidate_duplicates import approve, create_candidate, setup
from backend.tests.test_runs import FakeEncoder


def test_publish_new_dataset_then_append_immutable_version(tmp_path: Path) -> None:
    store, api, collection_id = setup(tmp_path)
    first = create_candidate(store, collection_id, "When did Acme launch?", "2018")
    approve(store, first)
    first_result = api.post(
        "/api/v1/candidates/publish",
        json={"candidate_ids": [first], "dataset_name": "Generated gold"},
    )
    assert first_result.status_code == 201, first_result.text
    initial = first_result.json()
    assert initial["version"] == 1
    assert initial["case_count"] == 1
    assert initial["source_collection_ids"] == [collection_id]
    old = api.get(f"/api/v1/datasets/{initial['dataset_id']}/versions/1").json()
    assert old["cases"][0] == {
        "case_id": f"gen-{first}",
        "question": "When did Acme launch?",
        "reference_answer": "2018",
        "reference_chunks": [{"document_id": "doc-a", "text": "Acme launched in 2018"}],
    }

    second = create_candidate(store, collection_id, "Who founded Acme?", "Ada")
    approve(store, second)
    appended = api.post(
        "/api/v1/candidates/publish",
        json={
            "candidate_ids": [second],
            "dataset_id": initial["dataset_id"],
            "expected_version": 1,
        },
    )
    assert appended.status_code == 201, appended.text
    assert appended.json()["version"] == 2
    assert appended.json()["case_count"] == 2
    assert appended.json()["source_collection_ids"] == [collection_id]
    current = api.get(f"/api/v1/datasets/{initial['dataset_id']}/versions/2").json()
    assert [case["case_id"] for case in current["cases"]] == [f"gen-{first}", f"gen-{second}"]
    assert api.get(f"/api/v1/datasets/{initial['dataset_id']}/versions/1").json() == old
    assert [
        item["source_collection_ids"]
        for item in api.get(f"/api/v1/datasets/{initial['dataset_id']}/versions").json()
    ] == [[collection_id], [collection_id]]
    store.review(
        first,
        expected_revision=1,
        collection_id=collection_id,
        question="Edited after publication",
        reference_answer="different answer",
        support_positions=[0],
        action="save",
    )
    assert api.get(f"/api/v1/datasets/{initial['dataset_id']}/versions/1").json() == old


def test_publish_rejects_unapproved_duplicate_and_unreleased_suspect(tmp_path: Path) -> None:
    store, api, collection_id = setup(tmp_path)
    first = create_candidate(store, collection_id, "When did Acme launch?", "2018")
    assert (
        api.post(
            "/api/v1/candidates/publish",
            json={"candidate_ids": [first], "dataset_name": "Blocked"},
        ).status_code
        == 409
    )
    approve(store, first)
    duplicate = create_candidate(store, collection_id, "When did Acme launch?", "2018")
    approve(store, duplicate)
    suspect = create_candidate(store, collection_id, "Name the launch milestone", "2018")
    approve(store, suspect)
    for candidate_id in (duplicate, suspect):
        result = api.post(
            "/api/v1/candidates/publish",
            json={"candidate_ids": [candidate_id], "dataset_name": "Blocked"},
        )
        assert result.status_code == 409
    assert api.get("/api/v1/datasets").json() == []

    check = api.get(f"/api/v1/candidates/{suspect}/duplicate-check").json()
    released = api.post(
        f"/api/v1/candidates/{suspect}/duplicate-decision",
        json={"check_id": check["id"], "expected_revision": 1, "reason": "Different fact"},
    )
    assert released.status_code == 200
    published = api.post(
        "/api/v1/candidates/publish",
        json={"candidate_ids": [suspect], "dataset_name": "Released"},
    )
    assert published.status_code == 201, published.text


def test_published_version_runs_through_normal_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.api import runs
    from backend.worker.run_processor import process_run

    store, api, collection_id = setup(tmp_path)
    candidate_id = create_candidate(store, collection_id, "When did Acme launch?", "2018")
    approve(store, candidate_id)
    dataset = api.post(
        "/api/v1/candidates/publish",
        json={"candidate_ids": [candidate_id], "dataset_name": "Gold"},
    ).json()
    prediction = api.post(
        "/api/v1/predictions/import",
        data={"dataset_id": dataset["dataset_id"], "evaluation_type": "retrieval"},
        files={
            "file": (
                "prediction.jsonl",
                io.BytesIO(
                    json.dumps(
                        {
                            "case_id": f"gen-{candidate_id}",
                            "contexts": [{"document_id": "doc-a", "text": "Acme launched in 2018"}],
                        }
                    ).encode()
                ),
            )
        },
    )
    assert prediction.status_code == 201, prediction.text
    monkeypatch.setattr(runs, "worker_is_ready", lambda *_: True)
    monkeypatch.setattr(runs, "score_run_task", lambda _run_id, _context=None: None)
    created = api.post(
        "/api/v1/runs",
        json={
            "prediction_batch_id": prediction.json()["id"],
            "model_name": "fake-v1",
            "threshold": 0.8,
            "metrics": ["precision", "map", "ndcg"],
        },
    )
    assert created.status_code == 202, created.text
    process_run(created.json()["id"], tmp_path, encoder_factory=FakeEncoder)
    result = api.get(f"/api/v1/runs/{created.json()['id']}").json()
    assert result["status"] == "completed"
    assert result["success_count"] == 1


def test_write_failure_rolls_back_dataset_and_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, api, collection_id = setup(tmp_path)
    candidate_id = create_candidate(store, collection_id, "When did Acme launch?", "2018")
    approve(store, candidate_id)

    def fail(*_args: object) -> None:
        raise RuntimeError("snapshot write failed")

    monkeypatch.setattr(PublicationStore, "record_published_candidate", fail)
    with pytest.raises(RuntimeError, match="snapshot write failed"):
        api.post(
            "/api/v1/candidates/publish",
            json={"candidate_ids": [candidate_id], "dataset_name": "Atomic"},
        )
    assert api.get("/api/v1/datasets").json() == []


def test_publish_conflicts_and_invalid_selection_are_atomic(tmp_path: Path) -> None:
    store, api, collection_id = setup(tmp_path)
    first = create_candidate(store, collection_id, "When did Acme launch?", "2018")
    approve(store, first)
    second = create_candidate(store, collection_id, "Who founded Acme?", "Ada")
    mixed = api.post(
        "/api/v1/candidates/publish",
        json={"candidate_ids": [first, second], "dataset_name": "Atomic"},
    )
    assert mixed.status_code == 409
    assert api.get("/api/v1/datasets").json() == []
    approve(store, second)
    duplicate_selection = api.post(
        "/api/v1/candidates/publish",
        json={"candidate_ids": [first, first], "dataset_name": "Atomic"},
    )
    assert duplicate_selection.status_code == 422
    assert api.get("/api/v1/datasets").json() == []

    imported = api.post(
        "/api/v1/datasets/import",
        data={"dataset_name": "Existing"},
        files={
            "file": (
                "one.jsonl",
                json.dumps(
                    {
                        "case_id": "old",
                        "question": "Old question",
                        "reference_answer": "Old answer",
                    }
                ),
            )
        },
    )
    assert imported.status_code == 201
    dataset_id = imported.json()["dataset_id"]
    stale = api.post(
        "/api/v1/candidates/publish",
        json={"candidate_ids": [first], "dataset_id": dataset_id, "expected_version": 2},
    )
    assert stale.status_code == 409
    assert [
        item["version"] for item in api.get(f"/api/v1/datasets/{dataset_id}/versions").json()
    ] == [1]

    collision = api.post(
        "/api/v1/datasets/import",
        data={"dataset_id": dataset_id},
        files={
            "file": (
                "collision.jsonl",
                json.dumps(
                    {
                        "case_id": f"gen-{first}",
                        "question": "Imported",
                        "reference_answer": "Other",
                    }
                ),
            )
        },
    )
    assert collision.status_code == 201
    conflict = api.post(
        "/api/v1/candidates/publish",
        json={"candidate_ids": [first], "dataset_id": dataset_id, "expected_version": 2},
    )
    assert conflict.status_code == 409
    assert [
        item["version"] for item in api.get(f"/api/v1/datasets/{dataset_id}/versions").json()
    ] == [2, 1]


def test_validation_reuses_import_rules_and_leaves_no_dataset(tmp_path: Path) -> None:
    store, api, _ = setup(tmp_path)
    collection = DocumentStore(tmp_path).create_from_chunks(
        "repeated text",
        [
            ManifestChunk(0, "doc", "same text"),
            ManifestChunk(1, "doc", "same text"),
        ],
    )
    collection_id = collection["id"]
    candidate_id = create_candidate(store, collection_id, "What?", "Answer")
    store.review(
        candidate_id,
        expected_revision=0,
        collection_id=collection_id,
        question="What?",
        reference_answer="Answer",
        support_positions=[0, 1],
        action="approve",
    )
    rejected = api.post(
        "/api/v1/candidates/publish",
        json={"candidate_ids": [candidate_id], "dataset_name": "Invalid"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["issues"][0]["code"] == "duplicate_reference_chunk"
    assert (
        api.post(
            "/api/v1/candidates/publish",
            json={"candidate_ids": ["missing"], "dataset_name": "Invalid"},
        ).status_code
        == 404
    )
    assert api.get("/api/v1/datasets").json() == []
