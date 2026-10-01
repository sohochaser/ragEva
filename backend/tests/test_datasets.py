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
    filename: str,
    content: str | bytes,
    *,
    dataset_name: str | None = "示例数据集",
    dataset_id: str | None = None,
    mapping: dict[str, str] | None = None,
) -> Response:
    fields = {}
    if dataset_name is not None:
        fields["dataset_name"] = dataset_name
    if dataset_id is not None:
        fields["dataset_id"] = dataset_id
    if mapping is not None:
        fields["mapping"] = json.dumps(mapping)
    payload = content.encode() if isinstance(content, str) else content
    return api.post(
        "/api/v1/datasets/import",
        data=fields,
        files={"file": (filename, io.BytesIO(payload))},
    )


def test_answer_csv_import_and_browse(tmp_path: Path) -> None:
    api = client(tmp_path)
    result = upload(
        api,
        "answers.csv",
        "case_id,question,reference_answer\n"
        "q1,什么是 RAG？,检索增强生成\n"
        "q2,什么是 chunk？,文档片段\n",
    )
    assert result.status_code == 201
    summary = result.json()
    assert summary["version"] == 1
    assert summary["case_count"] == 2
    assert summary["source_filename"] == "answers.csv"

    datasets = api.get("/api/v1/datasets").json()
    assert [(item["id"], item["latest_version"]) for item in datasets] == [
        (summary["dataset_id"], 1)
    ]
    versions = api.get(f"/api/v1/datasets/{summary['dataset_id']}/versions").json()
    assert [item["version"] for item in versions] == [1]
    detail = api.get(f"/api/v1/datasets/{summary['dataset_id']}/versions/1").json()
    assert detail["total"] == 2
    assert detail["cases"][0] == {
        "case_id": "q1",
        "question": "什么是 RAG？",
        "reference_answer": "检索增强生成",
        "reference_chunks": None,
    }


def test_retrieval_and_mixed_jsonl_keep_reference_order(tmp_path: Path) -> None:
    api = client(tmp_path)
    rows = [
        {
            "case_id": "r1",
            "question": "依据是什么？",
            "reference_chunks": [
                {"text": "更相关的片段", "document_id": "doc-1"},
                {"text": "次相关的片段", "document_id": "doc-1"},
            ],
        },
        {
            "case_id": "m1",
            "question": "结论是什么？",
            "reference_answer": "结论 A",
            "reference_chunks": [{"text": "结论依据", "document_id": "doc-2"}],
        },
    ]
    result = upload(api, "cases.jsonl", "\n".join(json.dumps(row) for row in rows))
    assert result.status_code == 201
    summary = result.json()
    detail = api.get(f"/api/v1/datasets/{summary['dataset_id']}/versions/1").json()
    assert detail["cases"][0]["reference_answer"] is None
    assert [chunk["text"] for chunk in detail["cases"][0]["reference_chunks"]] == [
        "更相关的片段",
        "次相关的片段",
    ]
    assert detail["cases"][1]["reference_answer"] == "结论 A"


def test_csv_field_mapping_and_json_chunk_cell(tmp_path: Path) -> None:
    api = client(tmp_path)
    content = (
        "id,prompt,gold,evidence\n"
        'x-1,问题,答案,"[{""text"":""片段 A"",""document_id"":""doc-7""}]"\n'
    )
    result = upload(
        api,
        "mapped.csv",
        content,
        mapping={
            "case_id": "id",
            "question": "prompt",
            "reference_answer": "gold",
            "reference_chunks": "evidence",
        },
    )
    assert result.status_code == 201
    summary = result.json()
    detail = api.get(f"/api/v1/datasets/{summary['dataset_id']}/versions/1").json()
    assert detail["cases"][0]["reference_chunks"] == [{"text": "片段 A", "document_id": "doc-7"}]


def test_invalid_rows_report_line_and_create_no_version(tmp_path: Path) -> None:
    api = client(tmp_path)
    rows = [
        {"case_id": "same", "question": "有效", "reference_answer": "答案"},
        {"case_id": "same", "question": "重复", "reference_answer": "答案"},
        {"case_id": "empty", "question": "空列表", "reference_chunks": []},
        {"case_id": "missing", "question": "缺少标注"},
        {
            "case_id": "duplicate-chunk",
            "question": "重复片段",
            "reference_chunks": [
                {"text": "相同  正文", "document_id": "doc-1"},
                {"text": " 相同 正文 ", "document_id": "doc-1"},
            ],
        },
    ]
    result = upload(api, "invalid.jsonl", "\n".join(json.dumps(row) for row in rows))
    assert result.status_code == 422
    issues = {(item["line"], item["code"]) for item in result.json()["issues"]}
    assert (2, "duplicate_case_id") in issues
    assert (3, "empty_reference_chunks") in issues
    assert (4, "missing_annotation") in issues
    assert (5, "duplicate_reference_chunk") in issues
    assert api.get("/api/v1/datasets").json() == []


def test_new_version_reuses_case_id_without_changing_old_version(tmp_path: Path) -> None:
    api = client(tmp_path)
    first = upload(api, "v1.jsonl", '{"case_id":"same","question":"Q","reference_answer":"A1"}')
    dataset_id = first.json()["dataset_id"]
    second = upload(
        api,
        "v2.jsonl",
        '{"case_id":"same","question":"Q","reference_answer":"A2"}',
        dataset_name=None,
        dataset_id=dataset_id,
    )
    assert second.status_code == 201
    assert second.json()["version"] == 2
    old = api.get(f"/api/v1/datasets/{dataset_id}/versions/1").json()
    new = api.get(f"/api/v1/datasets/{dataset_id}/versions/2").json()
    assert old["cases"][0]["reference_answer"] == "A1"
    assert new["cases"][0]["reference_answer"] == "A2"
    assert len(api.get(f"/api/v1/datasets/{dataset_id}/versions").json()) == 2


def test_failed_import_does_not_add_version_to_existing_dataset(tmp_path: Path) -> None:
    api = client(tmp_path)
    first = upload(api, "v1.jsonl", '{"case_id":"same","question":"Q","reference_answer":"A1"}')
    dataset_id = first.json()["dataset_id"]
    invalid = upload(
        api,
        "v2.jsonl",
        '{"case_id":"same","question":"Q","reference_chunks":[]}',
        dataset_name=None,
        dataset_id=dataset_id,
    )
    assert invalid.status_code == 422
    assert [
        version["version"] for version in api.get(f"/api/v1/datasets/{dataset_id}/versions").json()
    ] == [1]
    assert (
        api.get(f"/api/v1/datasets/{dataset_id}/versions/1").json()["cases"][0]["reference_answer"]
        == "A1"
    )


def test_mapping_and_chunk_field_errors_are_located(tmp_path: Path) -> None:
    api = client(tmp_path)
    missing_column = upload(
        api,
        "columns.csv",
        "case_id,question,reference_answer\nq,Q,A\n",
        mapping={"reference_chunks": "evidence"},
    )
    assert missing_column.status_code == 422
    assert missing_column.json()["issues"][0]["line"] == 1
    assert missing_column.json()["issues"][0]["code"] == "missing_column"

    bad_chunk = upload(
        api,
        "chunk.jsonl",
        '{"case_id":"q","question":"Q","reference_chunks":[{"text":"body"}]}',
    )
    assert bad_chunk.status_code == 422
    assert any(
        issue["field"] == "reference_chunks[0].document_id" for issue in bad_chunk.json()["issues"]
    )
    assert api.get("/api/v1/datasets").json() == []


def test_bad_file_and_unknown_dataset_do_not_create_partial_data(tmp_path: Path) -> None:
    api = client(tmp_path)
    assert upload(api, "bad.jsonl", b"\xff").status_code == 422
    assert upload(api, "bad.txt", "anything").status_code == 422
    malformed = upload(api, "bad.jsonl", '{"case_id":')
    assert malformed.status_code == 422
    assert malformed.json()["issues"][0]["line"] == 1
    unknown = upload(
        api,
        "good.jsonl",
        '{"case_id":"q","question":"Q","reference_answer":"A"}',
        dataset_name=None,
        dataset_id="not-found",
    )
    assert unknown.status_code == 404
    assert api.get("/api/v1/datasets").json() == []


def test_version_detail_is_paginated(tmp_path: Path) -> None:
    api = client(tmp_path)
    content = "\n".join(
        json.dumps({"case_id": f"q{number}", "question": "Q", "reference_answer": "A"})
        for number in range(3)
    )
    summary = upload(api, "pages.jsonl", content).json()
    detail = api.get(f"/api/v1/datasets/{summary['dataset_id']}/versions/1?offset=1&limit=1").json()
    assert detail["total"] == 3
    assert [case["case_id"] for case in detail["cases"]] == ["q1"]
