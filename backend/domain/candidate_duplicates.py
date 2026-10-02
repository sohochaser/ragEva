"""Deterministic duplicate evidence for candidates from one source collection."""

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

CHECK_VERSION = "candidate-duplicate-v1"
STOP_WORDS = frozenset(
    "a an are as at be by did do does for from how in is of on the to was were what when "
    "where which who why with year date happened happen".split()
)


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"\w+", value, flags=re.UNICODE))


def terms(value: str) -> set[str]:
    words = normalize(value).split()
    result = set()
    for word in words:
        if word in STOP_WORDS:
            continue
        if word.endswith("ed") and len(word) > 5:
            word = word[:-2]
        elif word.endswith("s") and len(word) > 4:
            word = word[:-1]
        result.add(word)
    return result


def compare(current: dict[str, Any], other: dict[str, Any]) -> dict[str, Any] | None:
    question = normalize(current["question"])
    other_question = normalize(other["question"])
    answer = normalize(current["reference_answer"])
    other_answer = normalize(other["reference_answer"])
    if not question or not other_question or not answer or not other_answer:
        return None

    same_answer = answer == other_answer
    current_sources = {
        (chunk["document_id"], normalize(chunk["text"])) for chunk in current["reference_chunks"]
    }
    other_sources = {
        (chunk["document_id"], normalize(chunk["text"])) for chunk in other["reference_chunks"]
    }
    shared_sources = len(current_sources & other_sources)
    left, right = terms(question), terms(other_question)
    term_similarity = len(left & right) / len(left | right) if left | right else 0.0
    text_similarity = SequenceMatcher(None, question, other_question).ratio()

    if same_answer and question == other_question:
        verdict = "duplicate"
        reason = "same_question_and_answer"
    elif same_answer and shared_sources and term_similarity >= 0.5 and text_similarity >= 0.55:
        verdict = "duplicate"
        reason = "same_answer_source_and_question_meaning"
    elif (same_answer and shared_sources) or (shared_sources and text_similarity >= 0.7):
        verdict = "suspected"
        reason = "shared_answer_or_source"
    else:
        return None

    return {
        "source_kind": other["source_kind"],
        "source_id": other["source_id"],
        "question": other["question"],
        "reference_answer": other["reference_answer"],
        "verdict": verdict,
        "reason": reason,
        "shared_source_count": shared_sources,
        "question_similarity": round(text_similarity, 3),
        "term_similarity": round(term_similarity, 3),
    }


def overall(matches: list[dict[str, Any]]) -> str:
    if any(match["verdict"] == "duplicate" for match in matches):
        return "duplicate"
    if matches:
        return "suspected"
    return "unique"
