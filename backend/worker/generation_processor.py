"""Bounded asynchronous generation from an immutable collection."""

from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from backend.adapters.document_store import CollectionNotFound
from backend.adapters.generation_model import GeneratedCase, GenerationModelError, generate_case
from backend.adapters.generation_store import GenerationStore
from backend.adapters.model_store import OnlineModelNotFound, OnlineModelStore
from backend.domain.generation import plan_slots, reference_chunks


def process_generation(
    run_id: str,
    data_dir: Path,
    client_factory: Callable[[], httpx.Client] = httpx.Client,
) -> None:
    store = GenerationStore(data_dir)
    if not store.claim(run_id):
        return
    unavailable_multi = 0
    try:
        run = store.get(run_id)
        config = run["config"]
        collection = store.get_collection(run["collection_id"])
        model = OnlineModelStore(data_dir)
        token = model.token(config["model_id"])
        slots, unavailable_multi = plan_slots(
            collection["chunks"], run["target_count"], run["target_multi_count"]
        )
        pending = deque(slots)
        with (
            client_factory() as client,
            ThreadPoolExecutor(max_workers=run["max_concurrency"]) as pool,
        ):
            while pending and store.get(run_id)["attempted_count"] < run["max_calls"]:
                remaining = run["max_calls"] - store.get(run_id)["attempted_count"]
                batch = [
                    pending.popleft()
                    for _ in range(min(len(pending), remaining, run["max_concurrency"]))
                ]
                futures = [
                    pool.submit(
                        generate_case,
                        client,
                        config["base_url"],
                        config["model_name"],
                        token,
                        config["timeout_seconds"],
                        slot,
                        config["language"],
                        config["question_type"],
                        config["instructions"],
                    )
                    for slot in batch
                ]
                for slot, future in zip(batch, futures, strict=True):
                    case: GeneratedCase | None = None
                    error = None
                    try:
                        case = future.result()
                        reference_chunks(case.support_positions, slot.sources, slot.multi_chunk)
                    except (GenerationModelError, ValueError) as exc:
                        error = str(exc)
                    except Exception:
                        error = "unexpected_model_error"
                    if error:
                        case = None
                        pending.append(slot)
                    store.record(run_id, slot, case, error)
    except (CollectionNotFound, OnlineModelNotFound):
        store.finish(run_id, unavailable_multi, "missing_generation_dependency")
        return
    except Exception:
        store.finish(run_id, unavailable_multi, "generation_worker_error")
        return
    store.finish(run_id, unavailable_multi)
