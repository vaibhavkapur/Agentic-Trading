"""In-process typed event bus with subscriber dispatch and durable persistence hook."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from trading_platform.domain.contracts import DomainEvent
from trading_platform.domain.types import utc_now

EventHandler = Callable[[DomainEvent], None]


class EventBus:
    """Deterministic synchronous event bus for domain provenance and observability."""

    def __init__(self, persist_callback: Callable[[DomainEvent], None] | None = None) -> None:
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)
        self._wildcard_subscribers: list[EventHandler] = []
        self._persist_callback = persist_callback
        self._history: list[DomainEvent] = []

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        if event_type == "*":
            self._wildcard_subscribers.append(handler)
        else:
            self._subscribers[event_type].append(handler)

    def publish(
        self,
        *,
        event_type: str,
        policy_version: str,
        payload: dict[str, Any],
        run_id: str | None = None,
    ) -> DomainEvent:
        event = DomainEvent(
            event_id=f"EVT-{uuid4().hex[:12].upper()}",
            event_type=event_type,
            timestamp_utc=utc_now(),
            run_id=run_id,
            policy_version=policy_version,
            payload=payload,
        )
        self._history.append(event)
        if self._persist_callback is not None:
            self._persist_callback(event)
        for handler in self._subscribers.get(event_type, []):
            handler(event)
        for handler in self._wildcard_subscribers:
            handler(event)
        return event

    def recent_events(self, limit: int = 100) -> list[DomainEvent]:
        return list(self._history[-limit:])
