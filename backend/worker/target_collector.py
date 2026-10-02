"""Collect generic JSON target predictions into an immutable batch."""

from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextvars import copy_context
from pathlib import Path
from time import time_ns

import httpx
from opentelemetry import trace

from backend.adapters.http_target import TargetCall, call_json_target
from backend.adapters.sse_target import call_sse_target
from backend.adapters.target_store import TargetStore
from backend.adapters.trace_store import TraceStore
from backend.tracing import attributes, business_span, fail, tracer


def collect_target_job(
    job_id: str,
    data_dir: Path,
    client_factory: Callable[[], httpx.Client] = httpx.Client,
) -> None:
    store = TargetStore(data_dir)
    traces = TraceStore(data_dir)
    if not store.claim_job(job_id):
        return
    try:
        job = store.get_job(job_id)
        target = store.get_target(job["target_id"])
        token = store.token(job["target_id"])
        cases = store.pending_cases(job_id)
        caller = call_sse_target if target["protocol"] == "sse" else call_json_target
        with (
            client_factory() as client,
            ThreadPoolExecutor(max_workers=target["max_concurrency"]) as pool,
        ):

            def call_case(case_id: str, question: str) -> TargetCall:
                with business_span("target.case") as span:
                    attributes(
                        span,
                        **{"job.id": job_id, "case.id": case_id, "protocol": target["protocol"]},
                    )
                    traces.record("target_case", f"{job_id}:{case_id}", span)
                    try:
                        result = caller(
                            client,
                            target["url"],
                            token,
                            case_id,
                            question,
                            job["evaluation_type"],
                            target["timeout_seconds"],
                            target["retries"],
                        )
                    except Exception:
                        fail(span, "call_error")
                        raise
                    cursor = time_ns() - int(sum(item.elapsed_ms for item in result.attempts) * 1e6)
                    for attempt in result.attempts:
                        attempt_span = tracer().start_span("target.attempt", start_time=cursor)
                        attributes(
                            attempt_span,
                            **{
                                "job.id": job_id,
                                "case.id": case_id,
                                "attempt.number": attempt.number,
                                "status": attempt.status,
                                "elapsed.ms": attempt.elapsed_ms,
                            },
                        )
                        if attempt.error:
                            fail(attempt_span, attempt.error)
                        cursor += int(attempt.elapsed_ms * 1e6)
                        attempt_span.end(end_time=cursor)
                    if result.usage:
                        attributes(
                            span,
                            **{
                                "token.input": result.usage["input_tokens"],
                                "token.output": result.usage["output_tokens"],
                            },
                        )
                    if result.error:
                        fail(span, result.error)
                    else:
                        attributes(span, **{"status": "success"})
                    return result

            pending = iter(cases)
            futures: dict[Future[TargetCall], str] = {}

            def enqueue_one() -> bool:
                if store.cancellation_requested(job_id):
                    return False
                try:
                    case_id, question = next(pending)
                except StopIteration:
                    return False
                future = pool.submit(copy_context().run, call_case, case_id, question)
                futures[future] = case_id
                return True

            for _ in range(target["max_concurrency"]):
                if not enqueue_one():
                    break
            while futures:
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    case_id = futures.pop(future)
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = TargetCall(None, (), f"call_error:{type(exc).__name__}", None)
                    with business_span("target.persist") as span:
                        attributes(span, **{"job.id": job_id, "case.id": case_id})
                        store.record_case(job_id, case_id, result)
                if store.cancellation_requested(job_id):
                    break
                for _ in done:
                    if not enqueue_one():
                        break
    except Exception as exc:
        fail(trace.get_current_span(), "collection_error")
        store.fail_pending(job_id, f"collection_error:{type(exc).__name__}")
    finally:
        with business_span("target.batch.persist") as span:
            batch = store.finish_job(job_id)
            if batch["batch_id"]:
                attributes(
                    span,
                    **{"job.id": job_id, "batch.id": batch["batch_id"], "status": batch["status"]},
                )
                traces.record("batch", batch["batch_id"], span)
