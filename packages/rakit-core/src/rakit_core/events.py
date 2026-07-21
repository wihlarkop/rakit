import inspect
import logging
import uuid
from collections.abc import Callable
from contextvars import ContextVar
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
        self._envelope_stack: ContextVar[tuple[EventEnvelope, ...]] = ContextVar(
            f"rakit_event_envelope_stack_{id(self)}", default=()
        )

    def subscribe(self, event_type, handler, *, priority: int = 0) -> None:
        entries = self.handlers.setdefault(event_type, [])
        entries.append((priority, handler))
        entries.sort(key=lambda entry: entry[0])

    def current_envelope(self) -> EventEnvelope | None:
        """Return the innermost envelope currently dispatching on this task's context."""
        stack = self._envelope_stack.get()
        return stack[-1] if stack else None

    def current_dispatch_depth(self) -> int:
        """Return how many envelopes are currently in-flight on this task's context."""
        return len(self._envelope_stack.get())

    async def dispatch(self, envelope: EventEnvelope) -> None:
        token = self._envelope_stack.set((*self._envelope_stack.get(), envelope))
        try:
            for _, handler in self.handlers.get(type(envelope.payload), []):
                result = handler(envelope.payload)
                if inspect.isawaitable(result):
                    await result
        finally:
            self._envelope_stack.reset(token)


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
        current_depth = self.bus.current_dispatch_depth()
        if current_depth >= self.max_causation_depth:
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

        parent = self.bus.current_envelope()
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
        while self.deferred:
            envelope = self.deferred.pop(0)
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
