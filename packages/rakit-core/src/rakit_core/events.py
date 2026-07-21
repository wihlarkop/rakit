import asyncio
import inspect
import logging
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, TypeVar, cast

from rakit_core.errors import ErrorCode, RakitError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DomainEvent:
    pass


E = TypeVar("E", bound=DomainEvent)

#: A subscribed event handler. Handlers may be plain synchronous functions
#: returning any value, or asynchronous functions returning an awaitable;
#: ``EventBus.dispatch`` awaits the result whenever it is awaitable
#: (``inspect.isawaitable``), so both call styles are accepted. Stored
#: internally against the base ``DomainEvent`` type since handlers for
#: different event types share one dict; ``subscribe`` accepts (and
#: dispatch always calls) a handler with its own specific ``event_type``,
#: never a mismatched one, so the narrowing is sound even though it isn't
#: expressible in the stored container's type.
EventHandler = Callable[[DomainEvent], Any]


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    event_name: str
    event_version: int
    occurred_at: datetime
    payload: DomainEvent
    correlation_id: str | None = None
    causation_id: str | None = None
    #: Logical causation-chain depth: 0 for a root/top-level event, else
    #: ``parent.causation_depth + 1``. Tracked explicitly as envelope
    #: metadata rather than inferred from live dispatch-call-stack depth,
    #: because under the non-recursive ``EventPublisher.publish_pre`` design
    #: ``EventBus.dispatch`` never nests (call-stack depth is always <= 1),
    #: even though the logical parent -> child -> grandchild chain can still
    #: grow arbitrarily deep via the drain queue.
    causation_depth: int = 0


class EventBus:
    def __init__(self) -> None:
        self.handlers: dict[type[DomainEvent], list[tuple[int, EventHandler]]] = {}
        self._envelope_stack: ContextVar[tuple[EventEnvelope, ...]] = ContextVar(
            f"rakit_event_envelope_stack_{id(self)}", default=()
        )

    def subscribe(
        self, event_type: type[E], handler: Callable[[E], Any], *, priority: int = 0
    ) -> None:
        entries = self.handlers.setdefault(event_type, [])
        entries.append((priority, cast(EventHandler, handler)))
        entries.sort(key=lambda entry: entry[0])

    def current_envelope(self) -> EventEnvelope | None:
        """Return the innermost envelope currently dispatching on this task's context."""
        stack = self._envelope_stack.get()
        return stack[-1] if stack else None

    def current_dispatch_depth(self) -> int:
        """Return how many envelopes are currently in-flight on this task's context."""
        return len(self._envelope_stack.get())

    async def dispatch(
        self,
        envelope: EventEnvelope,
        *,
        on_handler_error: Literal["raise", "log_and_continue"] = "raise",
    ) -> None:
        """Dispatch ``envelope`` to every handler subscribed to its payload type.

        ``on_handler_error`` controls what happens when a handler raises:

        - ``"raise"`` (default): the exception propagates immediately and any
          remaining handlers for this envelope are skipped. Used for
          pre-commit ("can this operation proceed?") dispatch, where a
          rejection must stop processing.
        - ``"log_and_continue"``: the exception is logged and the next
          handler subscribed to the SAME event still runs. Used for
          post-commit dispatch, where one observer's failure must not starve
          sibling observers of the same event.
        """
        token = self._envelope_stack.set((*self._envelope_stack.get(), envelope))
        try:
            for _, handler in self.handlers.get(type(envelope.payload), []):
                try:
                    result = handler(envelope.payload)
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    if on_handler_error == "raise":
                        raise
                    logger.exception(
                        "Post-commit event handler failed for event %s (event_id=%s); continuing.",
                        envelope.event_name,
                        envelope.event_id,
                    )
        finally:
            self._envelope_stack.reset(token)


@dataclass
class _PreDrainState:
    """Per-task drain state for a single top-level ``publish_pre`` call chain.

    Held behind a per-``EventPublisher``-instance ``ContextVar`` so that
    concurrent operations (different asyncio tasks) get isolated state
    automatically, while nested calls made from *the same task* correctly
    observe and share the same active state.

    ``owner_task`` records which ``asyncio.Task`` actually started this
    drain. This is essential because ``ContextVar`` values are copied (not
    shared) whenever a new ``asyncio.Task`` is created: a child task spawned
    with ``asyncio.create_task(...)`` while a drain is active on the parent
    task gets its own frozen copy of whatever this ContextVar held at that
    moment. Without an explicit ownership check, that child task would later
    see a stale, inherited state object and wrongly treat itself as "nested"
    -- enqueuing onto a queue that no pump will ever come back to drain, and
    silently losing the event. Checking ``asyncio.current_task() is
    state.owner_task`` (see ``EventPublisher._active_state_for_current_task``)
    ensures only the task that actually owns an active drain can observe it;
    every other task treats the ContextVar as if it held ``None``.
    """

    owner_task: "asyncio.Task[Any] | None"
    active: bool
    queue: list[EventEnvelope] = field(default_factory=list)
    processed: int = 0


class EventPublisher:
    def __init__(
        self,
        bus: EventBus,
        *,
        max_queue_depth: int = 1000,
        max_causation_depth: int = 20,
        max_total_processed_per_drain: int = 10_000,
    ) -> None:
        self.bus = bus
        self.deferred: list[EventEnvelope] = []
        self.max_queue_depth = max_queue_depth
        self.max_causation_depth = max_causation_depth
        self.max_total_processed_per_drain = max_total_processed_per_drain
        self._pre_drain_state: ContextVar[_PreDrainState | None] = ContextVar(
            f"rakit_pre_drain_state_{id(self)}", default=None
        )

    def _build_envelope(self, event: DomainEvent, *, version: int) -> EventEnvelope:
        parent = self.bus.current_envelope()
        causation_depth = parent.causation_depth + 1 if parent is not None else 0
        if causation_depth >= self.max_causation_depth:
            raise RakitError(
                code=ErrorCode.EVENTS_CAUSATION_DEPTH_EXCEEDED,
                message=(
                    "Event causation chain depth "
                    f"({causation_depth}) exceeds the configured limit "
                    f"({self.max_causation_depth}); this likely indicates a cyclic "
                    "chain of events triggering each other."
                ),
                status_code=500,
            )

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
            causation_depth=causation_depth,
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

    def _active_state_for_current_task(self) -> "_PreDrainState | None":
        """Return the drain state if -- and only if -- the CURRENT task is
        its genuine owner.

        A state inherited via ``ContextVar`` copying from a DIFFERENT (e.g.
        parent) task must never be treated as this task's own active drain:
        see the note on ``_PreDrainState`` for why that check is required.
        """
        state = self._pre_drain_state.get()
        if state is not None and state.active and asyncio.current_task() is state.owner_task:
            return state
        return None

    def _enqueue(self, state: "_PreDrainState", envelope: EventEnvelope) -> None:
        if len(state.queue) >= self.max_queue_depth:
            raise RakitError(
                code=ErrorCode.EVENTS_QUEUE_DEPTH_EXCEEDED,
                message=(
                    f"Pre-event queue depth exceeds the configured limit ({self.max_queue_depth})."
                ),
                status_code=500,
            )
        state.queue.append(envelope)

    async def _drain(self, state: "_PreDrainState") -> None:
        while state.queue:
            state.processed += 1
            if state.processed > self.max_total_processed_per_drain:
                state.queue.clear()
                raise RakitError(
                    code=ErrorCode.EVENTS_DRAIN_BUDGET_EXCEEDED,
                    message=(
                        "Pre-event drain processed more than the configured "
                        f"budget ({self.max_total_processed_per_drain}) of "
                        "envelopes in a single publish_pre call chain; this "
                        "likely indicates events that keep re-triggering "
                        "themselves without terminating."
                    ),
                    status_code=500,
                )
            envelope = state.queue.pop(0)
            await self.bus.dispatch(envelope, on_handler_error="raise")

    async def publish_pre(self, event: DomainEvent, *, version: int = 1) -> None:
        """Publish a pre-commit event and wait for it (and anything it
        transitively triggers via ``enqueue_pre``) to finish dispatching.

        This is the TOP-LEVEL, operation-facing API: it starts a fresh drain
        owned by the CURRENT ``asyncio.Task``, dispatches ``event`` and
        drains anything transitively queued during that dispatch, and only
        returns once every one of those events has actually been processed
        -- rejections propagate to the caller.

        It must NOT be called recursively from within a handler that is
        itself running as part of an active drain on the same task; that is
        rejected with ``RakitError(code="events.nested_publish_pre_not_allowed")``,
        because a synchronously-blocking nested drain would either deadlock
        or silently violate the "only one dispatch() active at a time per
        task" invariant. Handlers that need to publish another pre-event
        from within their own execution must call ``enqueue_pre`` instead,
        which queues onto the SAME active drain without waiting.
        """
        if self._active_state_for_current_task() is not None:
            raise RakitError(
                code=ErrorCode.EVENTS_NESTED_PUBLISH_PRE_NOT_ALLOWED,
                message=(
                    "publish_pre() cannot be called recursively from within an "
                    "active pre-event handler on the same task. Use "
                    "enqueue_pre() instead to queue a nested pre-event for the "
                    "active drain."
                ),
                status_code=500,
            )

        state = _PreDrainState(owner_task=asyncio.current_task(), active=True)
        token = self._pre_drain_state.set(state)
        try:
            envelope = self._build_envelope(event, version=version)
            self._enqueue(state, envelope)
            await self._drain(state)
        finally:
            state.active = False
            self._pre_drain_state.reset(token)

    async def enqueue_pre(self, event: DomainEvent, *, version: int = 1) -> None:
        """Queue a pre-commit event onto the CURRENT task's active drain,
        without waiting for it to be dispatched.

        This is the explicit, NESTED-handler API: call it from within a
        handler that is itself running as part of an active ``publish_pre``
        drain on this same task. The active pump (running further up this
        same task's call stack) will process the queued event in its turn,
        after the handler that called ``enqueue_pre`` returns.

        Raises ``RakitError(code="events.enqueue_pre_without_active_drain")``
        if there is no active drain owned by the current task -- it is
        meaningless to call ``enqueue_pre`` outside of a
        ``publish_pre``-initiated drain running on the same task.
        """
        state = self._active_state_for_current_task()
        if state is None:
            raise RakitError(
                code=ErrorCode.EVENTS_ENQUEUE_PRE_WITHOUT_ACTIVE_DRAIN,
                message=(
                    "enqueue_pre() can only be called from within an active "
                    "publish_pre() drain running on the same task."
                ),
                status_code=500,
            )
        envelope = self._build_envelope(event, version=version)
        self._enqueue(state, envelope)

    async def after_commit(self) -> None:
        while self.deferred:
            envelope = self.deferred.pop(0)
            await self.bus.dispatch(envelope, on_handler_error="log_and_continue")

    def after_rollback(self) -> None:
        self.deferred.clear()
