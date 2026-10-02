import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from backend.adapters.document_store import DocumentStore
from backend.adapters.generation_model import GeneratedCase
from backend.adapters.generation_store import GenerationStore
from backend.api.main import create_app
from backend.config import Settings
from backend.domain.chunk_manifests import ManifestChunk
from backend.domain.generation import GenerationSlot


def setup_candidate(tmp_path: Path) -> tuple[TestClient, str, str]:
    collection = DocumentStore(tmp_path).create_from_chunks(
        "source",
        [
            ManifestChunk(0, "doc-a", "first fact"),
            ManifestChunk(1, "doc-a", "second fact"),
            ManifestChunk(2, "doc-b", "third fact"),
        ],
    )
    store = GenerationStore(tmp_path)
    run = store.create_run(collection["id"], {"model_name": "test-model"}, 1, 0, 1, 1)
    assert store.claim(run["id"])
    store.record(
        run["id"],
        GenerationSlot(0, False, (collection["chunks"][0],)),
        GeneratedCase("Original question", "Original answer", (0,), None),
        None,
    )
    store.finish(run["id"])
    candidate_id = store.candidates(run["id"])[0]["id"]
    return TestClient(create_app(Settings(data_dir=tmp_path))), collection["id"], candidate_id


def payload(collection_id: str, **changes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "expected_revision": 0,
        "collection_id": collection_id,
        "question": "Revised question",
        "reference_answer": "Revised answer",
        "support_positions": [2, 0],
        "action": "save",
    }
    result.update(changes)
    return result


def test_edit_reorder_approve_and_revision_history(tmp_path: Path) -> None:
    api, collection_id, candidate_id = setup_candidate(tmp_path)
    path = f"/api/v1/candidates/{candidate_id}"
    initial = api.get(path).json()
    assert initial["collection_id"] == collection_id
    assert initial["revision"] == 0
    assert initial["status"] == "pending_review"

    edited = api.patch(path, json=payload(collection_id))
    assert edited.status_code == 200, edited.text
    candidate = edited.json()
    assert candidate["revision"] == 1
    assert candidate["status"] == "pending_review"
    assert candidate["support_positions"] == [2, 0]
    assert candidate["reference_chunks"] == [
        {"document_id": "doc-b", "text": "third fact"},
        {"document_id": "doc-a", "text": "first fact"},
    ]

    approved = api.patch(path, json=payload(collection_id, expected_revision=1, action="approve"))
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["revision"] == 2
    history = api.get(path + "/revisions").json()
    assert [item["revision"] for item in history] == [0, 1, 2]
    assert [item["status"] for item in history] == ["pending_review", "pending_review", "approved"]
    assert history[0]["question"] == "Original question"
    assert history[0]["reference_chunks"] == [{"document_id": "doc-a", "text": "first fact"}]

    reopened = api.patch(path, json=payload(collection_id, expected_revision=2, question="Again"))
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "pending_review"
    assert reopened.json()["revision"] == 3


def test_invalid_sources_and_direct_text_edits_do_not_change_candidate(tmp_path: Path) -> None:
    api, collection_id, candidate_id = setup_candidate(tmp_path)
    path = f"/api/v1/candidates/{candidate_id}"
    other = DocumentStore(tmp_path).create_from_chunks(
        "other", [ManifestChunk(0, "foreign", "foreign text")]
    )
    cases = [
        (payload(other["id"]), "collection_id"),
        (payload(collection_id, support_positions=[0, 99]), "support_positions"),
        (payload(collection_id, support_positions=[0, 0]), "support_positions"),
    ]
    for body, field in cases:
        response = api.patch(path, json=body)
        assert response.status_code == 422
        assert field in {issue["field"] for issue in response.json()["issues"]}
    direct_edit = api.patch(
        path,
        json={
            **payload(collection_id),
            "reference_chunks": [{"document_id": "doc-a", "text": "fake"}],
        },
    )
    assert direct_edit.status_code == 422
    assert api.get(path).json()["revision"] == 0
    assert len(api.get(path + "/revisions").json()) == 1


def test_incomplete_draft_cannot_be_approved_and_rejection_is_recorded(tmp_path: Path) -> None:
    api, collection_id, candidate_id = setup_candidate(tmp_path)
    path = f"/api/v1/candidates/{candidate_id}"
    incomplete = payload(collection_id, question=" ", reference_answer=" ", support_positions=[])
    saved = api.patch(path, json=incomplete)
    assert saved.status_code == 200
    assert saved.json()["reference_chunks"] == []
    rejected_approval = api.patch(
        path, json={**incomplete, "expected_revision": 1, "action": "approve"}
    )
    assert rejected_approval.status_code == 422
    assert {issue["field"] for issue in rejected_approval.json()["issues"]} == {
        "question",
        "reference_answer",
        "support_positions",
    }
    assert api.get(path).json()["revision"] == 1
    rejected = api.patch(path, json={**incomplete, "expected_revision": 1, "action": "reject"})
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert [item["status"] for item in api.get(path + "/revisions").json()] == [
        "pending_review",
        "pending_review",
        "rejected",
    ]


def test_stale_revision_and_unknown_candidate(tmp_path: Path) -> None:
    api, collection_id, candidate_id = setup_candidate(tmp_path)
    path = f"/api/v1/candidates/{candidate_id}"
    assert api.patch(path, json=payload(collection_id)).status_code == 200
    stale = api.patch(path, json=payload(collection_id, question="Lost edit"))
    assert stale.status_code == 409
    assert api.get(path).json()["question"] == "Revised question"
    assert api.get("/api/v1/candidates/missing").status_code == 404
    assert api.get("/api/v1/candidates/missing/revisions").status_code == 404
    assert api.patch("/api/v1/candidates/missing", json=payload(collection_id)).status_code == 404


def test_existing_candidate_without_revision_rows_keeps_original_snapshot(tmp_path: Path) -> None:
    api, collection_id, candidate_id = setup_candidate(tmp_path)
    with sqlite3.connect(tmp_path / "rageva.sqlite3") as connection:
        connection.execute(
            "DELETE FROM candidate_revisions WHERE candidate_id = ?", (candidate_id,)
        )
    path = f"/api/v1/candidates/{candidate_id}"
    assert [item["question"] for item in api.get(path + "/revisions").json()] == [
        "Original question"
    ]
    assert api.patch(path, json=payload(collection_id)).status_code == 200
    assert [item["question"] for item in api.get(path + "/revisions").json()] == [
        "Original question",
        "Revised question",
    ]
