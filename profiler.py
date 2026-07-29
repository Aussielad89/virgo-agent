"""Thread-safe profiler singleton."""

import threading
from collections import defaultdict


class Profiler:
    _INSTANCE: "Profiler | None" = None
    _LOCK = threading.Lock()

    def __new__(cls):
        if cls._INSTANCE is None:
            with cls._LOCK:
                if cls._INSTANCE is None:
                    cls._INSTANCE = super().__new__(cls)
                    cls._INSTANCE._events = defaultdict(list)
        return cls._INSTANCE

    def record(self, event: str, ms: float) -> None:
        self._events[event].append(float(ms))

    def stats(self, event: str):
        values = self._events.get(event, [])
        if not values:
            return 0, 0.0, 0.0
        count = len(values)
        total_ms = sum(values)
        avg_ms = total_ms / count
        return count, avg_ms, total_ms

    def clear(self) -> None:
        self._events.clear()


def record(event: str, ms: float) -> None:
    Profiler().record(event, ms)


def stats(event: str):
    return Profiler().stats(event)


def clear() -> None:
    Profiler().clear()
