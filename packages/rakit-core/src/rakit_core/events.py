import inspect
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from rakit_core.errors import ErrorCode, RakitError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DomainEvent:
    pass


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    event_name: str
    event_version: int
    occurred_at: datetime
    payload: DomainEvent
    correlation_id: str | None = None
    causation_id: str | None = None


class EventBus:
    def __init__(self) -> None:
        self.handlers: dict[type[DomainEvent], list[tuple[int, Callable[[Any], Any]]]] = {}
        self._dispatch_stack: list[EventEnvelope] = []

    def subscribe(self, event_type, handler, *, priority: int = 0) -> None:
        entries = self.handlers.setdefault(event_type, [])
        entries.append((priority, handler))
        entries.sort(key=lambda entry: entry[0])

    async def dispatch(self, envelope: EventEnvelope) -> None:
        self._dispatch_stack.append(envelope)
        try:
            for _, handler in self.handlers.get(type(envelope.payload), []):
                result = handler(envelope.payload)
                if inspect.isawaitable(result):
                    await result
        finally:
            self._dispatch_stack.pop()


class EventPublisher:
    def __init__(
        self,
        bus: EventBus,
        *,
        max_queue_depth: int = 1000,
        max_causation_depth: int = 20,
    ) -> None:
        self.bus = bus
        self.deferred: list[EventEnvelope] = []
        self.max_queue_depth = max_queue_depth
        self.max_causation_depth = max_causation_depth

    def _build_envelope(self, event: DomainEvent, *, version: int) -> EventEnvelope:
        current_depth = len(self.bus._dispatch_stack)
        if current_depth > self.max_causation_depth:
            raise RakitError(
                code=ErrorCode.EVENTS_CAUSATION_DEPTH_EXCEEDED,
                message=(
                    "Event causation chain depth "
                    f"({current_depth}) exceeds the configured limit "
                    f"({self.max_causation_depth}); this likely indicates a cyclic "
                    "chain of events triggering each other."
                ),
                status_code=500,
            )

        parent = self.bus._dispatch_stack[-1] if self.bus._dispatch_stack else None
        event_id = str(uuid.uuid4())
        correlation_id = parent.correlation_id if parent is not None else event_id
        causation_id = parent.event_id if parent is not None else None

        return EventEnvelope(
            event_id=event_id,
            event_name=f"{type(event).__module__}.{type(event).__qualname__}",
            event_version=version,
            occurred_at=datetime.now(UTC),
            payload=event,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )

    def publish(self, event: DomainEvent, *, version: int = 1) -> None:
        if len(self.deferred) >= self.max_queue_depth:
            raise RakitError(
                code=ErrorCode.EVENTS_QUEUE_DEPTH_EXCEEDED,
                message=(
                    "Deferred event queue depth exceeds the configured limit "
                    f"({self.max_queue_depth})."
                ),
                status_code=500,
            )

        envelope = self._build_envelope(event, version=version)
        self.deferred.append(envelope)

    async def publish_pre(self, event: DomainEvent, *, version: int = 1) -> None:
        envelope = self._build_envelope(event, version=version)
        await self.bus.dispatch(envelope)

    async def after_commit(self) -> None:
        queue, self.deferred = self.deferred, []
        for envelope in queue:
            try:
                await self.bus.dispatch(envelope)
            except Exception:
                logger.exception(
                    "Post-commit event handler failed for event %s (event_id=%s); continuing.",
                    envelope.event_name,
                    envelope.event_id,
                )

    def after_rollback(self) -> None:
        self.deferred.clear()
