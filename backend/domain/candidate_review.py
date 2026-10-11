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
    current_positions: list[int] | None = None,
    current_chunks: list[dict[str, str]] | None = None,
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
    if (
        all(position in by_position for position in support_positions)
        and len({by_position[position]["document_id"] for position in support_positions}) > 1
    ):
        issues.append(ReviewIssue("support_positions", "一道题只能引用同一文档的来源"))
    if action == "approve":
        if not question.strip():
            issues.append(ReviewIssue("question", "批准前须填写问题"))
        if not reference_answer.strip():
            issues.append(ReviewIssue("reference_answer", "批准前须填写标准答案"))
        if not support_positions:
            issues.append(ReviewIssue("support_positions", "批准前须选择至少一个参考 chunk"))
    if issues:
        return [], issues
    previous = dict(zip(current_positions or [], current_chunks or [], strict=True))
    return [
        {
            "document_id": by_position[position]["document_id"],
            "text": previous[position]["text"]
            if position in previous
            and previous[position]["document_id"] == by_position[position]["document_id"]
            and previous[position]["text"] in by_position[position]["text"]
            else by_position[position]["text"],
        }
        for position in support_positions
    ], []
