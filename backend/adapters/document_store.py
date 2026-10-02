"""Atomic SQLite snapshots of source files and their ordered chunks."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.domain.chunk_manifests import ManifestChunk
from backend.domain.document_collections import SourceDocument

SCHEMA = """
CREATE TABLE IF NOT EXISTS document_collections (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('original_files', 'chunks_only')),
    chunk_size INTEGER NOT NULL,
    chunk_overlap INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_documents (
    id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES document_collections(id),
    position INTEGER NOT NULL,
    filename TEXT,
    document_id TEXT NOT NULL,
    checksum TEXT,
    content BLOB,
    CHECK ((filename IS NOT NULL AND checksum IS NOT NULL AND content IS NOT NULL)
       OR (filename IS NULL AND checksum IS NULL AND content IS NULL)),
    UNIQUE(collection_id, document_id),
    UNIQUE(collection_id, position)
);
CREATE TABLE IF NOT EXISTS source_chunks (
    document_pk TEXT NOT NULL REFERENCES source_documents(id),
    position INTEGER NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY(document_pk, position)
);
"""


class CollectionNotFound(Exception):
    pass


class DocumentStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "rageva.sqlite3"

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        return connection

    def create(
        self, name: str, documents: list[SourceDocument], chunk_size: int, chunk_overlap: int
    ) -> dict[str, Any]:
        collection_id = str(uuid4())
        created_at = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO document_collections VALUES (?, ?, ?, ?, ?, ?)",
                (collection_id, name, "original_files", chunk_size, chunk_overlap, created_at),
            )
            for position, document in enumerate(documents):
                document_pk = str(uuid4())
                connection.execute(
                    "INSERT INTO source_documents VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        document_pk,
                        collection_id,
                        position,
                        document.filename,
                        document.document_id,
                        document.checksum,
                        document.content,
                    ),
                )
                connection.executemany(
                    "INSERT INTO source_chunks VALUES (?, ?, ?)",
                    [(document_pk, index, text) for index, text in enumerate(document.chunks)],
                )
        return self.get(collection_id)

    def create_from_chunks(self, name: str, chunks: list[ManifestChunk]) -> dict[str, Any]:
        if not chunks:
            raise ValueError("chunk 清单不能为空")
        collection_id = str(uuid4())
        created_at = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO document_collections VALUES (?, ?, ?, ?, ?, ?)",
                (collection_id, name, "chunks_only", 0, 0, created_at),
            )
            document_pks: dict[str, str] = {}
            for chunk in chunks:
                document_pk = document_pks.get(chunk.document_id)
                if document_pk is None:
                    document_pk = str(uuid4())
                    document_pks[chunk.document_id] = document_pk
                    connection.execute(
                        "INSERT INTO source_documents VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            document_pk,
                            collection_id,
                            len(document_pks) - 1,
                            None,
                            chunk.document_id,
                            None,
                            None,
                        ),
                    )
                connection.execute(
                    "INSERT INTO source_chunks VALUES (?, ?, ?)",
                    (document_pk, chunk.position, chunk.text),
                )
        return self.get(collection_id)

    def list(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT c.id, c.name, c.source_kind, c.chunk_size, c.chunk_overlap, c.created_at, "
                "COUNT(d.id) AS document_count FROM document_collections c "
                "LEFT JOIN source_documents d ON d.collection_id = c.id "
                "GROUP BY c.id ORDER BY c.created_at DESC, c.id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, collection_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT id, name, source_kind, chunk_size, chunk_overlap, created_at "
                "FROM document_collections WHERE id = ?",
                (collection_id,),
            ).fetchone()
            if row is None:
                raise CollectionNotFound(collection_id)
            documents = connection.execute(
                "SELECT id, filename, document_id, checksum, LENGTH(content) AS byte_count "
                "FROM source_documents WHERE collection_id = ? ORDER BY position",
                (collection_id,),
            ).fetchall()
            details = []
            ordered_chunks = []
            for document in documents:
                chunks = connection.execute(
                    "SELECT position, text FROM source_chunks "
                    "WHERE document_pk = ? ORDER BY position",
                    (document["id"],),
                ).fetchall()
                details.append(
                    {
                        "filename": document["filename"],
                        "document_id": document["document_id"],
                        "checksum": document["checksum"],
                        "byte_count": document["byte_count"],
                        "has_original_file": document["filename"] is not None,
                        "chunks": [dict(chunk) for chunk in chunks],
                    }
                )
                for chunk in chunks:
                    ordered_chunks.append(
                        {
                            "position": chunk["position"],
                            "document_id": document["document_id"],
                            "text": chunk["text"],
                        }
                    )
        if row["source_kind"] == "chunks_only":
            ordered_chunks.sort(key=lambda chunk: chunk["position"])
        else:
            for position, chunk in enumerate(ordered_chunks):
                chunk["position"] = position
        return {
            **dict(row),
            "document_count": len(details),
            "documents": details,
            "chunks": ordered_chunks,
        }
