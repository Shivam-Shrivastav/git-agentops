from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any

from .context import TraceContext, Span
from .events import Event, EventType
from .emitter import BaseEmitter, ConsoleEmitter


class AgentOps:

    def __init__(self, emitter: BaseEmitter | None = None):
        self.context = TraceContext()
        self.emitter = emitter or ConsoleEmitter()

    def _emit(
        self,
        event_type: EventType,
        span: Span,
        *,
        payload: dict[str, Any] | None = None,
        status: str = "success",
        duration_ms: float | None = None,
    ):

        self.emitter.emit(
            Event(
                trace_id=span.trace_id,
                span_id=span.span_id,
                parent_span_id=span.parent_span_id,
                event_type=event_type,
                name=span.name,
                status=status,
                duration_ms=duration_ms,
                payload=payload or {},
            )
        )

    @contextmanager
    def trace(
        self,
        name: str,
        payload: dict[str, Any] | None = None,
    ):

        span = self.context.start_trace(name)

        self._emit(
            EventType.AGENT_START,
            span,
            payload=payload,
        )

        try:
            yield

            status = "success"

        except Exception:

            status = "error"
            raise

        finally:

            duration = (
                time.perf_counter()
                - span.start_time
            ) * 1000

            self._emit(
                EventType.AGENT_END,
                span,
                status=status,
                duration_ms=duration,
            )

            self.context.end_span()

    @contextmanager
    def span(
        self,
        name: str,
        payload: dict[str, Any] | None = None,
    ):

        span = self.context.start_span(name)

        self._emit(
            EventType.SPAN_START,
            span,
            payload=payload,
        )

        try:
            yield

            status = "success"

        except Exception:

            status = "error"
            raise

        finally:

            duration = (
                time.perf_counter()
                - span.start_time
            ) * 1000

            self._emit(
                EventType.SPAN_END,
                span,
                status=status,
                duration_ms=duration,
            )

            self.context.end_span()