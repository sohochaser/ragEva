"""Run state rules shared by API, persistence, and worker."""

from typing import Literal

RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
CaseStatus = Literal["pending", "success", "failed", "not_applicable", "cancelled"]
MetricKey = Literal["precision", "map", "ndcg"]
TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}
