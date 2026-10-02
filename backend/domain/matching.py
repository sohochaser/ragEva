"""Candidate edges for document-constrained chunk matching."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np


class Chunk(Protocol):
    @property
    def text(self) -> str: ...

    @property
    def document_id(self) -> str: ...


@dataclass(frozen=True)
class CandidatePair:
    reference_index: int
    predicted_index: int
    similarity: float | None
    candidate: bool
    reason: str


def relevant_texts(reference: Sequence[Chunk], predicted: Sequence[Chunk]) -> list[str]:
    predicted_docs = {item.document_id for item in predicted}
    reference_docs = {item.document_id for item in reference}
    return list(
        dict.fromkeys(
            [item.text for item in reference if item.document_id in predicted_docs]
            + [item.text for item in predicted if item.document_id in reference_docs]
        )
    )


def candidate_pairs(
    reference: Sequence[Chunk],
    predicted: Sequence[Chunk],
    vectors: Mapping[str, np.ndarray],
    threshold: float,
) -> list[CandidatePair]:
    pairs: list[CandidatePair] = []
    for reference_index, gold in enumerate(reference):
        for predicted_index, actual in enumerate(predicted):
            if gold.document_id != actual.document_id:
                pairs.append(
                    CandidatePair(
                        reference_index, predicted_index, None, False, "document_mismatch"
                    )
                )
                continue
            first, second = vectors[gold.text], vectors[actual.text]
            if first.size != second.size:
                raise ValueError("同一向量模型返回了不同维度")
            similarity = float(
                np.dot(first, second) / (np.linalg.norm(first) * np.linalg.norm(second))
            )
            accepted = similarity >= threshold - 1e-7
            pairs.append(
                CandidatePair(
                    reference_index,
                    predicted_index,
                    round(similarity, 6),
                    accepted,
                    "candidate" if accepted else "below_threshold",
                )
            )
    return pairs
