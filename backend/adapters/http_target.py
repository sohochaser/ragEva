"""Generic JSON RAG target caller with bounded retries and normalization."""

from dataclasses import dataclass
from time import monotonic
from typing import Any

import httpx

from backend.domain.datasets import SourceRow
from backend.domain.predictions import EvaluationType, Prediction, validate_predictions


@dataclass(frozen=True)
class TargetAttempt:
    number: int
    status: str
    http_status: int | None
    elapsed_ms: float
    error: str | None
    ttft_ms: float | None = None
    ttlt_ms: float | None = None
    stream_completed_ms: float | None = None


@dataclass(frozen=True)
class TargetCall:
    prediction: Prediction | None
    attempts: tuple[TargetAttempt, ...]
    error: str | None
    usage: dict[str, int] | None


def _usage(value: Any) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("invalid_usage")
    result: dict[str, int] = {}
    for key in ("input_tokens", "output_tokens"):
        item = value.get(key)
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise ValueError("invalid_usage")
        result[key] = item
    return result


def call_json_target(
    client: httpx.Client,
    url: str,
    token: str | None,
    case_id: str,
    question: str,
    evaluation_type: EvaluationType,
    timeout_seconds: float = 30,
    retries: int = 1,
) -> TargetCall:
    attempts: list[TargetAttempt] = []
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    for number in range(1, retries + 2):
        start = monotonic()
        try:
            response = client.post(
                url,
                json={"case_id": case_id, "question": question},
                headers=headers,
                timeout=timeout_seconds,
            )
            elapsed_ms = (monotonic() - start) * 1000
            if response.status_code < 200 or response.status_code >= 300:
                code = response.status_code
                error = f"http_{code}"
                attempts.append(TargetAttempt(number, "http_error", code, elapsed_ms, error))
                if code in {429, 500, 502, 503, 504} and number <= retries:
                    continue
                return TargetCall(None, tuple(attempts), error, None)
            try:
                payload = response.json()
            except ValueError:
                error = "invalid_json"
                attempts.append(TargetAttempt(number, "invalid_response", 200, elapsed_ms, error))
                return TargetCall(None, tuple(attempts), error, None)
            if not isinstance(payload, dict):
                error = "invalid_json_object"
                attempts.append(TargetAttempt(number, "invalid_response", 200, elapsed_ms, error))
                return TargetCall(None, tuple(attempts), error, None)
            try:
                usage = _usage(payload.get("usage"))
            except ValueError as exc:
                error = str(exc)
                attempts.append(TargetAttempt(number, "invalid_response", 200, elapsed_ms, error))
                return TargetCall(None, tuple(attempts), error, None)
            values = {
                "case_id": case_id,
                "answer": payload.get("answer"),
                "contexts": payload.get("contexts"),
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
                attempts.append(TargetAttempt(number, "invalid_response", 200, elapsed_ms, error))
                return TargetCall(None, tuple(attempts), error, usage)
            attempts.append(TargetAttempt(number, "success", 200, elapsed_ms, None))
            return TargetCall(predictions[0], tuple(attempts), None, usage)
        except httpx.TimeoutException:
            elapsed_ms = (monotonic() - start) * 1000
            attempts.append(TargetAttempt(number, "timeout", None, elapsed_ms, "timeout"))
            if number > retries:
                return TargetCall(None, tuple(attempts), "timeout", None)
        except httpx.TransportError:
            elapsed_ms = (monotonic() - start) * 1000
            attempts.append(
                TargetAttempt(number, "connection_error", None, elapsed_ms, "connection_error")
            )
            if number > retries:
                return TargetCall(None, tuple(attempts), "connection_error", None)
    raise AssertionError("retry loop did not finish")
