"""Public trace link contract."""

from typing import Literal

from pydantic import BaseModel


class TraceReference(BaseModel):
    trace_id: str
    span_id: str
    expires_at: str
    status: Literal["available", "expired", "unconfigured"]
    url: str | None
