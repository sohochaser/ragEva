"""Immutable versions of user-editable answer criteria."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.adapters.dataset_store import DatasetStore
from backend.domain.answer_prompts import PROMPT_VERSION

SCENARIO_SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluation_scenarios (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scenario_versions (
    id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL REFERENCES evaluation_scenarios(id),
    version INTEGER NOT NULL,
    faithfulness TEXT NOT NULL,
    relevance TEXT NOT NULL,
    correctness TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(scenario_id, version)
);
"""


class ScenarioNotFound(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ScenarioStore(DatasetStore):
    def __init__(self, data_dir: Path) -> None:
        super().__init__(data_dir)

    def _connect(self) -> sqlite3.Connection:
        connection = super()._connect()
        connection.executescript(SCENARIO_SCHEMA)
        return connection

    def create(
        self, name: str, faithfulness: str, relevance: str, correctness: str
    ) -> dict[str, Any]:
        scenario_id = str(uuid4())
        created_at = _now()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO evaluation_scenarios (id, name, created_at) VALUES (?, ?, ?)",
                (scenario_id, name, created_at),
            )
            connection.execute(
                "INSERT INTO scenario_versions "
                "(id, scenario_id, version, faithfulness, relevance, correctness, "
                "prompt_version, created_at) VALUES (?, ?, 1, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    scenario_id,
                    faithfulness,
                    relevance,
                    correctness,
                    PROMPT_VERSION,
                    created_at,
                ),
            )
        return self.get_scenario_version(scenario_id, 1)

    def update(
        self, scenario_id: str, faithfulness: str, relevance: str, correctness: str
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS latest FROM scenario_versions "
                "WHERE scenario_id = ?",
                (scenario_id,),
            ).fetchone()
            if row["latest"] == 0:
                raise ScenarioNotFound(scenario_id)
            version = int(row["latest"]) + 1
            connection.execute(
                "INSERT INTO scenario_versions "
                "(id, scenario_id, version, faithfulness, relevance, correctness, "
                "prompt_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    scenario_id,
                    version,
                    faithfulness,
                    relevance,
                    correctness,
                    PROMPT_VERSION,
                    _now(),
                ),
            )
        return self.get_scenario_version(scenario_id, version)

    def get_scenario_version(self, scenario_id: str, version: int) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT s.id AS scenario_id, s.name, v.id, v.version, v.faithfulness, "
                "v.relevance, v.correctness, v.prompt_version, v.created_at "
                "FROM scenario_versions v JOIN evaluation_scenarios s ON s.id = v.scenario_id "
                "WHERE s.id = ? AND v.version = ?",
                (scenario_id, version),
            ).fetchone()
        if row is None:
            raise ScenarioNotFound(scenario_id)
        return dict(row)

    def list_versions(self, scenario_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            exists = connection.execute(
                "SELECT 1 FROM evaluation_scenarios WHERE id = ?", (scenario_id,)
            ).fetchone()
            if exists is None:
                raise ScenarioNotFound(scenario_id)
            rows = connection.execute(
                "SELECT version FROM scenario_versions WHERE scenario_id = ? ORDER BY version DESC",
                (scenario_id,),
            ).fetchall()
        return [self.get_scenario_version(scenario_id, row["version"]) for row in rows]

    def list_scenarios(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT s.id, MAX(v.version) AS version FROM evaluation_scenarios s "
                "JOIN scenario_versions v ON v.scenario_id = s.id "
                "GROUP BY s.id ORDER BY s.created_at DESC, s.id DESC"
            ).fetchall()
        return [self.get_scenario_version(row["id"], row["version"]) for row in rows]
