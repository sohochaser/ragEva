import json

import httpx

from backend.adapters.http_target import call_json_target
from backend.adapters.sse_target import call_sse_target


def event(kind: str, payload: dict[str, object]) -> str:
    return f"event: {kind}\ndata: {json.dumps(payload)}\n\n"


def stream(*events: str) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"Content-Type": "text/event-stream; charset=utf-8"},
        text="".join(events),
    )


def test_sse_normalizes_contexts_before_answer_and_tracks_three_times() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return stream(
            ": heartbeat\n\n",
            event(
                "contexts",
                {
                    "items": [
                        {"text": "second", "document_id": "d2"},
                        {"text": "first", "document_id": "d1"},
                    ]
                },
            ),
            event("answer.delta", {"text": ""}),
            event("answer.delta", {"text": "Hello"}),
            event("answer.delta", {"text": " world"}),
            event("completed", {"usage": {"input_tokens": 8, "output_tokens": 2}}),
        )

    ticks = iter([0.0, 0.1, 0.2, 0.3])
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = call_sse_target(
            client,
            "https://example.test/rag",
            "private",
            "q1",
            "Q",
            "both",
            clock=lambda: next(ticks),
        )
    assert result.error is None
    assert result.prediction is not None
    assert result.prediction.answer == "Hello world"
    assert [chunk.document_id for chunk in result.prediction.contexts or ()] == ["d2", "d1"]
    assert result.usage == {"input_tokens": 8, "output_tokens": 2}
    attempt = result.attempts[0]
    assert attempt.ttft_ms == 100
    assert attempt.ttlt_ms == 200
    assert attempt.stream_completed_ms == 300
    assert json.loads(seen[0].content) == {"case_id": "q1", "question": "Q", "stream": True}
    assert seen[0].headers["authorization"] == "Bearer private"

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "answer": "Hello world",
                    "contexts": [
                        {"text": "second", "document_id": "d2"},
                        {"text": "first", "document_id": "d1"},
                    ],
                },
            )
        )
    ) as client:
        plain = call_json_target(client, "https://example.test/rag", None, "q1", "Q", "both")
    assert plain.prediction is not None
    assert result.prediction.answer == plain.prediction.answer
    assert result.prediction.contexts == plain.prediction.contexts


def test_sse_contexts_after_delta_and_stream_error_retry() -> None:
    calls = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return stream(
                event("answer.delta", {"text": "discard"}),
                event(
                    "error",
                    {
                        "code": "temporary",
                        "message": "retry",
                    },
                ),
            )
        return stream(
            event("answer.delta", {"text": "A"}),
            event("contexts", {"items": [{"text": "A", "document_id": "d"}]}),
            event("completed", {}),
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = call_sse_target(client, "https://example.test/rag", None, "q1", "Q", "both")
    assert calls == 2
    assert result.prediction is not None
    assert result.prediction.answer == "A"
    assert [item.status for item in result.attempts] == ["stream_error", "success"]
    assert result.attempts[0].error == "stream_error:temporary"
    assert result.prediction.latency_ms is not None
    assert result.prediction.latency_ms >= sum(item.elapsed_ms for item in result.attempts)


def test_sse_missing_completion_and_missing_required_events() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: stream(
                event("answer.delta", {"text": "A"}),
            )
        )
    ) as client:
        interrupted = call_sse_target(
            client,
            "https://example.test/rag",
            None,
            "q1",
            "Q",
            "answer",
            retries=0,
        )
    assert interrupted.error == "missing_completed"
    assert interrupted.attempts[0].stream_completed_ms is None
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: stream(
                event("contexts", {"items": [{"text": "A", "document_id": "d"}]}),
                event("completed", {}),
            )
        )
    ) as client:
        no_answer = call_sse_target(client, "https://example.test/rag", None, "q1", "Q", "both")
    assert no_answer.error == "missing_answer"
    assert no_answer.attempts[0].ttft_ms is None
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: stream(
                event("answer.delta", {"text": "A"}),
                event("completed", {}),
            )
        )
    ) as client:
        no_contexts = call_sse_target(client, "https://example.test/rag", None, "q1", "Q", "both")
    assert no_contexts.error == "missing_contexts"


def test_sse_rejects_bad_payload_and_content_type() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: stream(
                "event: answer.delta\ndata: {bad-json}\n\n",
            )
        )
    ) as client:
        invalid = call_sse_target(client, "https://example.test/rag", None, "q1", "Q", "answer")
    assert invalid.error == "invalid_event_json"
    assert len(invalid.attempts) == 1
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="wrong"))
    ) as client:
        invalid_type = call_sse_target(
            client, "https://example.test/rag", None, "q1", "Q", "answer"
        )
    assert invalid_type.error == "invalid_content_type"


def test_sse_retries_unexpected_end_but_not_auth_failure() -> None:
    calls = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return stream(event("answer.delta", {"text": "discard"}))
        return stream(event("answer.delta", {"text": "A"}), event("completed", {}))

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = call_sse_target(client, "https://example.test/rag", None, "q1", "Q", "answer")
    assert calls == 2
    assert result.prediction is not None
    assert result.prediction.answer == "A"
    assert [attempt.error for attempt in result.attempts] == ["missing_completed", None]

    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(401))) as client:
        denied = call_sse_target(
            client, "https://example.test/rag", None, "q1", "Q", "answer", retries=2
        )
    assert denied.error == "http_401"
    assert len(denied.attempts) == 1
