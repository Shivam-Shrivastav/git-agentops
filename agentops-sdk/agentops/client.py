from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any

from .context import TraceContext, Span
from .events import Event, EventType
from .emitter import BaseEmitter, ConsoleEmitter
from typing import Generator
from .emitter import BaseEmitter, ConsoleEmitter, MultiEmitter
from contextlib import contextmanager


class AgentOps:

    def __init__(
        self,
        emitter: BaseEmitter | None = None,
        emitters: list[BaseEmitter] | None = None,
    ):
        self.context = TraceContext()

        if emitter is not None and emitters is not None:
            raise ValueError(
                "Provide either 'emitter' or 'emitters', not both."
            )

        if emitters is not None:
            self.emitter = MultiEmitter(emitters)
        elif emitter is not None:
            self.emitter = emitter
        else:
            self.emitter = ConsoleEmitter()

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
        trace_span = TraceSpan()

        

        self._emit(
            EventType.AGENT_START,
            span,
            payload=payload,
        )

        try:
            yield trace_span

        except Exception as exc:
            trace_span.set_error(
                error_type=type(exc).__name__,
                error_message=str(exc),
                failure_stage="agent",
            )

            raise

        finally:
            duration = round(
                (time.perf_counter() - span.start_time) * 1000,
                3,
            )

            self._emit(
                EventType.AGENT_END,
                span,
                status=trace_span.status,
                duration_ms=duration,
                payload=trace_span.error_payload(),
            )

            self.context.end_span()

    @contextmanager
    def _operation(
        self,
        *,
        start_event: EventType,
        end_event: EventType,
        name: str,
        payload: dict | None = None,
    ) -> Generator[None, None, None]:

        span = self.context.start_span(name)

        self._emit(
            start_event,
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

            duration = round(
                (time.perf_counter() - span.start_time) * 1000,
                3,
            )

            self._emit(
                end_event,
                span,
                payload=payload,
                duration_ms=duration,
                status=status,
            )

            self.context.end_span()

    @contextmanager
    def span(
        self,
        name: str,
        payload: dict[str, Any] | None = None,
    ):
        """Generic span for grouping operations under a parent node."""

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
            duration = round(
                (time.perf_counter() - span.start_time) * 1000,
                3,
            )

            self._emit(
                EventType.SPAN_END,
                span,
                status=status,
                duration_ms=duration,
                payload=payload,
            )

            self.context.end_span()


    @contextmanager
    def planner(
        self,
        *,
        model: str | None = None,
    ):
        from .planner import PlannerSpan

        span = self.context.start_span("planner")

        start_payload: dict[str, Any] = {}
        if model:
            start_payload["model"] = model

        self._emit(
            EventType.PLANNER_START,
            span,
            payload=start_payload,
        )

        planner_span = PlannerSpan(model=model)
        status = "success"

        try:
            yield planner_span

        except Exception:
            status = "error"
            raise

        finally:
            duration = round(
                (time.perf_counter() - span.start_time) * 1000,
                3,
            )

            if planner_span._status is not None:
                status = planner_span._status

            self._emit(
                EventType.PLANNER_END,
                span,
                payload=planner_span.to_end_payload(),
                status=status,
                duration_ms=duration,
            )

            self.context.end_span()

    @contextmanager
    def tool(
        self,
        *,
        name: str,
        **metadata,
    ):
        from .tool import ToolSpan

        span = self.context.start_span(name)

        start_payload = {
            "tool": name,
            **metadata,
        }

        self._emit(
            EventType.TOOL_START,
            span,
            payload=start_payload,
        )

        tool_span = ToolSpan(tool_name=name, args=metadata)
        status = "success"

        try:
            yield tool_span

        except Exception as exc:
            status = "error"
            tool_span.set_error(error_message=str(exc))
            raise

        finally:
            duration = round(
                (time.perf_counter() - span.start_time) * 1000,
                3,
            )

            if tool_span._status is not None:
                status = tool_span._status

            self._emit(
                EventType.TOOL_END,
                span,
                payload=tool_span.to_end_payload(),
                status=status,
                duration_ms=duration,
            )

            self.context.end_span()


    @contextmanager
    def llm(
        self,
        name: str,
        *,
        provider: str,
        model: str,
    ):
        from .llm import LLMSpan

        span = self.context.start_span(name)

        llm_span = LLMSpan(
            provider=provider,
            model=model,
        )

        self.emitter.emit(
            Event(
                trace_id=span.trace_id,
                span_id=span.span_id,
                parent_span_id=span.parent_span_id,
                event_type=EventType.LLM_START,
                name=name,
                payload=llm_span.to_payload(),
            )
        )

        start_time = time.perf_counter()

        status = "success"

        try:
            yield llm_span

        except Exception:
            status = "error"
            raise

        finally:
            duration_ms = (
                time.perf_counter() - start_time
            ) * 1000

            self.emitter.emit(
                Event(
                    trace_id=span.trace_id,
                    span_id=span.span_id,
                    parent_span_id=span.parent_span_id,
                    event_type=EventType.LLM_END,
                    name=name,
                    status=status,
                    duration_ms=round(duration_ms, 3),
                    payload=llm_span.to_payload(),
                )
            )

            self.context.end_span()



class TraceSpan:
    def __init__(self) -> None:
        self.status = "success"
        self.error_type: str | None = None
        self.error_message: str | None = None
        self.failure_stage: str | None = None

    def set_status(self, status: str) -> None:
        if status not in {"success", "error"}:
            raise ValueError(
                "status must be 'success' or 'error'"
            )

        self.status = status

    def set_error(
        self,
        *,
        error_type: str,
        error_message: str,
        failure_stage: str,
    ) -> None:
        self.status = "error"
        self.error_type = error_type
        self.error_message = error_message
        self.failure_stage = failure_stage

    def error_payload(self) -> dict[str, str]:
        payload = {}

        if self.error_type:
            payload["error_type"] = self.error_type

        if self.error_message:
            payload["error_message"] = self.error_message

        if self.failure_stage:
            payload["failure_stage"] = self.failure_stage

        return payload