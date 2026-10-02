import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.adapters.document_store import DocumentStore
from backend.adapters.generation_model import GeneratedCase
from backend.adapters.generation_store import DuplicateDecisionConflict, GenerationStore
from backend.api.main import create_app
from backend.config import Settings
from backend.domain.candidate_duplicates import compare
from backend.domain.chunk_manifests import ManifestChunk
from backend.domain.generation import GenerationSlot


def create_candidate(store: GenerationStore, collection_id: str, question: str, answer: str) -> str:
    collection = store.get_collection(collection_id)
    run = store.create_run(collection_id, {"model_name": "stub"}, 1, 0, 1, 1)
    assert store.claim(run["id"])
    store.record(
        run["id"],
        GenerationSlot(0, False, (collection["chunks"][0],)),
        GeneratedCase(question, answer, (0,), None),
        None,
    )
    store.finish(run["id"])
    return store.candidates(run["id"])[0]["id"]


def setup(tmp_path: Path) -> tuple[GenerationStore, TestClient, str]:
    collection = DocumentStore(tmp_path).create_from_chunks(
        "source", [ManifestChunk(0, "doc-a", "Acme launched in 2018")]
    )
    store = GenerationStore(tmp_path)
    return store, TestClient(create_app(Settings(data_dir=tmp_path))), collection["id"]


def approve(store: GenerationStore, candidate_id: str) -> None:
    candidate = store.get_candidate(candidate_id)
    store.review(
        candidate_id,
        expected_revision=candidate["revision"],
        collection_id=candidate["collection_id"],
        question=candidate["question"],
        reference_answer=candidate["reference_answer"],
        support_positions=candidate["support_positions"],
        action="approve",
    )


def test_generated_paraphrase_is_definite_duplicate_across_runs(tmp_path: Path) -> None:
    store, api, collection_id = setup(tmp_path)
    first = create_candidate(store, collection_id, "What year did Acme launch?", "2018")
    second = create_candidate(store, collection_id, "When was Acme launched?", "2018")
    response = api.get(f"/api/v1/candidates/{second}/duplicate-check")
    assert response.status_code == 200
    check = response.json()
    assert check["revision"] == 0
    assert check["verdict"] == "duplicate"
    assert check["matches"][0]["source_id"] == first
    assert check["matches"][0]["reason"] == "same_answer_source_and_question_meaning"
    approve(store, second)
    with sqlite3.connect(tmp_path / "rageva.sqlite3") as connection:
        connection.row_factory = sqlite3.Row
        with pytest.raises(DuplicateDecisionConflict):
            store.record_published_candidate(connection, second, "version", "case")
    assert (
        api.post(
            f"/api/v1/candidates/{second}/duplicate-decision",
            json={"check_id": check["id"], "expected_revision": 0, "reason": "not same"},
        ).status_code
        == 409
    )


def test_suspected_release_is_audited_and_revision_bound(tmp_path: Path) -> None:
    store, api, collection_id = setup(tmp_path)
    create_candidate(store, collection_id, "What year did Acme launch?", "2018")
    second = create_candidate(store, collection_id, "Name the launch milestone", "2018")
    approve(store, second)
    path = f"/api/v1/candidates/{second}"
    check = api.get(path + "/duplicate-check").json()
    assert check["verdict"] == "suspected"
    assert (
        api.post(
            path + "/duplicate-decision",
            json={"check_id": check["id"], "expected_revision": 1, "reason": "   "},
        ).status_code
        == 422
    )
    allowed = api.post(
        path + "/duplicate-decision",
        json={"check_id": check["id"], "expected_revision": 1, "reason": "Different fact"},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["reason"] == "Different fact"
    assert allowed.json()["decision"] == "allow"
    with sqlite3.connect(tmp_path / "rageva.sqlite3") as connection:
        connection.row_factory = sqlite3.Row
        store.assert_publishable(connection, second)
    revised = api.patch(
        path,
        json={
            "expected_revision": 1,
            "collection_id": collection_id,
            "question": "Another question",
            "reference_answer": "2018",
            "support_positions": [0],
            "action": "approve",
        },
    )
    assert revised.status_code == 200
    latest = api.get(path + "/duplicate-check").json()
    assert latest["revision"] == 2
    assert latest["decision"] is None
    history = api.get(path + "/duplicate-history").json()
    assert any(item["id"] == check["id"] and item["reason"] == "Different fact" for item in history)
    assert (
        api.post(
            path + "/duplicate-decision",
            json={"check_id": check["id"], "expected_revision": 1, "reason": "Old reason"},
        ).status_code
        == 409
    )


def test_published_snapshot_and_new_candidate_invalidate_old_check(tmp_path: Path) -> None:
    store, api, collection_id = setup(tmp_path)
    first = create_candidate(store, collection_id, "What year did Acme launch?", "2018")
    approve(store, first)
    with sqlite3.connect(tmp_path / "rageva.sqlite3") as connection:
        connection.row_factory = sqlite3.Row
        store.record_published_candidate(connection, first, "v1", "case-1")
        connection.commit()
    store.review(
        first,
        expected_revision=1,
        collection_id=collection_id,
        question="What is Acme?",
        reference_answer="A company",
        support_positions=[0],
        action="approve",
    )
    second = create_candidate(store, collection_id, "What year did Acme launch?", "2018")
    matches = api.get(f"/api/v1/candidates/{second}/duplicate-check").json()["matches"]
    assert any(
        item["source_kind"] == "published_case" and item["source_id"] == "v1:case-1"
        for item in matches
    )

    third = create_candidate(store, collection_id, "Who founded Zeta?", "Ada")
    approve(store, third)
    create_candidate(store, collection_id, "Who founded Zeta?", "Ada")
    with sqlite3.connect(tmp_path / "rageva.sqlite3") as connection:
        connection.row_factory = sqlite3.Row
        with pytest.raises(DuplicateDecisionConflict):
            store.record_published_candidate(connection, third, "v2", "case-2")
    assert api.post(f"/api/v1/candidates/{third}/duplicate-check").json()["verdict"] == "duplicate"


def test_two_allowed_candidates_can_publish_in_one_transaction(tmp_path: Path) -> None:
    store, api, collection_id = setup(tmp_path)
    first = create_candidate(store, collection_id, "What year did Acme launch?", "2018")
    second = create_candidate(store, collection_id, "Name the launch milestone", "2018")
    for candidate_id in (first, second):
        approve(store, candidate_id)
        check = api.get(f"/api/v1/candidates/{candidate_id}/duplicate-check").json()
        assert check["verdict"] == "suspected"
        assert (
            api.post(
                f"/api/v1/candidates/{candidate_id}/duplicate-decision",
                json={
                    "check_id": check["id"],
                    "expected_revision": 1,
                    "reason": "Separate question",
                },
            ).status_code
            == 200
        )
    with sqlite3.connect(tmp_path / "rageva.sqlite3") as connection, connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
        store.record_published_candidate(connection, first, "v1", "case-1")
        store.record_published_candidate(connection, second, "v1", "case-2")
    with sqlite3.connect(tmp_path / "rageva.sqlite3") as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM published_candidate_cases").fetchone()[0] == 2
        )


def test_other_collection_does_not_match_and_check_failure_blocks_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, api, collection_id = setup(tmp_path)
    first = create_candidate(store, collection_id, "What year did Acme launch?", "2018")
    second_collection = DocumentStore(tmp_path).create_from_chunks(
        "other", [ManifestChunk(0, "doc-a", "Acme launched in 2018")]
    )
    other = create_candidate(store, second_collection["id"], "What year did Acme launch?", "2018")
    assert api.get(f"/api/v1/candidates/{other}/duplicate-check").json()["verdict"] == "unique"
    approve(store, first)

    def fail(*_args: object) -> list[dict[str, object]]:
        raise RuntimeError("check failed")

    monkeypatch.setattr(store, "_duplicate_matches", fail)
    with pytest.raises(RuntimeError, match="check failed"):
        store.check_duplicates(first)
    with sqlite3.connect(tmp_path / "rageva.sqlite3") as connection:
        connection.row_factory = sqlite3.Row
        with pytest.raises(RuntimeError, match="check failed"):
            store.assert_publishable(connection, first)


def test_same_answer_without_shared_fact_is_not_definite_duplicate() -> None:
    case = {
        "question": "When did Acme launch?",
        "reference_answer": "2018",
        "reference_chunks": [{"document_id": "d", "text": "Acme launched in 2018"}],
    }
    other = {
        "source_kind": "candidate",
        "source_id": "other",
        "question": "Which award did Acme receive?",
        "reference_answer": "2018",
        "reference_chunks": case["reference_chunks"],
    }
    assert compare(case, other)["verdict"] == "suspected"  # type: ignore[index]
