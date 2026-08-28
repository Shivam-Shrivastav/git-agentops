from __future__ import annotations

from typing import Any


class PlannerSpan:
    """
    Mutable reasoning metadata for a planner step.

    The start event carries the model. The caller attaches the
    planner's reasoning after the LLM responds (or after a fallback
    decision on failure): the candidates it was offered, the action it
    chose, the ones it rejected, its stated thought and confidence, and
    the iteration number. This is what makes a planner decision a
    queryable object rather than opaque JSON.
    """

    def __init__(self, model: str | None) -> None:
        self.model = model

        self.thought: str | None = None
        self.candidates: list[str] | None = None
        self.chosen_action: str | None = None
        self.rejected_actions: list[str] | None = None
        self.confidence: float | None = None
        self.iteration: int | None = None
        self.error: str | None = None

        # free-form extension fields (budget_exceeded, token_usage,
        # final_response, ...) merged onto the end payload so a
        # planner decision can carry arbitrary queryable telemetry
        # the same way an LLM span carries eval_* fields via set_params.
        self.extra: dict[str, Any] = {}

        # explicit status override ("error" when set_error is called)
        self._status: str | None = None

    def set_params(self, **kwargs: Any) -> None:
        """
        Attach free-form fields to this planner decision.

        Unlike LLMSpan.set_params there are no reserved model-parameter
        keys, so every keyword is stored verbatim and emitted on the
        .end event. Use this to make cost/budget and final-response
        signals queryable alongside the decision itself.
        """
        for key, value in kwargs.items():
            self.extra[key] = value

    def set_plan(
        self,
        *,
        thought: str | None = None,
        candidates: list[str] | None = None,
        chosen_action: str | None = None,
        rejected_actions: list[str] | None = None,
        confidence: float | None = None,
        iteration: int | None = None,
    ) -> None:
        if thought is not None:
            self.thought = thought
        if candidates is not None:
            self.candidates = candidates
        if chosen_action is not None:
            self.chosen_action = chosen_action
        if rejected_actions is not None:
            self.rejected_actions = rejected_actions
        if confidence is not None:
            self.confidence = confidence
        if iteration is not None:
            self.iteration = iteration

    def set_error(self, error_message: str) -> None:
        self.error = error_message
        self._status = "error"

    def set_status(self, status: str) -> None:
        if status not in {"success", "error"}:
            raise ValueError("status must be 'success' or 'error'")
        self._status = status

    def to_end_payload(self) -> dict[str, Any]:
        """Fields merged onto the start payload on the .end event."""
        payload: dict[str, Any] = {}

        if self.thought is not None:
            payload["thought"] = self.thought

        if self.candidates is not None:
            payload["candidates"] = self.candidates

        if self.chosen_action is not None:
            payload["chosen_action"] = self.chosen_action

        if self.rejected_actions is not None:
            payload["rejected_actions"] = self.rejected_actions

        if self.confidence is not None:
            payload["confidence"] = self.confidence

        if self.iteration is not None:
            payload["iteration"] = self.iteration

        if self.error is not None:
            payload["error"] = self.error

        if self.extra:
            payload.update(self.extra)

        return payload