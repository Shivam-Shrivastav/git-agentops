from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    event_id: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None

    timestamp: datetime

    event_type: str
    name: str
    status: str

    duration_ms: float | None = None

    payload: dict[str, Any] = Field(default_factory=dict)