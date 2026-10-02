import httpx

from backend.adapters.http_target import call_json_target


def client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_json_target_preserves_order_usage_and_bearer() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "answer": "A",
                "contexts": [
                    {"text": "second", "document_id": "d2"},
                    {"text": "first", "document_id": "d1"},
                ],
                "usage": {"input_tokens": 12, "output_tokens": 4},
            },
        )

    with client(httpx.MockTransport(respond)) as http:
        result = call_json_target(http, "https://example.test/rag", "secret", "q1", "Q", "both")
    assert result.error is None
    assert result.prediction is not None
    assert [item.document_id for item in result.prediction.contexts or ()] == ["d2", "d1"]
    assert result.usage == {"input_tokens": 12, "output_tokens": 4}
    assert seen[0].headers["authorization"] == "Bearer secret"
    assert seen[0].content == b'{"case_id":"q1","question":"Q"}'


def test_retries_transient_error_and_keeps_attempts() -> None:
    count = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"contexts": [{"text": "A", "document_id": "d"}]})

    with client(httpx.MockTransport(respond)) as http:
        result = call_json_target(http, "https://example.test/rag", None, "q1", "Q", "retrieval")
    assert result.prediction is not None
    assert [item.status for item in result.attempts] == ["http_error", "success"]


def test_auth_and_bad_contract_fail_without_retry() -> None:
    with client(httpx.MockTransport(lambda _: httpx.Response(401))) as http:
        denied = call_json_target(
            http, "https://example.test/rag", None, "q1", "Q", "answer", retries=2
        )
    assert denied.error == "http_401"
    assert len(denied.attempts) == 1
    with client(httpx.MockTransport(lambda _: httpx.Response(200, json={"answer": "A"}))) as http:
        invalid = call_json_target(http, "https://example.test/rag", None, "q1", "Q", "both")
    assert invalid.error == "missing_contexts"


def test_timeout_and_invalid_json_are_distinct_failures() -> None:
    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout")

    with client(httpx.MockTransport(timeout)) as http:
        timed_out = call_json_target(
            http, "https://example.test/rag", None, "q1", "Q", "retrieval", retries=1
        )
    assert timed_out.error == "timeout"
    assert [attempt.status for attempt in timed_out.attempts] == ["timeout", "timeout"]
    with client(httpx.MockTransport(lambda _: httpx.Response(200, text="not json"))) as http:
        invalid = call_json_target(http, "https://example.test/rag", None, "q1", "Q", "retrieval")
    assert invalid.error == "invalid_json"
    assert len(invalid.attempts) == 1
