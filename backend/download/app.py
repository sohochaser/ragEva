"""Token-protected manifest and original file routes, separate from the management API."""

from secrets import compare_digest
from urllib.parse import quote

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from backend.adapters.document_store import (
    CollectionNotFound,
    DocumentStore,
    OriginalFileNotFound,
)
from backend.config import DownloadSettings


class DownloadDocument(BaseModel):
    document_id: str
    filename: str
    checksum: str
    download_url: str


class DownloadManifest(BaseModel):
    collection_id: str
    name: str
    source_kind: str
    documents: list[DownloadDocument]


def create_app(settings: DownloadSettings | None = None) -> FastAPI:
    config = settings or DownloadSettings.from_env()
    store = DocumentStore(config.data_dir)
    application = FastAPI(
        title="ragEva document download",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def authorize(authorization: str | None = Header(default=None)) -> None:
        scheme, separator, credential = (authorization or "").partition(" ")
        if (
            not separator
            or scheme.lower() != "bearer"
            or not compare_digest(credential, config.token)
        ):
            raise HTTPException(
                status_code=401,
                detail="Invalid download token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @application.get(
        "/download/v1/collections/{collection_id}/manifest",
        response_model=DownloadManifest,
        dependencies=[Depends(authorize)],
    )
    def manifest(collection_id: str, response: Response) -> DownloadManifest:
        try:
            collection = store.get_download_manifest(collection_id)
        except CollectionNotFound as exc:
            raise HTTPException(status_code=404, detail="Collection not found") from exc
        documents = [
            DownloadDocument(
                document_id=document["document_id"],
                filename=document["filename"],
                checksum=document["checksum"],
                download_url=f"{config.public_url}/download/v1/documents/{document['id']}/file",
            )
            for document in collection["documents"]
        ]
        response.headers["Cache-Control"] = "private, no-store"
        return DownloadManifest(
            collection_id=collection["id"],
            name=collection["name"],
            source_kind=collection["source_kind"],
            documents=documents,
        )

    @application.get("/download/v1/documents/{document_pk}/file", dependencies=[Depends(authorize)])
    def original_file(document_pk: str) -> Response:
        try:
            document = store.get_original_file(document_pk)
        except OriginalFileNotFound as exc:
            raise HTTPException(status_code=404, detail="Original file not found") from exc
        filename = quote(document["filename"], safe="")
        return Response(
            content=document["content"],
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
                "X-Content-SHA256": document["checksum"],
                "Cache-Control": "private, no-store",
            },
        )

    return application
