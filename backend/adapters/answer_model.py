"""OpenAI-compatible Chat Completions adapter for answer scoring."""

import json
import math
from dataclasses import dataclass
from typing import Any

import httpx

from backend.domain.answer_prompts import (
    PROMPT_VERSION,
    AnswerMetric,
    AnswerSample,
    render_messages,
)


class AnswerModelError(Exception):
    pass


@dataclass(frozen=True)
class AnswerModelResult:
    metric: AnswerMetric
    score: float
    reason: str
    raw_response: str
    usage: dict[str, int] | None
    model_name: str
    prompt_version: str


def _usage(payload: Any) -> dict[str, int] | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise AnswerModelError("invalid_usage")
    result = {}
    for source, target in (
        ("prompt_tokens", "input_tokens"),
        ("completion_tokens", "output_tokens"),
    ):
        value = payload.get(source)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AnswerModelError("invalid_usage")
        result[target] = value
    return result


def evaluate_answer_metric(
    client: httpx.Client,
    base_url: str,
    model_name: str,
    token: str | None,
    timeout_seconds: float,
    metric: AnswerMetric,
    criteria: str,
    sample: AnswerSample,
) -> AnswerModelResult:
    messages = render_messages(metric, criteria, sample)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = client.post(
            base_url.rstrip("/") + "/chat/completions",
            json={
                "model": model_name,
                "messages": messages,
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            headers=headers,
            timeout=timeout_seconds,
        )
    except httpx.TimeoutException as exc:
        raise AnswerModelError("model_timeout") from exc
    except httpx.TransportError as exc:
        raise AnswerModelError("model_connection_error") from exc
    if not 200 <= response.status_code < 300:
        raise AnswerModelError(f"model_http_{response.status_code}")
    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("missing_content")
        result = json.loads(content)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AnswerModelError("invalid_model_response") from exc
    if not isinstance(result, dict) or set(result) != {"score", "reason"}:
        raise AnswerModelError("invalid_score_shape")
    score = result["score"]
    reason = result["reason"]
    if isinstance(score, bool) or not isinstance(score, int | float) or not math.isfinite(score):
        raise AnswerModelError("invalid_score")
    if not 0 <= score <= 1:
        raise AnswerModelError("invalid_score")
    if not isinstance(reason, str) or not reason.strip():
        raise AnswerModelError("invalid_reason")
    usage = _usage(body.get("usage"))
    return AnswerModelResult(
        metric, float(score), reason.strip(), content, usage, model_name, PROMPT_VERSION
    )
