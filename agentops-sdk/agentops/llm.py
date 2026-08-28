from __future__ import annotations

from typing import Any


class LLMSpan:
    """
    Mutable metadata associated with an LLM operation.

    The caller attaches prompts, model parameters, usage and the
    completion after the provider returns a response. The end event
    carries the final payload (a superset of the start payload), and
    the worker merges start + end so nothing is lost.
    """

    def __init__(
        self,
        provider: str,
        model: str,
    ) -> None:
        # identity
        self.provider = provider
        self.model = model
        self.actual_model: str | None = None
        self.cost_usd: float | None = None

        # prompts
        self.system_prompt: str | None = None
        self.user_prompt: str | None = None
        self.prompt_template: str | None = None
        self.prompt_version: str | None = None

        # model parameters
        self.temperature: float | None = None
        self.top_p: float | None = None
        self.top_k: int | None = None
        self.max_tokens: int | None = None
        self.stop: list[str] | None = None
        self.frequency_penalty: float | None = None
        self.presence_penalty: float | None = None

        # usage
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None
        self.reasoning_tokens: int | None = None
        self.cached_tokens: int | None = None

        # completion / response
        self.completion: str | None = None
        self.finish_reason: str | None = None
        self.response_id: str | None = None

        # latency / transport
        self.ttft_ms: float | None = None
        self.streaming: bool | None = None
        self.api_version: str | None = None
        self.endpoint: str | None = None

        # free-form extension
        self.extra: dict[str, Any] = {}

    @property
    def total_tokens(self) -> int | None:
        if (
            self.input_tokens is None
            and self.output_tokens is None
        ):
            return None

        return (
            (self.input_tokens or 0)
            + (self.output_tokens or 0)
        )

    def set_prompts(
        self,
        *,
        system: str | None = None,
        user: str | None = None,
        template: str | None = None,
        version: str | None = None,
    ) -> None:
        if system is not None:
            self.system_prompt = system
        if user is not None:
            self.user_prompt = user
        if template is not None:
            self.prompt_template = template
        if version is not None:
            self.prompt_version = version

    def set_params(self, **kwargs: Any) -> None:
        """Set any of the model parameters (temperature, top_p, ...)."""
        allowed = {
            "temperature",
            "top_p",
            "top_k",
            "max_tokens",
            "stop",
            "frequency_penalty",
            "presence_penalty",
        }
        for key, value in kwargs.items():
            if key in allowed:
                setattr(self, key, value)
            else:
                self.extra[key] = value

    def set_usage(
        self,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        cached_tokens: int | None = None,
    ) -> None:
        if input_tokens is not None:
            self.input_tokens = input_tokens
        if output_tokens is not None:
            self.output_tokens = output_tokens
        if reasoning_tokens is not None:
            self.reasoning_tokens = reasoning_tokens
        if cached_tokens is not None:
            self.cached_tokens = cached_tokens

    def set_response_metadata(
        self,
        *,
        actual_model: str | None = None,
        cost_usd: float | None = None,
        finish_reason: str | None = None,
        api_version: str | None = None,
        endpoint: str | None = None,
        response_id: str | None = None,
    ) -> None:
        if actual_model is not None:
            self.actual_model = actual_model
        if cost_usd is not None:
            self.cost_usd = cost_usd
        if finish_reason is not None:
            self.finish_reason = finish_reason
        if api_version is not None:
            self.api_version = api_version
        if endpoint is not None:
            self.endpoint = endpoint
        if response_id is not None:
            self.response_id = response_id

    def set_completion(
        self,
        *,
        text: str | None = None,
        finish_reason: str | None = None,
    ) -> None:
        if text is not None:
            self.completion = text
        if finish_reason is not None:
            self.finish_reason = finish_reason

    def set_latency(
        self,
        *,
        ttft_ms: float | None = None,
        streaming: bool | None = None,
    ) -> None:
        if ttft_ms is not None:
            self.ttft_ms = ttft_ms
        if streaming is not None:
            self.streaming = streaming

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
        }

        if self.actual_model is not None:
            payload["actual_model"] = self.actual_model

        if self.cost_usd is not None:
            payload["cost_usd"] = self.cost_usd

        if self.system_prompt is not None:
            payload["system_prompt"] = self.system_prompt

        if self.user_prompt is not None:
            payload["user_prompt"] = self.user_prompt

        if self.prompt_template is not None:
            payload["prompt_template"] = self.prompt_template

        if self.prompt_version is not None:
            payload["prompt_version"] = self.prompt_version

        if self.temperature is not None:
            payload["temperature"] = self.temperature

        if self.top_p is not None:
            payload["top_p"] = self.top_p

        if self.top_k is not None:
            payload["top_k"] = self.top_k

        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens

        if self.stop is not None:
            payload["stop"] = self.stop

        if self.frequency_penalty is not None:
            payload["frequency_penalty"] = self.frequency_penalty

        if self.presence_penalty is not None:
            payload["presence_penalty"] = self.presence_penalty

        if self.input_tokens is not None:
            payload["input_tokens"] = self.input_tokens

        if self.output_tokens is not None:
            payload["output_tokens"] = self.output_tokens

        if self.reasoning_tokens is not None:
            payload["reasoning_tokens"] = self.reasoning_tokens

        if self.cached_tokens is not None:
            payload["cached_tokens"] = self.cached_tokens

        if self.total_tokens is not None:
            payload["total_tokens"] = self.total_tokens

        if self.completion is not None:
            payload["completion"] = self.completion

        if self.finish_reason is not None:
            payload["finish_reason"] = self.finish_reason

        if self.response_id is not None:
            payload["response_id"] = self.response_id

        if self.ttft_ms is not None:
            payload["ttft_ms"] = self.ttft_ms

        if self.streaming is not None:
            payload["streaming"] = self.streaming

        if self.api_version is not None:
            payload["api_version"] = self.api_version

        if self.endpoint is not None:
            payload["endpoint"] = self.endpoint

        payload.update(self.extra)

        return payload