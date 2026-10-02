from pathlib import Path

import pytest

from backend.adapters.usage_store import UsageStore
from backend.domain import model_usage


def test_estimator_failure_stays_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> None:
        raise RuntimeError("tokenizer unavailable")

    monkeypatch.setattr(model_usage, "_tokenizer", fail)
    result = model_usage.model_call_usage(
        [{"role": "user", "content": "visible text"}], "visible response", None
    )
    assert result["input_tokens"] is None
    assert result["output_tokens"] is None
    assert result["input_source"] == result["output_source"] == "unknown"


def test_usage_store_separates_sources(tmp_path: Path) -> None:
    store = UsageStore(tmp_path)
    actual = model_usage.model_call_usage([], None, {"input_tokens": 8, "output_tokens": 3})
    estimated = model_usage.model_call_usage([{"role": "user", "content": "Hi"}], "ok", None)
    embedding = model_usage.embedding_usage(["Hi"])
    store.record("run", "run-1", "answer_scoring", "q1", "judge", actual)
    store.record("run", "run-1", "answer_scoring", "q2", "judge", estimated)
    store.record("run", "run-1", "embedding", "q2", "encoder", embedding)
    result = store.for_owner("run", "run-1")
    assert result["call_count"] == 3
    assert result["totals"]["input"]["actual"] == {"calls": 1, "tokens": 8}
    assert result["totals"]["input"]["estimated"]["calls"] == 2
    assert result["totals"]["output"]["not_applicable"] == {"calls": 1, "tokens": 0}
    assert store.for_owner("run", "other")["call_count"] == 0
