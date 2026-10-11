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
    created_at TEXT NOT NULL,
    group_id TEXT,
    version INTEGER
);
CREATE TABLE IF NOT EXISTS collection_groups (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    current_snapshot_id TEXT NOT NULL
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


class OriginalFileNotFound(Exception):
    pass


class CollectionConflict(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class DocumentStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "rageva.sqlite3"

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(document_collections)")
        }
        if "group_id" not in columns:
            connection.execute("ALTER TABLE document_collections ADD COLUMN group_id TEXT")
        if "version" not in columns:
            connection.execute("ALTER TABLE document_collections ADD COLUMN version INTEGER")
        connection.execute(
            "UPDATE document_collections SET group_id = id, version = 1 WHERE group_id IS NULL"
        )
        connection.execute(
            "INSERT OR IGNORE INTO collection_groups "
            "SELECT id, name, lower(trim(name)), source_kind, id "
            "FROM document_collections WHERE id = group_id"
        )
        connection.commit()
        return connection

    @staticmethod
    def _key(name: str) -> str:
        return name.strip().casefold()

    def resolve(
        self, name: str, source_kind: str, group_id: str | None = None
    ) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            group = self._select_group(connection, name, source_kind, group_id)
            if group is None:
                return None
            return self.get(group["current_snapshot_id"])

    def _select_group(
        self, connection: sqlite3.Connection, name: str, source_kind: str, group_id: str | None
    ) -> sqlite3.Row | None:
        rows = connection.execute("SELECT * FROM collection_groups").fetchall()
        matches = [row for row in rows if self._key(row["name"]) == self._key(name)]
        if group_id:
            selected = next((row for row in matches if row["id"] == group_id), None)
            if selected is None:
                raise CollectionConflict("unknown_selection")
        elif len(matches) > 1:
            raise CollectionConflict("ambiguous_name")
        else:
            selected = matches[0] if matches else None
        if selected is not None and selected["source_kind"] != source_kind:
            raise CollectionConflict("source_kind_conflict")
        return selected

    def versions(self, collection_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT group_id FROM document_collections WHERE id = ?", (collection_id,)
            ).fetchone()
            if row is None:
                raise CollectionNotFound(collection_id)
            rows = connection.execute(
                "SELECT c.id, c.name, c.source_kind, c.chunk_size, c.chunk_overlap, "
                "c.created_at, c.group_id, c.version, COUNT(d.id) AS document_count "
                "FROM document_collections c LEFT JOIN source_documents d "
                "ON d.collection_id = c.id "
                "WHERE c.group_id = ? GROUP BY c.id ORDER BY c.version DESC",
                (row["group_id"],),
            ).fetchall()
            return [dict(item) for item in rows]

    def create(
        self, name: str, documents: list[SourceDocument], chunk_size: int, chunk_overlap: int
    ) -> dict[str, Any]:
        return self.save_documents(name, documents, chunk_size, chunk_overlap)

    def _begin_snapshot(
        self,
        connection: sqlite3.Connection,
        name: str,
        source_kind: str,
        chunk_size: int,
        chunk_overlap: int,
        group_id: str | None,
        expected_version: int | None,
        new_ids: set[str],
    ) -> tuple[str, str, int, int]:
        group = self._select_group(connection, name, source_kind, group_id)
        collection_id = str(uuid4())
        created_at = datetime.now(UTC).isoformat()
        previous_id = None
        if group is None:
            if group_id is not None:
                raise CollectionConflict("unknown_selection")
            group_id = collection_id
            version = 1
            connection.execute(
                "INSERT INTO collection_groups VALUES (?, ?, ?, ?, ?)",
                (group_id, name, self._key(name), source_kind, collection_id),
            )
            old_count = 0
        else:
            group_id = group["id"]
            previous_id = group["current_snapshot_id"]
            old = connection.execute(
                "SELECT version, chunk_size, chunk_overlap FROM document_collections WHERE id = ?",
                (previous_id,),
            ).fetchone()
            if old is None:
                raise CollectionConflict("missing_snapshot")
            if expected_version is not None and old["version"] != expected_version:
                raise CollectionConflict("stale_version")
            if source_kind == "original_files" and (
                chunk_size != old["chunk_size"] or chunk_overlap != old["chunk_overlap"]
            ):
                raise CollectionConflict("chunk_config_conflict")
            present = {
                item["document_id"]
                for item in connection.execute(
                    "SELECT document_id FROM source_documents WHERE collection_id = ?",
                    (previous_id,),
                )
            }
            if new_ids & present:
                raise CollectionConflict("duplicate_document_id")
            version = old["version"] + 1
            old_count = connection.execute(
                "SELECT COUNT(*) FROM source_chunks c JOIN source_documents d "
                "ON d.id = c.document_pk "
                "WHERE d.collection_id = ?",
                (previous_id,),
            ).fetchone()[0]
        connection.execute(
            "INSERT INTO document_collections "
            "(id, name, source_kind, chunk_size, chunk_overlap, created_at, group_id, version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                collection_id,
                group["name"] if group else name,
                source_kind,
                chunk_size,
                chunk_overlap,
                created_at,
                group_id,
                version,
            ),
        )
        if previous_id:
            old_documents = connection.execute(
                "SELECT * FROM source_documents WHERE collection_id = ? ORDER BY position",
                (previous_id,),
            ).fetchall()
            for old_document in old_documents:
                new_pk = str(uuid4())
                connection.execute(
                    "INSERT INTO source_documents VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        new_pk,
                        collection_id,
                        old_document["position"],
                        old_document["filename"],
                        old_document["document_id"],
                        old_document["checksum"],
                        old_document["content"],
                    ),
                )
                connection.execute(
                    "INSERT INTO source_chunks SELECT ?, position, text FROM source_chunks "
                    "WHERE document_pk = ?",
                    (new_pk, old_document["id"]),
                )
            connection.execute(
                "UPDATE collection_groups SET current_snapshot_id = ? WHERE id = ?",
                (collection_id, group_id),
            )
        return collection_id, group_id, version, old_count

    def save_documents(
        self,
        name: str,
        documents: list[SourceDocument],
        chunk_size: int,
        chunk_overlap: int,
        group_id: str | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            collection_id, _, _, _ = self._begin_snapshot(
                connection,
                name,
                "original_files",
                chunk_size,
                chunk_overlap,
                group_id,
                expected_version,
                {document.document_id for document in documents},
            )
            offset = connection.execute(
                "SELECT COUNT(*) FROM source_documents WHERE collection_id = ?", (collection_id,)
            ).fetchone()[0]
            for position, document in enumerate(documents, start=offset):
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
        return self.save_chunks(name, chunks)

    def save_chunks(
        self,
        name: str,
        chunks: list[ManifestChunk],
        group_id: str | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        if not chunks:
            raise ValueError("chunk 清单不能为空")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            collection_id, _, _, old_count = self._begin_snapshot(
                connection,
                name,
                "chunks_only",
                0,
                0,
                group_id,
                expected_version,
                {chunk.document_id for chunk in chunks},
            )
            document_pks: dict[str, str] = {}
            document_offset = connection.execute(
                "SELECT COUNT(*) FROM source_documents WHERE collection_id = ?", (collection_id,)
            ).fetchone()[0]
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
                            document_offset + len(document_pks) - 1,
                            None,
                            chunk.document_id,
                            None,
                            None,
                        ),
                    )
                connection.execute(
                    "INSERT INTO source_chunks VALUES (?, ?, ?)",
                    (document_pk, old_count + chunk.position, chunk.text),
                )
        return self.get(collection_id)

    def list(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT c.id, c.name, c.source_kind, c.chunk_size, c.chunk_overlap, c.created_at, "
                "c.group_id, c.version, "
                "COUNT(d.id) AS document_count FROM document_collections c "
                "JOIN collection_groups g ON g.current_snapshot_id = c.id "
                "LEFT JOIN source_documents d ON d.collection_id = c.id "
                "GROUP BY c.id ORDER BY c.created_at DESC, c.id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, collection_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT id, name, source_kind, chunk_size, chunk_overlap, created_at, "
                "group_id, version "
                "FROM document_collections WHERE id = ?",
                (collection_id,),
            ).fetchone()
            if row is None:
                raise CollectionNotFound(collection_id)
            previous = connection.execute(
                "SELECT id FROM document_collections WHERE group_id = ? AND version = ?",
                (row["group_id"], row["version"] - 1),
            ).fetchone()
            previous_documents = 0
            previous_chunks = 0
            if previous is not None:
                previous_documents = connection.execute(
                    "SELECT COUNT(*) FROM source_documents WHERE collection_id = ?",
                    (previous["id"],),
                ).fetchone()[0]
                previous_chunks = connection.execute(
                    "SELECT COUNT(*) FROM source_chunks c JOIN source_documents d "
                    "ON d.id = c.document_pk WHERE d.collection_id = ?",
                    (previous["id"],),
                ).fetchone()[0]
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
            "added_document_count": len(details) - previous_documents,
            "added_chunk_count": len(ordered_chunks) - previous_chunks,
            "documents": details,
            "chunks": ordered_chunks,
        }

    def get_download_manifest(self, collection_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            collection = connection.execute(
                "SELECT id, name, source_kind FROM document_collections WHERE id = ?",
                (collection_id,),
            ).fetchone()
            if collection is None:
                raise CollectionNotFound(collection_id)
            documents = connection.execute(
                "SELECT id, document_id, filename, checksum FROM source_documents "
                "WHERE collection_id = ? AND filename IS NOT NULL ORDER BY position",
                (collection_id,),
            ).fetchall()
        return {**dict(collection), "documents": [dict(document) for document in documents]}

    def get_original_file(self, document_pk: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            document = connection.execute(
                "SELECT d.filename, d.checksum, d.content FROM source_documents d "
                "JOIN document_collections c ON c.id = d.collection_id "
                "WHERE d.id = ? AND c.source_kind = 'original_files' "
                "AND d.content IS NOT NULL",
                (document_pk,),
            ).fetchone()
        if document is None:
            raise OriginalFileNotFound(document_pk)
        return dict(document)
