"""Deterministic source allocation and validation for generated cases."""

import math
from dataclasses import dataclass
from typing import Any

PROMPT_VERSION = "candidate-generation-v2"


@dataclass(frozen=True)
class GenerationSlot:
    index: int
    multi_chunk: bool
    sources: tuple[dict[str, Any], ...]


def multi_chunk_target(target_count: int, ratio: float) -> int:
    return min(target_count, math.ceil(target_count * ratio - 1e-9))


def plan_slots(
    chunks: list[dict[str, Any]], target_count: int, target_multi_count: int
) -> tuple[list[GenerationSlot], int]:
    by_document: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        by_document.setdefault(chunk["document_id"], []).append(chunk)
    ordered = [
        document_chunks[index]
        for index in range(max(map(len, by_document.values()), default=0))
        for document_chunks in by_document.values()
        if index < len(document_chunks)
    ]
    if not ordered:
        return [], target_multi_count
    multi_documents = [chunks for chunks in by_document.values() if len(chunks) >= 2]
    multi_sources = [
        (document_chunks[index], document_chunks[(index + 1) % len(document_chunks)])
        for index in range(max(map(len, multi_documents), default=0))
        for document_chunks in multi_documents
        if index < len(document_chunks)
    ]
    slots: list[GenerationSlot] = []
    unavailable_multi = 0
    for index in range(target_count):
        multi = index < target_multi_count
        if multi:
            if not multi_sources:
                unavailable_multi += 1
                continue
            sources: tuple[dict[str, Any], ...] = multi_sources[index % len(multi_sources)]
        else:
            sources = (ordered[index % len(ordered)],)
        slots.append(GenerationSlot(index, multi, sources))
    return slots, unavailable_multi


def reference_chunks(
    positions: tuple[int, ...],
    sources: tuple[dict[str, Any], ...],
    multi_chunk: bool,
    passages: tuple[str, ...] | None = None,
) -> list[dict[str, str]]:
    source_by_position = {source["position"]: source for source in sources}
    if not positions or len(set(positions)) != len(positions):
        raise ValueError("invalid_support_positions")
    if multi_chunk and len(positions) < 2:
        raise ValueError("insufficient_multi_chunk_support")
    if any(position not in source_by_position for position in positions):
        raise ValueError("unknown_support_position")
    if len({source_by_position[position]["document_id"] for position in positions}) != 1:
        raise ValueError("cross_document_support")
    if passages is not None and len(passages) != len(positions):
        raise ValueError("invalid_support_passages")
    if passages is not None and any(
        not passage.strip() or passage not in source_by_position[position]["text"]
        for position, passage in zip(positions, passages, strict=True)
    ):
        raise ValueError("unsupported_passage")
    return [
        {
            "document_id": source_by_position[position]["document_id"],
            "text": passages[index]
            if passages is not None
            else source_by_position[position]["text"],
        }
        for index, position in enumerate(positions)
    ]
