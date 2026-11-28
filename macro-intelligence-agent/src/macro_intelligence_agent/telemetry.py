"""Structured diagnostic counters and deterministic event recorder."""

from __future__ import annotations

from typing import Any, Dict, List

from .models import RunDiagnostics


class TelemetryCollector:
    """Collects structured diagnostic events and counters without wall-clock nondeterminism."""

    def __init__(self) -> None:
        self._counters: Dict[str, int] = {}
        self._events: List[Dict[str, Any]] = []
        self._seq: int = 0

    def increment(self, name: str, amount: int = 1) -> None:
        self._counters[name] = self._counters.get(name, 0) + amount

    def record(self, event_type: str, level: str = "INFO", **fields: Any) -> None:
        self._seq += 1
        entry: Dict[str, Any] = {
            "seq": self._seq,
            "level": level,
            "event": event_type,
        }
        for key in sorted(fields.keys()):
            entry[key] = fields[key]
        self._events.append(entry)

    def snapshot(self) -> RunDiagnostics:
        return RunDiagnostics(
            counters=dict(sorted(self._counters.items())),
            events=tuple(self._events),
        )
