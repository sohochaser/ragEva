"""Generic SSE RAG target caller with explicit completion semantics."""

from collections.abc import Callable
from time import monotonic
from typing import Any

import httpx
from httpx_sse import SSEError, connect_sse

from backend.adapters.http_target import TargetAttempt, TargetCall, _usage
from backend.domain.datasets import SourceRow
from backend.domain.predictions import EvaluationType, validate_predictions


class StreamFailure(Exception):
    def __init__(self, code: str, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


def call_sse_target(
    client: httpx.Client,
    url: str,
    token: str | None,
    case_id: str,
    question: str,
    evaluation_type: EvaluationType,
    timeout_seconds: float = 30,
    retries: int = 1,
    clock: Callable[[], float] = monotonic,
) -> TargetCall:
    attempts: list[TargetAttempt] = []
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    for number in range(1, retries + 2):
        start = clock()
        ttft: float | None = None
        ttlt: float | None = None
        completed_ms: float | None = None
        status_code: int | None = None
        try:
            with connect_sse(
                client,
                "POST",
                url,
                json={"case_id": case_id, "question": question, "stream": True},
                headers=headers,
                timeout=timeout_seconds,
            ) as source:
                status_code = source.response.status_code
                if not 200 <= status_code < 300:
                    elapsed = (clock() - start) * 1000
                    error = f"http_{status_code}"
                    attempts.append(
                        TargetAttempt(number, "http_error", status_code, elapsed, error)
                    )
                    if status_code in {429, 500, 502, 503, 504} and number <= retries:
                        continue
                    return TargetCall(None, tuple(attempts), error, None)
                answer_parts: list[str] = []
                contexts: Any = None
                usage: dict[str, int] | None = None
                completed = False
                for event in source.iter_sse():
                    if event.event in {"message", "heartbeat", "ping"}:
                        continue
                    try:
                        payload = event.json()
                    except ValueError as exc:
                        raise StreamFailure("invalid_event_json", False) from exc
                    if not isinstance(payload, dict):
                        raise StreamFailure("invalid_event_payload", False)
                    if event.event == "answer.delta":
                        text = payload.get("text")
                        if not isinstance(text, str):
                            raise StreamFailure("invalid_answer_delta", False)
                        if text:
                            answer_parts.append(text)
                            elapsed = (clock() - start) * 1000
                            if ttft is None:
                                ttft = elapsed
                            ttlt = elapsed
                    elif event.event == "contexts":
                        if contexts is not None:
                            raise StreamFailure("duplicate_contexts", False)
                        contexts = payload.get("items")
                    elif event.event == "completed":
                        try:
                            usage = _usage(payload.get("usage"))
                        except ValueError as exc:
                            raise StreamFailure("invalid_usage", False) from exc
                        completed_ms = (clock() - start) * 1000
                        completed = True
                        break
                    elif event.event == "error":
                        code = payload.get("code")
                        if not isinstance(code, str) or not code or len(code) > 80:
                            raise StreamFailure("invalid_error_event", False)
                        raise StreamFailure(f"stream_error:{code}", True)
                    else:
                        raise StreamFailure("unknown_event", False)
                if not completed:
                    raise StreamFailure("missing_completed", True)
                elapsed_ms = completed_ms if completed_ms is not None else (clock() - start) * 1000
                values = {
                    "case_id": case_id,
                    "answer": "".join(answer_parts) if answer_parts else None,
                    "contexts": contexts,
                    "latency_ms": sum(item.elapsed_ms for item in attempts) + elapsed_ms,
                }
                predictions, issues = validate_predictions(
                    [SourceRow(1, values)],
                    {field: field for field in ("case_id", "answer", "contexts", "latency_ms")},
                    evaluation_type,
                    {case_id},
                )
                if issues:
                    error = issues[0].code
                    attempts.append(
                        TargetAttempt(
                            number,
                            "invalid_response",
                            status_code,
                            elapsed_ms,
                            error,
                            ttft,
                            ttlt,
                            completed_ms,
                        )
                    )
                    return TargetCall(None, tuple(attempts), error, usage)
                attempts.append(
                    TargetAttempt(
                        number,
                        "success",
                        status_code,
                        elapsed_ms,
                        None,
                        ttft,
                        ttlt,
                        completed_ms,
                    )
                )
                return TargetCall(predictions[0], tuple(attempts), None, usage)
        except StreamFailure as exc:
            elapsed = (clock() - start) * 1000
            attempts.append(
                TargetAttempt(
                    number,
                    "stream_error",
                    status_code,
                    elapsed,
                    exc.code,
                    ttft,
                    ttlt,
                    completed_ms,
                )
            )
            if not exc.retryable or number > retries:
                return TargetCall(None, tuple(attempts), exc.code, None)
        except SSEError:
            elapsed = (clock() - start) * 1000
            attempts.append(
                TargetAttempt(
                    number,
                    "invalid_response",
                    status_code,
                    elapsed,
                    "invalid_content_type",
                    ttft,
                    ttlt,
                    completed_ms,
                )
            )
            return TargetCall(None, tuple(attempts), "invalid_content_type", None)
        except httpx.TimeoutException:
            elapsed = (clock() - start) * 1000
            attempts.append(
                TargetAttempt(
                    number,
                    "timeout",
                    status_code,
                    elapsed,
                    "timeout",
                    ttft,
                    ttlt,
                    completed_ms,
                )
            )
            if number > retries:
                return TargetCall(None, tuple(attempts), "timeout", None)
        except httpx.TransportError:
            elapsed = (clock() - start) * 1000
            attempts.append(
                TargetAttempt(
                    number,
                    "connection_error",
                    status_code,
                    elapsed,
                    "connection_error",
                    ttft,
                    ttlt,
                    completed_ms,
                )
            )
            if number > retries:
                return TargetCall(None, tuple(attempts), "connection_error", None)
    raise AssertionError("retry loop did not finish")
