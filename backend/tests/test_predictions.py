import io
import json
from pathlib import Path

from fastapi.testclient import TestClient
from httpx import Response

from backend.api.main import create_app
from backend.config import Settings


def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings(data_dir=tmp_path)))


def upload(
    api: TestClient,
    content: str,
    *,
    filename: str = "predictions.jsonl",
    dataset_id: str | None = None,
    dataset_version: int | None = None,
    dataset_name: str | None = None,
    evaluation_type: str = "both",
    mapping: dict[str, str] | None = None,
) -> Response:
    fields: dict[str, str] = {"evaluation_type": evaluation_type}
    if dataset_id:
        fields["dataset_id"] = dataset_id
    if dataset_version:
        fields["dataset_version"] = str(dataset_version)
    if dataset_name:
        fields["dataset_name"] = dataset_name
    if mapping is not None:
        fields["mapping"] = json.dumps(mapping)
    return api.post(
        "/api/v1/predictions/import",
        data=fields,
        files={"file": (filename, io.BytesIO(content.encode()))},
    )


def gold(api: TestClient) -> str:
    result = api.post(
        "/api/v1/datasets/import",
        data={"dataset_name": "gold"},
        files={
            "file": (
                "gold.jsonl",
                io.BytesIO(
                    b'{"case_id":"q1","question":"Q1","reference_answer":"A1"}\n'
                    b'{"case_id":"q2","question":"Q2","reference_answer":"A2"}'
                ),
            )
        },
    )
    assert result.status_code == 201
    return str(result.json()["dataset_id"])


def test_existing_dataset_csv_mapping_keeps_prediction_order(tmp_path: Path) -> None:
    api = client(tmp_path)
    dataset_id = gold(api)
    content = (
        "id,response,passages\n"
        'q1,A1,"[{""text"":""first"",""document_id"":""doc-1""},'
        '{""text"":""second"",""document_id"":""doc-2""}]"\n'
    )
    result = upload(
        api,
        content,
        filename="predictions.csv",
        dataset_id=dataset_id,
        mapping={"case_id": "id", "answer": "response", "contexts": "passages"},
    )
    assert result.status_code == 201, result.text
    summary = result.json()
    assert summary["dataset_version"] == 1
    assert summary["matched_count"] == 1
    assert summary["missing_case_count"] == 1
    detail = api.get(f"/api/v1/predictions/{summary['id']}").json()
    assert detail["predictions"][0]["answer"] == "A1"
    assert [item["text"] for item in detail["predictions"][0]["contexts"]] == ["first", "second"]
    assert [item["document_id"] for item in detail["predictions"][0]["contexts"]] == [
        "doc-1",
        "doc-2",
    ]


def test_one_file_creates_gold_and_prediction_batch_atomically(tmp_path: Path) -> None:
    api = client(tmp_path)
    row = {
        "case_id": "q1",
        "question": "Q1",
        "reference_answer": "A1",
        "reference_chunks": [{"text": "gold", "document_id": "doc-1"}],
        "answer": "predicted",
        "contexts": [{"text": "retrieved", "document_id": "doc-1"}],
    }
    result = upload(api, json.dumps(row), dataset_name="combined")
    assert result.status_code == 201, result.text
    summary = result.json()
    assert summary["dataset_version"] == 1
    assert summary["matched_count"] == 1
    dataset = api.get(f"/api/v1/datasets/{summary['dataset_id']}/versions/1").json()
    assert dataset["cases"][0]["reference_answer"] == "A1"
    assert api.get("/api/v1/predictions").json()[0]["id"] == summary["id"]


def test_invalid_combined_file_creates_neither_dataset_nor_batch(tmp_path: Path) -> None:
    api = client(tmp_path)
    rows = [
        {
            "case_id": "q1",
            "question": "Q1",
            "reference_answer": "A1",
            "answer": "P1",
            "contexts": [{"text": "body", "document_id": "d"}],
        },
        {
            "case_id": "q1",
            "question": "Q2",
            "reference_answer": "A2",
            "answer": "P2",
            "contexts": [{"text": "body"}],
        },
    ]
    result = upload(api, "\n".join(json.dumps(row) for row in rows), dataset_name="invalid")
    assert result.status_code == 422
    issues = {(issue["line"], issue["code"]) for issue in result.json()["issues"]}
    assert (2, "duplicate_case_id") in issues
    assert (2, "missing_field") in issues
    assert api.get("/api/v1/datasets").json() == []
    assert api.get("/api/v1/predictions").json() == []


def test_unknown_case_and_missing_selected_field_reject_whole_batch(tmp_path: Path) -> None:
    api = client(tmp_path)
    dataset_id = gold(api)
    rows = [
        {"case_id": "q1", "answer": "P1"},
        {"case_id": "unknown", "answer": "P2", "contexts": [{"text": "body", "document_id": "d"}]},
    ]
    result = upload(api, "\n".join(json.dumps(row) for row in rows), dataset_id=dataset_id)
    assert result.status_code == 422
    assert {(item["line"], item["code"]) for item in result.json()["issues"]} >= {
        (1, "missing_contexts"),
        (2, "unknown_case_id"),
    }
    assert api.get("/api/v1/predictions").json() == []


def test_retrieval_only_needs_no_answer_and_versions_remain_bound(tmp_path: Path) -> None:
    api = client(tmp_path)
    dataset_id = gold(api)
    row = {"case_id": "q1", "contexts": [{"text": "body", "document_id": "d"}]}
    result = upload(api, json.dumps(row), dataset_id=dataset_id, evaluation_type="retrieval")
    assert result.status_code == 201, result.text
    summary = result.json()
    assert summary["evaluation_type"] == "retrieval"
    assert (
        api.get(f"/api/v1/predictions/{summary['id']}").json()["predictions"][0]["answer"] is None
    )

    api.post(
        "/api/v1/datasets/import",
        data={"dataset_id": dataset_id},
        files={
            "file": (
                "next.jsonl",
                io.BytesIO(b'{"case_id":"q3","question":"Q3","reference_answer":"A3"}'),
            )
        },
    )
    assert api.get(f"/api/v1/predictions/{summary['id']}").json()["dataset_version"] == 1


def test_invalid_version_and_file_format_do_not_persist(tmp_path: Path) -> None:
    api = client(tmp_path)
    dataset_id = gold(api)
    row = '{"case_id":"q1","answer":"P1"}'
    assert (
        upload(
            api, row, dataset_id=dataset_id, dataset_version=99, evaluation_type="answer"
        ).status_code
        == 404
    )
    invalid = upload(
        api, row, filename="predictions.txt", dataset_id=dataset_id, evaluation_type="answer"
    )
    assert invalid.status_code == 422
    assert invalid.json()["issues"][0]["code"] == "invalid_format"
    assert api.get("/api/v1/predictions").json() == []
