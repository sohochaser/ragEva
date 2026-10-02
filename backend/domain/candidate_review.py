"""Validate reviewer edits against an immutable source collection."""

from dataclasses import dataclass
from typing import Any, Literal

ReviewAction = Literal["save", "approve", "reject"]


@dataclass(frozen=True)
class ReviewIssue:
    field: str
    message: str


def validate_review(
    *,
    question: str,
    reference_answer: str,
    support_positions: list[int],
    collection_id: str,
    source_collection_id: str,
    collection_chunks: list[dict[str, Any]],
    action: ReviewAction,
) -> tuple[list[dict[str, str]], list[ReviewIssue]]:
    issues: list[ReviewIssue] = []
    if collection_id != source_collection_id:
        issues.append(ReviewIssue("collection_id", "只能选择候选所属集合的 chunk"))
    if len(support_positions) != len(set(support_positions)):
        issues.append(ReviewIssue("support_positions", "参考 chunk 不能重复"))
    by_position = {chunk["position"]: chunk for chunk in collection_chunks}
    if any(position not in by_position for position in support_positions):
        issues.append(ReviewIssue("support_positions", "参考 chunk 必须来自当前集合"))
    if action == "approve":
        if not question.strip():
            issues.append(ReviewIssue("question", "批准前须填写问题"))
        if not reference_answer.strip():
            issues.append(ReviewIssue("reference_answer", "批准前须填写标准答案"))
        if not support_positions:
            issues.append(ReviewIssue("support_positions", "批准前须选择至少一个参考 chunk"))
    if issues:
        return [], issues
    return [
        {"document_id": by_position[position]["document_id"], "text": by_position[position]["text"]}
        for position in support_positions
    ], []
