"""Collect generic JSON target predictions into an immutable batch."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from backend.adapters.http_target import TargetCall, call_json_target
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
        with client_factory() as client, ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(
                    call_json_target,
                    client,
                    target["url"],
                    token,
                    case_id,
                    question,
                    job["evaluation_type"],
                    target["timeout_seconds"],
                    target["retries"],
                ): case_id
                for case_id, question in cases
            }
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as exc:
                    result = TargetCall(None, (), f"call_error:{type(exc).__name__}", None)
                store.record_case(job_id, futures[future], result)
    except Exception as exc:
        store.fail_pending(job_id, f"collection_error:{type(exc).__name__}")
    finally:
        store.finish_job(job_id)
