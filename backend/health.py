"""Shared worker heartbeat observed by the management API."""

import os
import sqlite3
import time
from pathlib import Path


def _database(data_dir: Path) -> Path:
    return data_dir / "health.sqlite3"


def write_worker_heartbeat(data_dir: Path, pid: int, now: float | None = None) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_database(data_dir), timeout=5) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS worker_heartbeat "
            "(id INTEGER PRIMARY KEY CHECK (id = 1), "
            "pid INTEGER NOT NULL, updated_at REAL NOT NULL)"
        )
        connection.execute(
            "INSERT INTO worker_heartbeat (id, pid, updated_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET pid=excluded.pid, updated_at=excluded.updated_at",
            (pid, time.time() if now is None else now),
        )


def clear_worker_heartbeat(data_dir: Path, pid: int) -> None:
    if not _database(data_dir).exists():
        return
    with sqlite3.connect(_database(data_dir), timeout=5) as connection:
        connection.execute("DELETE FROM worker_heartbeat WHERE id = 1 AND pid = ?", (pid,))


def worker_is_ready(data_dir: Path, stale_after: int, now: float | None = None) -> bool:
    if not _database(data_dir).exists():
        return False
    try:
        with sqlite3.connect(_database(data_dir), timeout=5) as connection:
            row = connection.execute(
                "SELECT pid, updated_at FROM worker_heartbeat WHERE id = 1"
            ).fetchone()
    except sqlite3.Error:
        return False
    if row is None:
        return False
    pid, updated_at = row
    age = (time.time() if now is None else now) - updated_at
    if age < 0 or age > stale_after:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True
