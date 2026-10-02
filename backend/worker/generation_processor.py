"""Bounded asynchronous generation from an immutable collection."""

from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from functools import partial
from pathlib import Path

import httpx
from opentelemetry import trace

from backend.adapters.document_store import CollectionNotFound
from backend.adapters.generation_model import GeneratedCase, GenerationModelError, generate_case
from backend.adapters.generation_store import GenerationStore
from backend.adapters.model_store import OnlineModelNotFound, OnlineModelStore
from backend.adapters.trace_store import TraceStore
from backend.adapters.usage_store import UsageStore
from backend.domain.generation import GenerationSlot, plan_slots, reference_chunks
from backend.domain.model_usage import model_call_usage
from backend.tracing import attributes, business_span, fail


def process_generation(
    run_id: str,
    data_dir: Path,
    client_factory: Callable[[], httpx.Client] = httpx.Client,
) -> None:
    store = GenerationStore(data_dir)
    usage_store = UsageStore(data_dir)
    traces = TraceStore(data_dir)
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

        def record_generation_call(
            messages: list[dict[str, str]],
            content: str | None,
            usage: dict[str, int] | None,
            slot_index: int,
        ) -> None:
            token_usage = model_call_usage(messages, content, usage)
            attributes(
                trace.get_current_span(),
                **{
                    "token.input": token_usage["input_tokens"],
                    "token.output": token_usage["output_tokens"],
                },
            )
            usage_store.record(
                "generation",
                run_id,
                "generation",
                str(slot_index),
                config["model_name"],
                token_usage,
            )

        def generate_slot(slot: GenerationSlot) -> GeneratedCase:
            with business_span("generation.attempt") as span:
                attributes(
                    span,
                    **{
                        "generation.id": run_id,
                        "model.id": config["model_name"],
                        "slot.index": slot.index,
                    },
                )
                traces.record("generation_slot", f"{run_id}:{slot.index}", span)
                try:
                    result = generate_case(
                        client,
                        config["base_url"],
                        config["model_name"],
                        token,
                        config["timeout_seconds"],
                        slot,
                        config["language"],
                        config["question_type"],
                        config["instructions"],
                        partial(record_generation_call, slot_index=slot.index),
                    )
                    attributes(span, **{"status": "success"})
                    return result
                except Exception as exc:
                    fail(span, type(exc).__name__)
                    raise

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
                futures = [pool.submit(copy_context().run, generate_slot, slot) for slot in batch]
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
                    with business_span("generation.persist") as span:
                        attributes(
                            span,
                            **{
                                "generation.id": run_id,
                                "slot.index": slot.index,
                                "status": "failed" if error else "success",
                            },
                        )
                        if error:
                            fail(span, error)
                        store.record(run_id, slot, case, error)
    except (CollectionNotFound, OnlineModelNotFound):
        store.finish(run_id, unavailable_multi, "missing_generation_dependency")
        return
    except Exception:
        store.finish(run_id, unavailable_multi, "generation_worker_error")
        return
    store.finish(run_id, unavailable_multi)
