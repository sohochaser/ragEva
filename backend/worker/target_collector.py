"""Collect generic JSON target predictions into an immutable batch."""

from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path

import httpx

from backend.adapters.http_target import TargetCall, call_json_target
from backend.adapters.sse_target import call_sse_target
from backend.adapters.target_store import TargetStore


def collect_target_job(
    job_id: str,
    data_dir: Path,
    client_factory: Callable[[], httpx.Client] = httpx.Client,
) -> None:
    store = TargetStore(data_dir)
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
            pending = iter(cases)
            futures: dict[Future[TargetCall], str] = {}

            def enqueue_one() -> bool:
                if store.cancellation_requested(job_id):
                    return False
                try:
                    case_id, question = next(pending)
                except StopIteration:
                    return False
                future = pool.submit(
                    caller,
                    client,
                    target["url"],
                    token,
                    case_id,
                    question,
                    job["evaluation_type"],
                    target["timeout_seconds"],
                    target["retries"],
                )
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
                    store.record_case(job_id, case_id, result)
                if store.cancellation_requested(job_id):
                    break
                for _ in done:
                    if not enqueue_one():
                        break
    except Exception as exc:
        store.fail_pending(job_id, f"collection_error:{type(exc).__name__}")
    finally:
        store.finish_job(job_id)
