from __future__ import annotations

from typing import Any


class ToolSpan:
    """
    Mutable outcome metadata for a tool invocation.

    The start event carries the tool name + arguments (what went in).
    The caller attaches the result after the tool returns, and the end
    event carries the outcome fields below (what came back). The worker
    merges start + end so a span row holds both the arguments and the
    result.
    """

    def __init__(self, tool_name: str, args: dict[str, Any]) -> None:
        self.tool = tool_name
        self.args = args

        self.return_value: Any | None = None
        self.http_status: int | None = None
        self.result_size_bytes: int | None = None
        self.retries: int | None = None
        self.error: str | None = None

        # explicit status override ("error" when set_error is called)
        self._status: str | None = None

    def set_result(
        self,
        *,
        return_value: Any | None = None,
        http_status: int | None = None,
        result_size: int | None = None,
        retries: int | None = None,
    ) -> None:
        if return_value is not None:
            self.return_value = return_value
        if http_status is not None:
            self.http_status = http_status
        if result_size is not None:
            self.result_size_bytes = result_size
        if retries is not None:
            self.retries = retries

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

        if self.return_value is not None:
            payload["result"] = self.return_value

        if self.http_status is not None:
            payload["http_status"] = self.http_status

        if self.result_size_bytes is not None:
            payload["result_size_bytes"] = self.result_size_bytes

        if self.retries is not None:
            payload["retries"] = self.retries

        if self.error is not None:
            payload["error"] = self.error

        return payload