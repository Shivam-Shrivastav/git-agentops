from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from .events import Event


class BaseEmitter(ABC):

    @abstractmethod
    def emit(self, event: Event) -> None:
        ...

    def emit_many(self, events: Iterable[Event]) -> None:
        for event in events:
            self.emit(event)


class ConsoleEmitter(BaseEmitter):

    def emit(self, event: Event) -> None:

        print(
            f"[{event.event_type.value}] "
            f"{event.name}"
        )

        print(event.model_dump_json(indent=2))


class NullEmitter(BaseEmitter):

    def emit(self, event: Event) -> None:
        pass