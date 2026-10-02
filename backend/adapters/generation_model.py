"""OpenAI-compatible model call for one candidate question."""

import json
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from backend.domain.generation import GenerationSlot


class GenerationModelError(Exception):
    pass


CallObserver = Callable[[list[dict[str, str]], str | None, dict[str, int] | None], None]


@dataclass(frozen=True)
class GeneratedCase:
    question: str
    reference_answer: str
    support_positions: tuple[int, ...]
    usage: dict[str, int] | None


SYSTEM_PROMPT = (
    "Generate one grounded single-turn RAG evaluation case. Return only a JSON object "
    "with question, reference_answer, and support_positions (an array of source positions). "
    "Use only the provided source chunks. Every listed chunk must be necessary to answer. "
    "Order support_positions from most to least relevant to the question. "
    "Do not invent facts or cite positions outside the provided sources."
)


def generate_case(
    client: httpx.Client,
    base_url: str,
    model_name: str,
    token: str | None,
    timeout_seconds: float,
    slot: GenerationSlot,
    language: str,
    question_type: str,
    instructions: str,
    on_call: CallObserver | None = None,
) -> GeneratedCase:
    source_payload = [
        {"position": item["position"], "document_id": item["document_id"], "text": item["text"]}
        for item in slot.sources
    ]
    user_prompt = json.dumps(
        {
            "language": language,
            "question_type": question_type,
            "additional_requirements": instructions,
            "required_support_chunks": 2 if slot.multi_chunk else 1,
            "sources": source_payload,
        },
        ensure_ascii=False,
    )
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    content: str | None = None
    parsed_usage: dict[str, int] | None = None
    try:
        try:
            response = client.post(
                base_url.rstrip("/") + "/chat/completions",
                headers=headers,
                json={
                    "model": model_name,
                    "messages": messages,
                    "temperature": 0.3,
                    "response_format": {"type": "json_object"},
                },
                timeout=timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise GenerationModelError("model_timeout") from exc
        except httpx.TransportError as exc:
            raise GenerationModelError("model_connection_error") from exc
        if not 200 <= response.status_code < 300:
            raise GenerationModelError(f"model_http_{response.status_code}")
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("invalid_body")
            content = payload["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("invalid_content")
            usage = payload.get("usage")
            if usage is not None:
                if not isinstance(usage, dict) or any(
                    not isinstance(usage.get(key), int)
                    or isinstance(usage.get(key), bool)
                    or usage[key] < 0
                    for key in ("prompt_tokens", "completion_tokens")
                ):
                    raise GenerationModelError("invalid_usage")
                parsed_usage = {
                    "input_tokens": usage["prompt_tokens"],
                    "output_tokens": usage["completion_tokens"],
                }
            result = json.loads(content)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise GenerationModelError("invalid_model_response") from exc
        if not isinstance(result, dict) or set(result) != {
            "question",
            "reference_answer",
            "support_positions",
        }:
            raise GenerationModelError("invalid_candidate_shape")
        question = result["question"]
        answer = result["reference_answer"]
        positions = result["support_positions"]
        if (
            not isinstance(question, str)
            or not question.strip()
            or len(question) > 2000
            or not isinstance(answer, str)
            or not answer.strip()
            or len(answer) > 10000
            or not isinstance(positions, list)
            or not positions
            or any(not isinstance(item, int) or isinstance(item, bool) for item in positions)
            or len(set(positions)) != len(positions)
        ):
            raise GenerationModelError("invalid_candidate_fields")
        return GeneratedCase(question.strip(), answer.strip(), tuple(positions), parsed_usage)
    finally:
        if on_call is not None:
            on_call(messages, content if isinstance(content, str) else None, parsed_usage)
