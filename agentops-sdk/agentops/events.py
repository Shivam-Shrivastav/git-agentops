from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class EventType(str, Enum):
    AGENT_START = "agent.start"
    AGENT_END = "agent.end"

    SPAN_START = "span.start"
    SPAN_END = "span.end"

    TOOL_START = "tool.start"
    TOOL_END = "tool.end"

    LLM_START = "llm.start"
    LLM_END = "llm.end"

    ERROR = "error"


class Event(BaseModel):
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    event_type: EventType

    name: str

    status: str = "success"

    duration_ms: Optional[float] = None

    payload: Dict[str, Any] = Field(default_factory=dict)