"""Public source-aware token usage contract."""

from typing import Literal

from pydantic import BaseModel

TokenSource = Literal["actual", "estimated", "not_applicable", "unknown"]


class TokenBucket(BaseModel):
    calls: int
    tokens: int


class UsageCall(BaseModel):
    id: str
    owner_type: str
    owner_id: str
    operation: str
    case_id: str | None
    model_id: str
    input_tokens: int | None
    input_source: TokenSource
    output_tokens: int | None
    output_source: TokenSource
    tokenizer: str | None
    created_at: str


class UsageSummary(BaseModel):
    call_count: int
    totals: dict[str, dict[TokenSource, TokenBucket]]
    calls: list[UsageCall]
