from __future__ import annotations

import atexit
import json
import os
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from typing import Iterable

import requests

from .events import Event


class BaseEmitter(ABC):

    @abstractmethod
    def emit(self, event: Event) -> None:
        ...

    def emit_many(self, events: Iterable[Event]) -> None:
        for event in events:
            self.emit(event)


class ConsoleEmitter(BaseEmitter):

    def emit(self, event: Event):

        print(
            f"{event.event_type.value:<18}"
            f"{event.name:<20}"
            f"status={event.status:<8}"
            f"duration={event.duration_ms}"
        )

        print(event.model_dump_json(indent=2))


class NullEmitter(BaseEmitter):

    def emit(self, event: Event) -> None:
        pass


class MultiEmitter(BaseEmitter):

    def __init__(self, emitters: Iterable[BaseEmitter]):
        self.emitters = list(emitters)

    def emit(self, event: Event) -> None:
        for emitter in self.emitters:
            emitter.emit(event)


class HTTPEmitter(BaseEmitter):
    """
    Sends events to the AgentOps ingestion API.

    By default this is a *batched, non-blocking, durable* emitter:

      * emit() appends to an in-memory queue and returns immediately,
        so the agent's hot path is never blocked by telemetry.
      * a daemon thread flushes the queue in batches to
        POST <endpoint>/batch every ``flush_interval`` seconds (or
        when ``max_batch`` events accumulate).
      * failed POSTs are retried with exponential backoff; if the
        endpoint stays down the batch is spilled to disk
        (~/.agentops/spill/*.jsonl) and replayed on the next start,
        so events survive an ingestion-API outage.

    Pass ``batch=False`` for the original one-POST-per-event behaviour.

    The endpoint and API key fall back to the AGENTOPS_ENDPOINT and
    AGENTOPS_API_KEY environment variables. When an API key is present
    an ``Authorization: Bearer <key>`` header is sent on every POST.
    """

    def __init__(
        self,
        endpoint: str | None = None,
        *,
        timeout: float = 5.0,
        api_key: str | None = None,
        batch: bool = True,
        max_batch: int = 100,
        flush_interval: float = 1.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        spill_dir: str | None = None,
    ):
        self.endpoint = endpoint or os.getenv("AGENTOPS_ENDPOINT")
        if self.endpoint is None:
            raise ValueError(
                "HTTPEmitter requires an endpoint: pass endpoint= or set "
                "AGENTOPS_ENDPOINT."
            )

        self.api_key = api_key or os.getenv("AGENTOPS_API_KEY")
        self.timeout = timeout
        self.batch = batch
        self.max_batch = max_batch
        self.flush_interval = flush_interval
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.spill_dir = spill_dir or os.path.expanduser(
            "~/.agentops/spill"
        )

        # Derive the batch URL: ".../events" -> ".../events/batch".
        if self.endpoint.rstrip("/").endswith("/events"):
            self.batch_endpoint = self.endpoint.rstrip("/") + "/batch"
        else:
            self.batch_endpoint = self.endpoint

        if not self.batch:
            return

        # --- batched mode machinery ---
        self._queue: deque[dict] = deque()
        self._lock = threading.Lock()
        self._flush_event = threading.Event()
        self._closed = False

        # Replay anything spilled by a previous, interrupted run.
        self._replay_spill()

        self._thread = threading.Thread(
            target=self._flush_loop,
            name="agentops-http-emitter",
            daemon=True,
        )
        self._thread.start()
        atexit.register(self.close)

    # -- public API ---------------------------------------------------

    def emit(self, event: Event) -> None:
        if not self.batch:
            payload = event.model_dump(mode="json")
            if not self._post(payload, self.endpoint):
                self._spill([payload])
            return

        with self._lock:
            self._queue.append(event.model_dump(mode="json"))
            should_flush = len(self._queue) >= self.max_batch

        if should_flush:
            self._flush_event.set()

    def flush(self) -> None:
        """Flush pending events synchronously (mainly for tests)."""
        if not self.batch:
            return
        self._drain_and_post()

    def close(self) -> None:
        """Flush remaining events and stop the background thread."""
        if not self.batch or self._closed:
            return
        self._closed = True
        self._flush_event.set()
        self._thread.join(timeout=10)
        # Final synchronous drain in case the loop exited early.
        self._drain_and_post()

    # -- internals ----------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    def _post(self, payloads, url: str) -> bool:
        """
        POST payloads (a dict for a single event, a list for a batch)
        to url with retry + backoff. Returns True on success, False if
        all retries were exhausted.
        """
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.post(
                    url,
                    json=payloads,
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return True
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(
                        self.backoff_base * (2 ** (attempt - 1))
                    )

        print(
            f"[AgentOps] Failed to deliver {self._count(payloads)} "
            f"event(s) to {url} after {self.max_retries} attempts: "
            f"{last_exc}"
        )
        return False

    @staticmethod
    def _count(payloads) -> int:
        if isinstance(payloads, list):
            return len(payloads)
        return 1

    def _flush_loop(self) -> None:
        while not self._closed:
            self._flush_event.wait(self.flush_interval)
            self._flush_event.clear()
            self._drain_and_post()

        # One final drain after the loop exits (close path).
        self._drain_and_post()

    def _drain_and_post(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    return
                take = min(self.max_batch, len(self._queue))
                batch = [
                    self._queue.popleft() for _ in range(take)
                ]

            if self._post(batch, self.batch_endpoint):
                continue

            # Endpoint looks down: spill this batch and everything
            # still queued, then stop trying this cycle. The spilled
            # events are replayed on the next emitter start.
            self._spill(batch)
            with self._lock:
                rest = list(self._queue)
                self._queue.clear()
            if rest:
                self._spill(rest)
            return

    def _spill(self, events: list[dict]) -> None:
        try:
            os.makedirs(self.spill_dir, exist_ok=True)
            path = os.path.join(
                self.spill_dir, f"spill-{time.time_ns()}.jsonl"
            )
            with open(path, "a", encoding="utf-8") as fh:
                for event in events:
                    fh.write(json.dumps(event) + "\n")
        except OSError as exc:
            print(
                f"[AgentOps] Could not spill {len(events)} event(s) "
                f"to {self.spill_dir}: {exc}"
            )

    def _replay_spill(self) -> None:
        if not os.path.isdir(self.spill_dir):
            return
        try:
            names = sorted(
                f for f in os.listdir(self.spill_dir)
                if f.startswith("spill-") and f.endswith(".jsonl")
            )
        except OSError:
            return

        for name in names:
            path = os.path.join(self.spill_dir, name)
            try:
                with open(path, encoding="utf-8") as fh:
                    events = [
                        json.loads(line)
                        for line in fh
                        if line.strip()
                    ]
            except (OSError, json.JSONDecodeError):
                continue

            if events:
                with self._lock:
                    self._queue.extend(events)

            try:
                os.remove(path)
            except OSError:
                pass