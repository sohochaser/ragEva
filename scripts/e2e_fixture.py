"""Deterministic model and RAG target endpoints for browser acceptance tests."""

import json
from collections.abc import Iterator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def completion(request: Request) -> dict[str, object]:
    body = await request.json()
    prompt = json.loads(body["messages"][1]["content"])
    if "sources" in prompt:
        question = (
            "Give the year recorded for this event."
            if prompt["additional_requirements"] == "alternate"
            else "When did Acme launch?"
        )
        result = {
            "question": question,
            "reference_answer": "2018",
            "support_positions": [item["position"] for item in prompt["sources"]],
        }
    else:
        result = {"score": 1.0, "reason": "The answer matches the supplied evidence."}
    return {
        "choices": [{"message": {"content": json.dumps(result)}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 8},
    }


@app.post("/rag/json")
async def json_target(request: Request) -> dict[str, object]:
    await request.json()
    return {
        "answer": "2018",
        "contexts": [{"document_id": "doc-a", "text": "Acme launched in 2018."}],
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }


@app.post("/rag/sse")
async def sse_target(request: Request) -> StreamingResponse:
    await request.json()

    def events() -> Iterator[str]:
        yield (
            "event: contexts\n"
            'data: {"items":[{"document_id":"doc-a","text":"Acme launched in 2018."}]}\n\n'
        )
        yield 'event: answer.delta\ndata: {"text":"2018"}\n\n'
        yield 'event: completed\ndata: {"usage":{"input_tokens":10,"output_tokens":2}}\n\n'

    return StreamingResponse(events(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=18002)
