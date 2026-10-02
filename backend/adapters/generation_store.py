"""Durable generation jobs, attempts, and reviewable candidates."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.adapters.document_store import DocumentStore
from backend.adapters.generation_model import GeneratedCase
from backend.domain.candidate_duplicates import CHECK_VERSION, compare, overall
from backend.domain.candidate_review import ReviewAction, ReviewIssue, validate_review
from backend.domain.generation import PROMPT_VERSION, GenerationSlot, reference_chunks

SCHEMA = """
CREATE TABLE IF NOT EXISTS generation_runs (
    id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES document_collections(id),
    status TEXT NOT NULL,
    config_json TEXT NOT NULL,
    target_count INTEGER NOT NULL,
    target_multi_count INTEGER NOT NULL,
    max_calls INTEGER NOT NULL,
    max_concurrency INTEGER NOT NULL,
    attempted_count INTEGER NOT NULL DEFAULT 0,
    actual_count INTEGER NOT NULL DEFAULT 0,
    actual_multi_count INTEGER NOT NULL DEFAULT 0,
    shortfall_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS generation_attempts (
    run_id TEXT NOT NULL REFERENCES generation_runs(id),
    attempt_number INTEGER NOT NULL,
    slot_index INTEGER NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    usage_json TEXT,
    PRIMARY KEY(run_id, attempt_number)
);
CREATE TABLE IF NOT EXISTS generated_candidates (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES generation_runs(id),
    slot_index INTEGER NOT NULL,
    question TEXT NOT NULL,
    reference_answer TEXT NOT NULL,
    reference_chunks_json TEXT NOT NULL,
    support_positions_json TEXT NOT NULL,
    multi_chunk INTEGER NOT NULL,
    status TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, slot_index)
);
CREATE TABLE IF NOT EXISTS candidate_revisions (
    candidate_id TEXT NOT NULL REFERENCES generated_candidates(id),
    revision INTEGER NOT NULL,
    question TEXT NOT NULL,
    reference_answer TEXT NOT NULL,
    reference_chunks_json TEXT NOT NULL,
    support_positions_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(candidate_id, revision)
);
CREATE TABLE IF NOT EXISTS candidate_duplicate_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT NOT NULL REFERENCES generated_candidates(id),
    revision INTEGER NOT NULL,
    verdict TEXT NOT NULL,
    matches_json TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidate_duplicate_decisions (
    check_id INTEGER PRIMARY KEY REFERENCES candidate_duplicate_checks(id),
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    decided_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS published_candidate_cases (
    version_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL REFERENCES generated_candidates(id),
    collection_id TEXT NOT NULL,
    question TEXT NOT NULL,
    reference_answer TEXT NOT NULL,
    reference_chunks_json TEXT NOT NULL,
    published_at TEXT NOT NULL,
    PRIMARY KEY(version_id, case_id)
);
"""

CANDIDATE_SELECT = """
SELECT c.*, r.collection_id,
       COALESCE((SELECT MAX(v.revision) FROM candidate_revisions v WHERE v.candidate_id = c.id), 0)
       AS revision
FROM generated_candidates c JOIN generation_runs r ON r.id = c.run_id
"""


class GenerationNotFound(Exception):
    pass


class CandidateNotFound(Exception):
    pass


class RevisionConflict(Exception):
    pass


class InvalidReview(Exception):
    def __init__(self, issues: list[ReviewIssue]) -> None:
        self.issues = issues


class DuplicateDecisionConflict(Exception):
    pass


class GenerationStore(DocumentStore):
    def __init__(self, data_dir: Path) -> None:
        super().__init__(data_dir)

    def _connect(self) -> sqlite3.Connection:
        connection = super()._connect()
        connection.executescript(SCHEMA)
        return connection

    def create_run(
        self,
        collection_id: str,
        config: dict[str, Any],
        target_count: int,
        target_multi_count: int,
        max_calls: int,
        max_concurrency: int,
    ) -> dict[str, Any]:
        self.get_collection(collection_id)
        run_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO generation_runs "
                "(id, collection_id, status, config_json, target_count, target_multi_count, "
                "max_calls, max_concurrency, created_at) VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    collection_id,
                    json.dumps(config, ensure_ascii=False),
                    target_count,
                    target_multi_count,
                    max_calls,
                    max_concurrency,
                    now,
                ),
            )
        return self.get(run_id)

    def get_collection(self, collection_id: str) -> dict[str, Any]:
        return super().get(collection_id)

    def get(self, run_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM generation_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise GenerationNotFound(run_id)
            errors = connection.execute(
                "SELECT error, COUNT(*) AS count FROM generation_attempts "
                "WHERE run_id = ? AND error IS NOT NULL GROUP BY error ORDER BY count DESC, error",
                (run_id,),
            ).fetchall()
        result = dict(row)
        result["config"] = json.loads(result.pop("config_json"))
        result["shortfall_reasons"] = json.loads(result.pop("shortfall_json"))
        result["attempt_errors"] = {item["error"]: item["count"] for item in errors}
        return result

    def list_runs(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            ids = connection.execute(
                "SELECT id FROM generation_runs ORDER BY created_at DESC, id DESC"
            ).fetchall()
        return [self.get(row["id"]) for row in ids]

    def claim(self, run_id: str) -> bool:
        with closing(self._connect()) as connection, connection:
            changed = connection.execute(
                "UPDATE generation_runs SET status = 'running', started_at = ? "
                "WHERE id = ? AND status = 'queued'",
                (datetime.now(UTC).isoformat(), run_id),
            ).rowcount
        return bool(changed)

    def record(
        self,
        run_id: str,
        slot: GenerationSlot,
        case: GeneratedCase | None,
        error: str | None,
    ) -> None:
        model_name = self.get(run_id)["config"]["model_name"] if case is not None else None
        candidate_id: str | None = None
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT attempted_count FROM generation_runs WHERE id = ? AND status = 'running'",
                (run_id,),
            ).fetchone()
            if row is None:
                return
            attempt_number = row["attempted_count"] + 1
            connection.execute(
                "INSERT INTO generation_attempts VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    attempt_number,
                    slot.index,
                    "success" if case else "failed",
                    error,
                    json.dumps(case.usage) if case and case.usage else None,
                ),
            )
            if case is not None:
                chunks = reference_chunks(case.support_positions, slot.sources, slot.multi_chunk)
                candidate_id = str(uuid4())
                created_at = datetime.now(UTC).isoformat()
                chunks_json = json.dumps(chunks, ensure_ascii=False)
                positions_json = json.dumps(case.support_positions)
                connection.execute(
                    "INSERT INTO generated_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        candidate_id,
                        run_id,
                        slot.index,
                        case.question,
                        case.reference_answer,
                        chunks_json,
                        positions_json,
                        int(slot.multi_chunk),
                        "pending_review",
                        PROMPT_VERSION,
                        model_name,
                        created_at,
                    ),
                )
                connection.execute(
                    "INSERT INTO candidate_revisions "
                    "VALUES (?, 0, ?, ?, ?, ?, 'pending_review', ?)",
                    (
                        candidate_id,
                        case.question,
                        case.reference_answer,
                        chunks_json,
                        positions_json,
                        created_at,
                    ),
                )
            connection.execute(
                "UPDATE generation_runs SET attempted_count = attempted_count + 1, "
                "actual_count = actual_count + ?, actual_multi_count = actual_multi_count + ? "
                "WHERE id = ?",
                (int(case is not None), int(case is not None and slot.multi_chunk), run_id),
            )
        if candidate_id is not None:
            self.check_duplicates(candidate_id)

    def finish(
        self, run_id: str, unavailable_multi: int = 0, fatal_error: str | None = None
    ) -> None:
        run = self.get(run_id)
        if run["status"] != "running":
            return
        reasons = []
        if unavailable_multi:
            reasons.append("insufficient_source_chunks")
        if run["actual_count"] < run["target_count"]:
            if run["attempted_count"] >= run["max_calls"]:
                reasons.append("call_limit_reached")
            if run["attempt_errors"]:
                reasons.append("model_or_validation_errors")
            if fatal_error:
                reasons.append(fatal_error)
            if not reasons:
                reasons.append("insufficient_candidates")
        status = (
            "completed"
            if run["actual_count"] == run["target_count"]
            else "partial"
            if run["actual_count"]
            else "failed"
        )
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE generation_runs SET status = ?, shortfall_json = ?, finished_at = ? "
                "WHERE id = ? AND status = 'running'",
                (status, json.dumps(reasons), datetime.now(UTC).isoformat(), run_id),
            )

    def candidates(self, run_id: str) -> list[dict[str, Any]]:
        self.get(run_id)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                CANDIDATE_SELECT + " WHERE c.run_id = ? ORDER BY c.slot_index",
                (run_id,),
            ).fetchall()
        return [self._candidate(row) for row in rows]

    @staticmethod
    def _candidate(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["reference_chunks"] = json.loads(item.pop("reference_chunks_json"))
        item["support_positions"] = json.loads(item.pop("support_positions_json"))
        item["multi_chunk"] = bool(item["multi_chunk"])
        return item

    def get_candidate(self, candidate_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                CANDIDATE_SELECT + " WHERE c.id = ?", (candidate_id,)
            ).fetchone()
        if row is None:
            raise CandidateNotFound(candidate_id)
        return self._candidate(row)

    def revisions(self, candidate_id: str) -> list[dict[str, Any]]:
        candidate = self.get_candidate(candidate_id)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM candidate_revisions WHERE candidate_id = ? ORDER BY revision",
                (candidate_id,),
            ).fetchall()
        if not rows:
            return [self._revision_snapshot(candidate, 0, candidate["created_at"])]
        return [self._decode_revision(row) for row in rows]

    @staticmethod
    def _revision_snapshot(
        candidate: dict[str, Any], revision: int, created_at: str
    ) -> dict[str, Any]:
        return {
            "revision": revision,
            "question": candidate["question"],
            "reference_answer": candidate["reference_answer"],
            "reference_chunks": candidate["reference_chunks"],
            "support_positions": candidate["support_positions"],
            "status": candidate["status"],
            "created_at": created_at,
        }

    @staticmethod
    def _decode_revision(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item.pop("candidate_id")
        item["reference_chunks"] = json.loads(item.pop("reference_chunks_json"))
        item["support_positions"] = json.loads(item.pop("support_positions_json"))
        return item

    def review(
        self,
        candidate_id: str,
        *,
        expected_revision: int,
        collection_id: str,
        question: str,
        reference_answer: str,
        support_positions: list[int],
        action: ReviewAction,
    ) -> dict[str, Any]:
        current = self.get_candidate(candidate_id)
        source = self.get_collection(current["collection_id"])
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                CANDIDATE_SELECT + " WHERE c.id = ?", (candidate_id,)
            ).fetchone()
            if row is None:
                raise CandidateNotFound(candidate_id)
            candidate = self._candidate(row)
            if expected_revision != candidate["revision"]:
                raise RevisionConflict(candidate_id)
            chunks, issues = validate_review(
                question=question,
                reference_answer=reference_answer,
                support_positions=support_positions,
                collection_id=collection_id,
                source_collection_id=candidate["collection_id"],
                collection_chunks=source["chunks"],
                action=action,
            )
            if issues:
                raise InvalidReview(issues)
            if candidate["revision"] == 0:
                existing = connection.execute(
                    "SELECT 1 FROM candidate_revisions WHERE candidate_id = ? AND revision = 0",
                    (candidate_id,),
                ).fetchone()
                if existing is None:
                    self._insert_revision(
                        connection,
                        candidate_id,
                        self._revision_snapshot(candidate, 0, candidate["created_at"]),
                    )
            revision = candidate["revision"] + 1
            now = datetime.now(UTC).isoformat()
            status = {"save": "pending_review", "approve": "approved", "reject": "rejected"}[action]
            snapshot = {
                "revision": revision,
                "question": question.strip(),
                "reference_answer": reference_answer.strip(),
                "reference_chunks": chunks,
                "support_positions": support_positions,
                "status": status,
                "created_at": now,
            }
            connection.execute(
                "UPDATE generated_candidates SET question = ?, reference_answer = ?, "
                "reference_chunks_json = ?, support_positions_json = ?, status = ? WHERE id = ?",
                (
                    snapshot["question"],
                    snapshot["reference_answer"],
                    json.dumps(chunks, ensure_ascii=False),
                    json.dumps(support_positions),
                    status,
                    candidate_id,
                ),
            )
            self._insert_revision(connection, candidate_id, snapshot)
        self.check_duplicates(candidate_id)
        return self.get_candidate(candidate_id)

    def check_duplicates(self, candidate_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                CANDIDATE_SELECT + " WHERE c.id = ?", (candidate_id,)
            ).fetchone()
            if row is None:
                raise CandidateNotFound(candidate_id)
            candidate = self._candidate(row)
            matches = self._duplicate_matches(connection, candidate)
            verdict = overall(matches)
            checked_at = datetime.now(UTC).isoformat()
            cursor = connection.execute(
                "INSERT INTO candidate_duplicate_checks "
                "(candidate_id, revision, verdict, matches_json, rule_version, checked_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    candidate_id,
                    candidate["revision"],
                    verdict,
                    json.dumps(matches, ensure_ascii=False),
                    CHECK_VERSION,
                    checked_at,
                ),
            )
            check_id = cursor.lastrowid
        return {
            "id": check_id,
            "candidate_id": candidate_id,
            "revision": candidate["revision"],
            "verdict": verdict,
            "matches": matches,
            "rule_version": CHECK_VERSION,
            "checked_at": checked_at,
            "decision": None,
            "reason": None,
            "decided_at": None,
        }

    def _duplicate_matches(
        self, connection: sqlite3.Connection, candidate: dict[str, Any]
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            CANDIDATE_SELECT + " WHERE r.collection_id = ? AND c.id != ? "
            "ORDER BY c.created_at, c.id",
            (candidate["collection_id"], candidate["id"]),
        ).fetchall()
        others = [
            {**self._candidate(other), "source_kind": "candidate", "source_id": other["id"]}
            for other in rows
        ]
        current_candidates = {other["id"]: other for other in others}
        published = connection.execute(
            "SELECT * FROM published_candidate_cases WHERE collection_id = ? "
            "ORDER BY published_at, version_id, case_id",
            (candidate["collection_id"],),
        ).fetchall()
        for item in published:
            snapshot = {
                "source_kind": "published_case",
                "source_id": f"{item['version_id']}:{item['case_id']}",
                "question": item["question"],
                "reference_answer": item["reference_answer"],
                "reference_chunks": json.loads(item["reference_chunks_json"]),
            }
            current = current_candidates.get(item["candidate_id"])
            if current is not None and all(
                current[field] == snapshot[field]
                for field in ("question", "reference_answer", "reference_chunks")
            ):
                continue
            others.append(snapshot)
        return [match for other in others if (match := compare(candidate, other))]

    def duplicate_check(self, candidate_id: str) -> dict[str, Any] | None:
        candidate = self.get_candidate(candidate_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT c.*, d.decision, d.reason, d.decided_at "
                "FROM candidate_duplicate_checks c "
                "LEFT JOIN candidate_duplicate_decisions d ON d.check_id = c.id "
                "WHERE c.candidate_id = ? AND c.revision = ? ORDER BY c.id DESC LIMIT 1",
                (candidate_id, candidate["revision"]),
            ).fetchone()
        if row is None:
            return None
        return self._decode_duplicate_check(row)

    def duplicate_history(self, candidate_id: str) -> list[dict[str, Any]]:
        self.get_candidate(candidate_id)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT c.*, d.decision, d.reason, d.decided_at "
                "FROM candidate_duplicate_checks c "
                "LEFT JOIN candidate_duplicate_decisions d ON d.check_id = c.id "
                "WHERE c.candidate_id = ? ORDER BY c.id",
                (candidate_id,),
            ).fetchall()
        return [self._decode_duplicate_check(row) for row in rows]

    @staticmethod
    def _decode_duplicate_check(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["matches"] = json.loads(result.pop("matches_json"))
        return result

    def decide_duplicate(
        self, candidate_id: str, check_id: int, expected_revision: int, reason: str
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                CANDIDATE_SELECT + " WHERE c.id = ?", (candidate_id,)
            ).fetchone()
            if row is None:
                raise CandidateNotFound(candidate_id)
            candidate = self._candidate(row)
            latest = connection.execute(
                "SELECT id, revision, verdict FROM candidate_duplicate_checks "
                "WHERE candidate_id = ? ORDER BY id DESC LIMIT 1",
                (candidate_id,),
            ).fetchone()
            if (
                candidate["revision"] != expected_revision
                or latest is None
                or latest["id"] != check_id
                or latest["revision"] != expected_revision
                or latest["verdict"] != "suspected"
                or candidate["status"] != "approved"
            ):
                raise DuplicateDecisionConflict(candidate_id)
            if not reason.strip():
                raise ValueError("放行理由不能为空")
            connection.execute(
                "INSERT INTO candidate_duplicate_decisions VALUES (?, 'allow', ?, ?)",
                (check_id, reason.strip(), datetime.now(UTC).isoformat()),
            )
        result = self.duplicate_check(candidate_id)
        assert result is not None
        return result

    def assert_publishable(
        self, connection: sqlite3.Connection, candidate_id: str
    ) -> dict[str, Any]:
        row = connection.execute(CANDIDATE_SELECT + " WHERE c.id = ?", (candidate_id,)).fetchone()
        if row is None:
            raise CandidateNotFound(candidate_id)
        candidate = self._candidate(row)
        latest = connection.execute(
            "SELECT c.*, d.decision FROM candidate_duplicate_checks c "
            "LEFT JOIN candidate_duplicate_decisions d ON d.check_id = c.id "
            "WHERE c.candidate_id = ? ORDER BY c.id DESC LIMIT 1",
            (candidate_id,),
        ).fetchone()
        if (
            candidate["status"] != "approved"
            or latest is None
            or latest["revision"] != candidate["revision"]
            or latest["rule_version"] != CHECK_VERSION
            or json.loads(latest["matches_json"]) != self._duplicate_matches(connection, candidate)
            or latest["verdict"] == "duplicate"
            or (latest["verdict"] == "suspected" and latest["decision"] != "allow")
        ):
            raise DuplicateDecisionConflict(candidate_id)
        return candidate

    def record_published_candidate(
        self, connection: sqlite3.Connection, candidate_id: str, version_id: str, case_id: str
    ) -> None:
        candidate = self.assert_publishable(connection, candidate_id)
        connection.execute(
            "INSERT INTO published_candidate_cases "
            "(version_id, case_id, candidate_id, collection_id, question, reference_answer, "
            "reference_chunks_json, published_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                version_id,
                case_id,
                candidate_id,
                candidate["collection_id"],
                candidate["question"],
                candidate["reference_answer"],
                json.dumps(candidate["reference_chunks"], ensure_ascii=False),
                datetime.now(UTC).isoformat(),
            ),
        )

    @staticmethod
    def _insert_revision(
        connection: sqlite3.Connection, candidate_id: str, snapshot: dict[str, Any]
    ) -> None:
        connection.execute(
            "INSERT INTO candidate_revisions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                candidate_id,
                snapshot["revision"],
                snapshot["question"],
                snapshot["reference_answer"],
                json.dumps(snapshot["reference_chunks"], ensure_ascii=False),
                json.dumps(snapshot["support_positions"]),
                snapshot["status"],
                snapshot["created_at"],
            ),
        )
