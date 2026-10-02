import io
import json
import sqlite3
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from backend.api.main import create_app as create_management_app
from backend.config import DownloadSettings, Settings
from backend.download import __main__ as download_main
from backend.download.app import create_app as create_download_app


def clients(tmp_path: Path) -> tuple[TestClient, TestClient]:
    management = TestClient(create_management_app(Settings(data_dir=tmp_path)))
    download = TestClient(
        create_download_app(
            DownloadSettings(
                data_dir=tmp_path,
                token="download-secret",
                public_url="https://files.example.test/rageva",
            )
        )
    )
    return management, download


def auth(token: str = "download-secret") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_manifest_urls_return_exact_original_bytes_and_ids(tmp_path: Path) -> None:
    management, download = clients(tmp_path)
    contents = [("说明.md", b"\xef\xbb\xbfhello\n"), ("guide.txt", b"second file")]
    created = management.post(
        "/api/v1/document-collections",
        data={"name": "sources", "document_ids": '["source-1", null]'},
        files=[("files", (name, io.BytesIO(content))) for name, content in contents],
    )
    assert created.status_code == 201, created.text
    collection_id = created.json()["id"]

    response = download.get(f"/download/v1/collections/{collection_id}/manifest", headers=auth())
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    manifest = response.json()
    assert manifest["collection_id"] == collection_id
    assert manifest["source_kind"] == "original_files"
    assert [item["document_id"] for item in manifest["documents"]] == ["source-1", "guide-1"]
    for item, (filename, content) in zip(manifest["documents"], contents, strict=True):
        assert item["filename"] == filename
        assert item["checksum"] == sha256(content).hexdigest()
        url = urlsplit(item["download_url"])
        assert f"{url.scheme}://{url.netloc}" == "https://files.example.test"
        assert url.path.startswith("/rageva/download/v1/documents/")
        path = url.path.removeprefix("/rageva")
        file_response = download.get(path, headers=auth())
        assert file_response.status_code == 200
        assert file_response.content == content
        assert file_response.headers["x-content-sha256"] == item["checksum"]
        assert file_response.headers["content-type"] == "application/octet-stream"


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic download-secret"}]
)
def test_both_routes_require_independent_bearer_token(
    tmp_path: Path, headers: dict[str, str]
) -> None:
    management, download = clients(tmp_path)
    created = management.post(
        "/api/v1/document-collections",
        data={"name": "sources"},
        files={"files": ("a.txt", io.BytesIO(b"hello"))},
    )
    collection_id = created.json()["id"]
    with sqlite3.connect(tmp_path / "rageva.sqlite3") as connection:
        document_pk = connection.execute("SELECT id FROM source_documents").fetchone()[0]
    for path in (
        f"/download/v1/collections/{collection_id}/manifest",
        f"/download/v1/documents/{document_pk}/file",
    ):
        response = download.get(path, headers=headers)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert "download-secret" not in response.text


def test_chunk_only_has_no_file_urls_and_file_route_rejects_it(tmp_path: Path) -> None:
    management, download = clients(tmp_path)
    created = management.post(
        "/api/v1/document-collections/import-chunks",
        data={"name": "existing chunks"},
        files={
            "file": (
                "chunks.jsonl",
                io.BytesIO(
                    json.dumps({"position": 0, "document_id": "d-1", "text": "one"}).encode()
                ),
            )
        },
    )
    assert created.status_code == 201, created.text
    collection_id = created.json()["id"]
    manifest = download.get(f"/download/v1/collections/{collection_id}/manifest", headers=auth())
    assert manifest.status_code == 200
    assert manifest.json()["source_kind"] == "chunks_only"
    assert manifest.json()["documents"] == []
    with sqlite3.connect(tmp_path / "rageva.sqlite3") as connection:
        document_pk = connection.execute(
            "SELECT id FROM source_documents WHERE collection_id = ?", (collection_id,)
        ).fetchone()[0]
    assert (
        download.get(f"/download/v1/documents/{document_pk}/file", headers=auth()).status_code
        == 404
    )


def test_unknown_ids_traversal_and_management_routes_are_not_exposed(tmp_path: Path) -> None:
    management, download = clients(tmp_path)
    assert (
        download.get("/download/v1/collections/missing/manifest", headers=auth()).status_code == 404
    )
    assert download.get("/download/v1/documents/missing/file", headers=auth()).status_code == 404
    assert (
        download.get("/download/v1/documents/%2e%2e%2fsecret/file", headers=auth()).status_code
        == 404
    )
    assert download.get("/api/v1/document-collections", headers=auth()).status_code == 404
    assert download.get("/docs", headers=auth()).status_code == 404
    assert download.get("/openapi.json", headers=auth()).status_code == 404
    assert management.get("/download/v1/collections/missing/manifest").status_code == 404


def test_download_settings_and_process_use_separate_listener(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = {
        "RAGEVA_DATA_DIR": str(tmp_path),
        "RAGEVA_DOWNLOAD_TOKEN": "secret",
        "RAGEVA_DOWNLOAD_HOST": "0.0.0.0",
        "RAGEVA_DOWNLOAD_PORT": "9443",
        "RAGEVA_DOWNLOAD_PUBLIC_URL": "https://files.example.test/prefix/",
    }
    settings = DownloadSettings.from_env(values)
    assert settings.host == "0.0.0.0"
    assert settings.port == 9443
    assert settings.public_url == "https://files.example.test/prefix"
    assert settings.data_dir == tmp_path
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    called: dict[str, object] = {}

    def fake_run(app: object, *, host: str, port: int) -> None:
        called.update(app=app, host=host, port=port)

    monkeypatch.setattr(download_main.uvicorn, "run", fake_run)
    assert download_main.main() == 0
    assert called["host"] == "0.0.0.0"
    assert called["port"] == 9443


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RAGEVA_DOWNLOAD_TOKEN", " "),
        ("RAGEVA_DOWNLOAD_HOST", " "),
        ("RAGEVA_DOWNLOAD_PORT", "0"),
        ("RAGEVA_DOWNLOAD_PORT", "65536"),
        ("RAGEVA_DOWNLOAD_PUBLIC_URL", "ftp://files.example.test"),
        ("RAGEVA_DOWNLOAD_PUBLIC_URL", "https://user:pass@files.example.test"),
        ("RAGEVA_DOWNLOAD_PUBLIC_URL", "https://files.example.test/?token=secret"),
    ],
)
def test_invalid_download_configuration_is_rejected(name: str, value: str) -> None:
    values = {"RAGEVA_DOWNLOAD_TOKEN": "secret", name: value}
    with pytest.raises(ValueError, match=name):
        DownloadSettings.from_env(values)
