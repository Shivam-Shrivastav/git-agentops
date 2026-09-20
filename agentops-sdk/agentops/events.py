from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field
from uuid import uuid4


class EventType(str, Enum):
    AGENT_START = "agent.start"
    AGENT_END = "agent.end"

    PLANNER_START = "planner.start"
    PLANNER_END = "planner.end"

    TOOL_START = "tool.start"
    TOOL_END = "tool.end"

    LLM_START = "llm.start"
    LLM_END = "llm.end"

    SPAN_START = "span.start"
    SPAN_END = "span.end"

    ERROR = "error"


class Event(BaseModel):
    event_id: str = Field(
        default_factory=lambda: str(uuid4())
    )

    trace_id: str
    span_id: str
    parent_span_id: str | None = None

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    event_type: EventType
    name: str

    status: str = "success"
    duration_ms: float | None = None

    payload: dict[str, Any] = Field(
        default_factory=dict
    )