"""Deterministic source allocation and validation for generated cases."""

import math
from dataclasses import dataclass
from typing import Any

PROMPT_VERSION = "candidate-generation-v1"


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
    slots: list[GenerationSlot] = []
    unavailable_multi = 0
    for index in range(target_count):
        multi = index < target_multi_count
        if multi and len(ordered) < 2:
            unavailable_multi += 1
            continue
        width = 2 if multi else 1
        start = index % len(ordered)
        sources = tuple(ordered[(start + offset) % len(ordered)] for offset in range(width))
        slots.append(GenerationSlot(index, multi, sources))
    return slots, unavailable_multi


def reference_chunks(
    positions: tuple[int, ...], sources: tuple[dict[str, Any], ...], multi_chunk: bool
) -> list[dict[str, str]]:
    source_by_position = {source["position"]: source for source in sources}
    if not positions or len(set(positions)) != len(positions):
        raise ValueError("invalid_support_positions")
    if multi_chunk and len(positions) < 2:
        raise ValueError("insufficient_multi_chunk_support")
    if any(position not in source_by_position for position in positions):
        raise ValueError("unknown_support_position")
    return [
        {
            "document_id": source_by_position[position]["document_id"],
            "text": source_by_position[position]["text"],
        }
        for position in positions
    ]
