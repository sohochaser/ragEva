"""Saved online model endpoints with separate private credentials."""

import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.adapters.dataset_store import DatasetStore

MODEL_SCHEMA = """
CREATE TABLE IF NOT EXISTS online_models (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    model_name TEXT NOT NULL,
    has_token INTEGER NOT NULL,
    timeout_seconds REAL NOT NULL,
    created_at TEXT NOT NULL
);
"""


class OnlineModelNotFound(Exception):
    pass


class OnlineModelInUse(Exception):
    pass


class OnlineModelStore(DatasetStore):
    def __init__(self, data_dir: Path) -> None:
        super().__init__(data_dir)
        self.secret_dir = data_dir / "secrets" / "models"

    def _connect(self) -> sqlite3.Connection:
        connection = super()._connect()
        connection.executescript(MODEL_SCHEMA)
        return connection

    def create(
        self,
        name: str,
        base_url: str,
        model_name: str,
        token: str | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        model_id = str(uuid4())
        secret_path = self.secret_dir / model_id
        if token:
            self.secret_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(secret_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(token)
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    "INSERT INTO online_models "
                    "(id, name, base_url, model_name, has_token, timeout_seconds, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        model_id,
                        name,
                        base_url.rstrip("/"),
                        model_name,
                        bool(token),
                        timeout_seconds,
                        datetime.now(UTC).isoformat(),
                    ),
                )
        except Exception:
            secret_path.unlink(missing_ok=True)
            raise
        return self.get(model_id)

    def get(self, model_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM online_models WHERE id = ?", (model_id,)
            ).fetchone()
        if row is None:
            raise OnlineModelNotFound(model_id)
        return {**dict(row), "has_token": bool(row["has_token"])}

    def list_models(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id FROM online_models ORDER BY created_at DESC, id DESC"
            ).fetchall()
        return [self.get(row["id"]) for row in rows]

    def token(self, model_id: str) -> str | None:
        if not self.get(model_id)["has_token"]:
            return None
        return (self.secret_dir / model_id).read_text(encoding="utf-8")

    def _replace_secret(self, model_id: str, token: str | None) -> None:
        secret_path = self.secret_dir / model_id
        if token is None:
            secret_path.unlink(missing_ok=True)
            return
        self.secret_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.secret_dir / f".{model_id}.{uuid4().hex}"
        try:
            descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(token)
            os.replace(temporary, secret_path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _ensure_idle(connection: sqlite3.Connection, model_id: str) -> None:
        sources = (
            ("generation_runs", "$.model_id"),
            ("evaluation_runs", "$.answer.judge_model_id"),
        )
        for table, path in sources:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()
            if (
                exists
                and connection.execute(
                    f"SELECT 1 FROM {table} WHERE status IN ('queued', 'running') "
                    "AND json_extract(config_json, ?) = ? LIMIT 1",
                    (path, model_id),
                ).fetchone()
            ):
                raise OnlineModelInUse(model_id)

    def ensure_idle(self, model_id: str) -> None:
        with closing(self._connect()) as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM online_models WHERE id = ?", (model_id,)
                ).fetchone()
                is None
            ):
                raise OnlineModelNotFound(model_id)
            self._ensure_idle(connection, model_id)

    def update(
        self,
        model_id: str,
        name: str,
        base_url: str,
        model_name: str,
        timeout_seconds: float,
        *,
        change_token: bool,
        token: str | None,
    ) -> dict[str, Any]:
        secret_path = self.secret_dir / model_id
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT has_token FROM online_models WHERE id = ?", (model_id,)
            ).fetchone()
            if row is None:
                raise OnlineModelNotFound(model_id)
            self._ensure_idle(connection, model_id)
            old_token = secret_path.read_text(encoding="utf-8") if row["has_token"] else None
            try:
                if change_token:
                    self._replace_secret(model_id, token)
                connection.execute(
                    "UPDATE online_models SET name = ?, base_url = ?, model_name = ?, "
                    "has_token = ?, timeout_seconds = ? WHERE id = ?",
                    (
                        name,
                        base_url.rstrip("/"),
                        model_name,
                        bool(token) if change_token else bool(row["has_token"]),
                        timeout_seconds,
                        model_id,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                if change_token:
                    self._replace_secret(model_id, old_token)
                raise
        return self.get(model_id)

    def delete(self, model_id: str) -> None:
        secret_path = self.secret_dir / model_id
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT has_token FROM online_models WHERE id = ?", (model_id,)
            ).fetchone()
            if row is None:
                raise OnlineModelNotFound(model_id)
            self._ensure_idle(connection, model_id)
            old_token = secret_path.read_text(encoding="utf-8") if row["has_token"] else None
            try:
                self._replace_secret(model_id, None)
                connection.execute("DELETE FROM online_models WHERE id = ?", (model_id,))
                connection.commit()
            except Exception:
                connection.rollback()
                if old_token is not None:
                    self._replace_secret(model_id, old_token)
                raise
