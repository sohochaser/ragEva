from math import isclose

from backend.domain.datasets import ReferenceChunk
from backend.domain.matching import CandidatePair
from backend.domain.predictions import PredictedChunk
from backend.domain.retrieval_scoring import (
    GAIN_RULE_VERSION,
    MATCH_RULE_VERSION,
    aggregate_retrieval,
    score_retrieval,
)


def gold(*texts: str) -> list[ReferenceChunk]:
    return [ReferenceChunk(text, "doc") for text in texts]


def predicted(*texts: str) -> list[PredictedChunk]:
    return [PredictedChunk(text, "doc") for text in texts]


def edge(reference: int, actual: int, similarity: float = 0.9) -> CandidatePair:
    return CandidatePair(reference, actual, similarity, True, "candidate")


def test_merged_chunk_counts_once_with_k_denominator() -> None:
    result = score_retrieval(
        gold("A", "B"), predicted("A and B"), [edge(0, 0), edge(1, 0)], "model", 0.8
    )
    ten = result.scores[10]
    assert ten.precision == 0.1
    assert ten.ap == 0.5
    assert len(ten.matches) == 1
    assert ten.matches[0].reference_index == 0
    assert ten.ndcg < 1
    assert result.match_rule_version == MATCH_RULE_VERSION
    assert result.gain_rule_version == GAIN_RULE_VERSION


def test_maximum_cardinality_requires_first_prediction_to_take_second_reference() -> None:
    candidates = [edge(0, 0), edge(1, 0), edge(0, 1)]
    result = score_retrieval(gold("A", "B"), predicted("AB", "A"), candidates, "model", 0.8)
    ten = result.scores[10]
    assert [(match.predicted_index, match.reference_index) for match in ten.matches] == [
        (0, 1),
        (1, 0),
    ]
    assert ten.precision == 0.2
    assert ten.ap == 1
    assert score_retrieval(gold("A", "B"), predicted("AB", "A"), candidates, "model", 0.8) == result


def test_reference_order_only_changes_ndcg_when_both_predicted_positions_hit() -> None:
    first = score_retrieval(
        gold("A", "B"), predicted("A", "B"), [edge(0, 0), edge(1, 1)], "model", 0.8
    )
    swapped = score_retrieval(
        gold("A", "B"), predicted("B", "A"), [edge(1, 0), edge(0, 1)], "model", 0.8
    )
    assert first.scores[10].precision == swapped.scores[10].precision
    assert first.scores[10].ap == swapped.scores[10].ap
    assert first.scores[10].ndcg == 1
    assert swapped.scores[10].ndcg < 1


def test_duplicate_prediction_keeps_rank_but_cannot_add_hit() -> None:
    result = score_retrieval(
        gold("A", "B"),
        predicted("A", " A  ", "B"),
        [edge(0, 0), edge(0, 1), edge(1, 2)],
        "model",
        0.8,
    )
    ten = result.scores[10]
    assert [(match.predicted_index, match.reference_index) for match in ten.matches] == [
        (0, 0),
        (2, 1),
    ]
    assert isclose(ten.ap, (1 + 2 / 3) / 2)
    assert any(
        item.predicted_index == 1 and item.reason == "duplicate_prediction"
        for item in ten.decisions
    )


def test_top_k_is_matched_independently_and_zero_predictions_score_zero() -> None:
    predictions = predicted(*[f"p{i}" for i in range(11)])
    result = score_retrieval(gold("A", "B"), predictions, [edge(0, 0), edge(1, 10)], "model", 0.8)
    assert len(result.scores[10].matches) == 1
    assert len(result.scores[20].matches) == 2
    assert result.scores[10].precision == 0.1
    assert result.scores[20].precision == 0.1
    assert result.scores[20].ap > result.scores[10].ap
    empty = score_retrieval(gold("A"), [], [], "model", 0.8)
    assert all(score.precision == score.ap == score.ndcg == 0 for score in empty.scores.values())


def test_cross_document_and_below_threshold_edges_never_match() -> None:
    reference = [ReferenceChunk("A", "doc-a")]
    actual = [PredictedChunk("A", "doc-b"), PredictedChunk("B", "doc-a")]
    pairs = [
        CandidatePair(0, 0, None, False, "document_mismatch"),
        CandidatePair(0, 1, 0.79, False, "below_threshold"),
    ]
    result = score_retrieval(reference, actual, pairs, "model", 0.8)
    assert result.scores[10].matches == ()
    assert [item.reason for item in result.scores[10].decisions] == [
        "document_mismatch",
        "below_threshold",
    ]


def test_run_level_map_excludes_inapplicable_cases() -> None:
    hit = score_retrieval(gold("A"), predicted("A"), [edge(0, 0)], "model", 0.8)
    miss = score_retrieval(gold("A"), predicted("B"), [], "model", 0.8)
    aggregated = aggregate_retrieval([hit, miss, None])
    assert aggregated.valid_count == 2
    assert aggregated.not_applicable_count == 1
    assert aggregated.map_at_k[10] == 0.5
    assert aggregated.precision_at_k[10] == 0.05
    assert aggregated.ndcg_at_k[10] == 0.5
