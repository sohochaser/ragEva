"""Deterministic Top-K one-to-one chunk scoring."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import log2
from typing import Any

from backend.domain.matching import CandidatePair, Chunk

MATCH_RULE_VERSION = "one-to-one-v1"
GAIN_RULE_VERSION = "ordered-linear-v1"
DEFAULT_K = (10, 20)


@dataclass(frozen=True)
class SelectedMatch:
    predicted_index: int
    reference_index: int
    similarity: float


@dataclass(frozen=True)
class EdgeDecision:
    reference_index: int
    predicted_index: int
    similarity: float | None
    candidate: bool
    selected: bool
    reason: str


@dataclass(frozen=True)
class KScore:
    k: int
    precision: float
    ap: float
    ndcg: float
    matches: tuple[SelectedMatch, ...]
    decisions: tuple[EdgeDecision, ...]


@dataclass(frozen=True)
class RetrievalCaseScore:
    model_id: str
    threshold: float
    match_rule_version: str
    gain_rule_version: str
    scores: dict[int, KScore]


@dataclass(frozen=True)
class RetrievalAggregate:
    valid_count: int
    not_applicable_count: int
    precision_at_k: dict[int, float | None]
    map_at_k: dict[int, float | None]
    ndcg_at_k: dict[int, float | None]


def score_from_dict(payload: Mapping[str, Any]) -> RetrievalCaseScore:
    scores = {
        int(k): KScore(
            k=int(k),
            precision=value["precision"],
            ap=value["ap"],
            ndcg=value["ndcg"],
            matches=tuple(SelectedMatch(**match) for match in value["matches"]),
            decisions=tuple(EdgeDecision(**decision) for decision in value["decisions"]),
        )
        for k, value in payload["scores"].items()
    }
    return RetrievalCaseScore(
        model_id=payload["model_id"],
        threshold=payload["threshold"],
        match_rule_version=payload["match_rule_version"],
        gain_rule_version=payload["gain_rule_version"],
        scores=scores,
    )


def _maximum_size(
    positions: Sequence[int], available: set[int], adjacency: Mapping[int, set[int]]
) -> int:
    by_reference: dict[int, int] = {}

    def augment(position: int, visited: set[int]) -> bool:
        for reference in sorted(adjacency.get(position, set()) & available):
            if reference in visited:
                continue
            visited.add(reference)
            other = by_reference.get(reference)
            if other is None or augment(other, visited):
                by_reference[reference] = position
                return True
        return False

    for position in positions:
        augment(position, set())
    return len(by_reference)


def _deduplicated_positions(predicted: Sequence[Chunk]) -> set[int]:
    seen: set[tuple[str, str]] = set()
    duplicates: set[int] = set()
    for index, chunk in enumerate(predicted):
        key = (chunk.document_id, re.sub(r"\s+", " ", chunk.text.strip()))
        if key in seen:
            duplicates.add(index)
        seen.add(key)
    return duplicates


def _score_at_k(
    reference: Sequence[Chunk],
    predicted: Sequence[Chunk],
    pairs: Sequence[CandidatePair],
    duplicates: set[int],
    k: int,
) -> KScore:
    top = min(k, len(predicted))
    adjacency: dict[int, set[int]] = {}
    similarity: dict[tuple[int, int], float] = {}
    for pair in pairs:
        if pair.predicted_index >= top or pair.predicted_index in duplicates or not pair.candidate:
            continue
        adjacency.setdefault(pair.predicted_index, set()).add(pair.reference_index)
        if pair.similarity is not None:
            similarity[(pair.predicted_index, pair.reference_index)] = pair.similarity
    positions = [position for position in range(top) if position not in duplicates]
    available = set(range(len(reference)))
    target_size = _maximum_size(positions, available, adjacency)
    selected: dict[int, int] = {}

    # Fix earlier predictions and their earliest feasible references while preserving cardinality.
    for position in positions:
        remaining = [item for item in positions if item > position]
        for candidate in sorted(adjacency.get(position, set()) & available):
            if (
                len(selected) + 1 + _maximum_size(remaining, available - {candidate}, adjacency)
                == target_size
            ):
                selected[position] = candidate
                available.remove(candidate)
                break
        else:
            if len(selected) + _maximum_size(remaining, available, adjacency) != target_size:
                raise ValueError("无法确定最大一对一匹配")

    matches = tuple(
        SelectedMatch(position, reference_index, similarity[(position, reference_index)])
        for position, reference_index in sorted(selected.items())
    )
    decisions = tuple(
        EdgeDecision(
            pair.reference_index,
            pair.predicted_index,
            pair.similarity,
            pair.candidate and pair.predicted_index not in duplicates,
            selected.get(pair.predicted_index) == pair.reference_index,
            "duplicate_prediction"
            if pair.predicted_index in duplicates and pair.candidate
            else "matched"
            if selected.get(pair.predicted_index) == pair.reference_index
            else "not_selected"
            if pair.candidate
            else pair.reason,
        )
        for pair in pairs
        if pair.predicted_index < top
    )
    precision = len(matches) / k
    ap = sum(hit / (match.predicted_index + 1) for hit, match in enumerate(matches, start=1)) / min(
        len(reference), k
    )
    dcg = sum(
        (len(reference) - match.reference_index) / log2(match.predicted_index + 2)
        for match in matches
    )
    idcg = sum(
        (len(reference) - index) / log2(index + 2) for index in range(min(len(reference), k))
    )
    ndcg = dcg / idcg if idcg else 0.0
    return KScore(k, precision, ap, ndcg, matches, decisions)


def score_retrieval(
    reference: Sequence[Chunk],
    predicted: Sequence[Chunk],
    pairs: Sequence[CandidatePair],
    model_id: str,
    threshold: float,
    ks: tuple[int, ...] = DEFAULT_K,
) -> RetrievalCaseScore:
    if not reference:
        raise ValueError("检索评分需要参考 chunk")
    if not ks or any(k <= 0 for k in ks):
        raise ValueError("K 必须为正整数")
    if any(
        pair.reference_index < 0
        or pair.reference_index >= len(reference)
        or pair.predicted_index < 0
        or pair.predicted_index >= len(predicted)
        for pair in pairs
    ):
        raise ValueError("候选位置超出 chunk 列表")
    duplicates = _deduplicated_positions(predicted)
    return RetrievalCaseScore(
        model_id,
        threshold,
        MATCH_RULE_VERSION,
        GAIN_RULE_VERSION,
        {k: _score_at_k(reference, predicted, pairs, duplicates, k) for k in ks},
    )


def aggregate_retrieval(
    results: Sequence[RetrievalCaseScore | None], ks: tuple[int, ...] = DEFAULT_K
) -> RetrievalAggregate:
    valid = [result for result in results if result is not None]
    count = len(valid)

    def average(field: str) -> dict[int, float | None]:
        return {
            k: sum(getattr(result.scores[k], field) for result in valid) / count if count else None
            for k in ks
        }

    return RetrievalAggregate(
        valid_count=count,
        not_applicable_count=len(results) - count,
        precision_at_k=average("precision"),
        map_at_k=average("ap"),
        ndcg_at_k=average("ndcg"),
    )
