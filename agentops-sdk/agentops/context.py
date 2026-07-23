from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional


from dataclasses import dataclass, field
import time


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str

    start_time: float = field(default_factory=time.perf_counter)


_stack: ContextVar[list[Span]] = ContextVar("trace_stack", default=[])


class TraceContext:

    def start_trace(self, name: str) -> Span:
        trace_id = str(uuid.uuid4())

        span = Span(
            trace_id=trace_id,
            span_id=str(uuid.uuid4()),
            parent_span_id=None,
            name=name,
        )

        _stack.set([span])

        return span

    def start_span(self, name: str) -> Span:

        stack = list(_stack.get())

        if not stack:
            raise RuntimeError("No active trace.")

        parent = stack[-1]

        span = Span(
            trace_id=parent.trace_id,
            span_id=str(uuid.uuid4()),
            parent_span_id=parent.span_id,
            name=name,
        )

        stack.append(span)
        _stack.set(stack)

        return span

    def end_span(self):

        stack = list(_stack.get())

        if not stack:
            return None

        span = stack.pop()

        _stack.set(stack)

        return span

    def current(self) -> Optional[Span]:
        stack = _stack.get()

        if stack:
            return stack[-1]

        return None