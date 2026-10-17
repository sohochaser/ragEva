import io
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient
from httpx import Response

from backend.adapters.document_store import DocumentStore
from backend.api.main import create_app
from backend.config import Settings
from backend.domain.chunk_manifests import ManifestChunk


def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings(data_dir=tmp_path)))


def import_manifest(
    api: TestClient, filename: str, content: bytes, name: str = "现有切块"
) -> Response:
    return api.post(
        "/api/v1/document-collections/import-chunks",
        data={"name": name},
        files={"file": (filename, io.BytesIO(content))},
    )


def test_jsonl_import_preserves_global_order_and_marks_missing_originals(tmp_path: Path) -> None:
    api = client(tmp_path)
    content = (
        '{"position":0,"document_id":"a","text":"第一段"}\n'
        '{"position":1,"document_id":"b","text":"第二段"}\n'
        '{"position":2,"document_id":"a","text":"第三段"}\n'
    ).encode()
    result = import_manifest(api, "chunks.jsonl", content)
    assert result.status_code == 201
    detail = result.json()
    assert detail["source_kind"] == "chunks_only"
    assert detail["document_count"] == 2
    assert [
        (chunk["position"], chunk["document_id"], chunk["text"]) for chunk in detail["chunks"]
    ] == [(0, "a", "第一段"), (1, "b", "第二段"), (2, "a", "第三段")]
    assert all(not doc["has_original_file"] for doc in detail["documents"])
    assert all(
        doc["filename"] is None and doc["checksum"] is None and doc["byte_count"] is None
        for doc in detail["documents"]
    )
    assert api.get(f"/api/v1/document-collections/{detail['id']}").json() == detail
    with sqlite3.connect(tmp_path / "rageva.sqlite3") as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM source_documents WHERE content IS NOT NULL"
            ).fetchone()[0]
            == 0
        )


def test_csv_import_and_invalid_rows_are_atomic(tmp_path: Path) -> None:
    api = client(tmp_path)
    valid = b"position,document_id,text\n0,doc-a,First\n1,doc-b,Second\n"
    result = import_manifest(api, "chunks.csv", valid)
    assert result.status_code == 201
    assert [chunk["text"] for chunk in result.json()["chunks"]] == ["First", "Second"]

    bad = b"position,document_id,text\n0,doc-a,First\n2,doc-a,First\n3,,Third\n4,doc-b,\n"
    failure = import_manifest(api, "bad.csv", bad)
    assert failure.status_code == 422
    issues = failure.json()["issues"]
    assert {(item["line"], item["code"]) for item in issues} == {
        (3, "invalid_order"),
        (3, "duplicate_chunk"),
        (4, "invalid_order"),
        (4, "missing_document_id"),
        (5, "invalid_order"),
        (5, "missing_text"),
    }
    assert len(api.get("/api/v1/document-collections").json()) == 1
    assert api.get(f"/api/v1/document-collections/{result.json()['id']}").json() == result.json()


def test_empty_bad_json_and_missing_columns_do_not_create_collection(tmp_path: Path) -> None:
    api = client(tmp_path)
    examples = [
        ("empty.jsonl", b"\n", "empty_manifest"),
        ("bad.jsonl", b"{\n", "invalid_json"),
        ("missing.csv", b"position,text\n0,content\n", "missing_column"),
        ("wrong.txt", b"data", "invalid_format"),
        ("bad-encoding.csv", b"\xff", "invalid_encoding"),
    ]
    for filename, content, code in examples:
        result = import_manifest(api, filename, content)
        assert result.status_code == 422
        assert code in {issue["code"] for issue in result.json()["issues"]}
    assert api.get("/api/v1/document-collections").json() == []


def test_append_chunk_manifest_rebases_positions_and_keeps_old_snapshot(tmp_path: Path) -> None:
    api = client(tmp_path)
    first = import_manifest(
        api, "first.csv", b"position,document_id,text\n0,a,First\n1,b,Second\n"
    ).json()
    second = api.post(
        "/api/v1/document-collections/import-chunks",
        data={"name": "现有切块", "group_id": first["group_id"], "expected_version": "1"},
        files={"file": ("next.csv", io.BytesIO(b"position,document_id,text\n0,c,Third\n"))},
    )
    assert second.status_code == 201
    detail = second.json()
    assert detail["version"] == 2
    assert [(item["position"], item["document_id"]) for item in detail["chunks"]] == [
        (0, "a"),
        (1, "b"),
        (2, "c"),
    ]
    assert api.get(f"/api/v1/document-collections/{first['id']}").json() == first
    duplicate = api.post(
        "/api/v1/document-collections/import-chunks",
        data={"name": "现有切块", "group_id": first["group_id"], "expected_version": "2"},
        files={"file": ("bad.csv", io.BytesIO(b"position,document_id,text\n0,a,Other\n"))},
    )
    assert duplicate.status_code == 409


def test_concurrent_same_name_imports_share_one_logical_collection(tmp_path: Path) -> None:
    store = DocumentStore(tmp_path)

    def create(index: int) -> dict[str, object]:
        return store.save_chunks("Concurrent", [ManifestChunk(0, f"doc-{index}", f"Text {index}")])

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, (1, 2)))
    assert {item["version"] for item in results} == {1, 2}
    listed = store.list()
    assert len(listed) == 1
    assert listed[0]["version"] == 2
    assert {item["document_id"] for item in store.get(listed[0]["id"])["documents"]} == {
        "doc-1",
        "doc-2",
    }
