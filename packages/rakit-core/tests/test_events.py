import asyncio
from dataclasses import dataclass
from typing import Literal

import pytest
from rakit_core.errors import RakitError
from rakit_core.events import DomainEvent, EventBus, EventEnvelope, EventPublisher


@dataclass(frozen=True)
class OrderCreated(DomainEvent):
    order_id: str


@dataclass(frozen=True)
class OrderShipped(DomainEvent):
    order_id: str


@dataclass(frozen=True)
class OrderArchived(DomainEvent):
    order_id: str


@dataclass(frozen=True)
class RootA(DomainEvent):
    tag: str


@dataclass(frozen=True)
class RootB(DomainEvent):
    tag: str


@dataclass(frozen=True)
class ChildOfA(DomainEvent):
    tag: str


@dataclass(frozen=True)
class ChildTaskEvent(DomainEvent):
    tag: str


@pytest.mark.anyio
async def test_event_is_delivered_after_commit() -> None:
    received: list[str] = []
    bus = EventBus()
    bus.subscribe(OrderCreated, lambda event: received.append(event.order_id))
    publisher = EventPublisher(bus)

    publisher.publish(OrderCreated(order_id="o-1"))
    assert received == []
    await publisher.after_commit()
    assert received == ["o-1"]


@pytest.mark.anyio
async def test_rollback_discards_events() -> None:
    received: list[str] = []
    bus = EventBus()
    bus.subscribe(OrderCreated, lambda event: received.append(event.order_id))
    publisher = EventPublisher(bus)
    publisher.publish(OrderCreated(order_id="o-1"))
    publisher.after_rollback()
    assert received == []


@pytest.mark.anyio
async def test_publish_pre_dispatches_serially_and_can_reject() -> None:
    bus = EventBus()

    def rejecting_handler(_event: OrderCreated) -> None:
        raise ValueError("rejected")

    bus.subscribe(OrderCreated, rejecting_handler)
    publisher = EventPublisher(bus)

    with pytest.raises(ValueError, match="rejected"):
        await publisher.publish_pre(OrderCreated(order_id="o-1"))


@pytest.mark.anyio
async def test_post_commit_logs_and_continues_after_handler_failure() -> None:
    ran: list[str] = []
    bus = EventBus()

    def failing_handler(_event: OrderCreated) -> None:
        raise RuntimeError("boom")

    bus.subscribe(OrderCreated, failing_handler)
    bus.subscribe(OrderShipped, lambda event: ran.append(event.order_id))

    publisher = EventPublisher(bus)
    publisher.publish(OrderCreated(order_id="o-1"))
    publisher.publish(OrderShipped(order_id="o-1"))

    await publisher.after_commit()

    assert ran == ["o-1"]


@pytest.mark.anyio
async def test_publish_raises_when_queue_depth_exceeded() -> None:
    bus = EventBus()
    publisher = EventPublisher(bus, max_queue_depth=2)

    publisher.publish(OrderCreated(order_id="o-1"))
    publisher.publish(OrderCreated(order_id="o-2"))

    with pytest.raises(RakitError) as exc_info:
        publisher.publish(OrderCreated(order_id="o-3"))

    assert exc_info.value.code == "events.queue_depth_exceeded"


@pytest.mark.anyio
async def test_correlation_and_causation_propagate_through_nested_enqueue_pre() -> None:
    bus = EventBus()
    publisher = EventPublisher(bus)

    captured: dict[str, object] = {}

    async def on_order_created(_event: OrderCreated) -> None:
        first_envelope = bus.current_envelope()
        assert first_envelope is not None
        captured["first_event_id"] = first_envelope.event_id
        captured["first_correlation_id"] = first_envelope.correlation_id

        await publisher.enqueue_pre(OrderShipped(order_id="o-1"))

    def on_order_shipped(_event: OrderShipped) -> None:
        second_envelope = bus.current_envelope()
        assert second_envelope is not None
        captured["second_causation_id"] = second_envelope.causation_id
        captured["second_correlation_id"] = second_envelope.correlation_id

    bus.subscribe(OrderCreated, on_order_created)
    bus.subscribe(OrderShipped, on_order_shipped)

    await publisher.publish_pre(OrderCreated(order_id="o-1"))

    assert captured["second_causation_id"] == captured["first_event_id"]
    assert captured["second_correlation_id"] == captured["first_correlation_id"]
    assert captured["first_correlation_id"] is not None


@pytest.mark.anyio
async def test_cycle_diagnostics_raises_on_deep_nested_enqueue_pre() -> None:
    bus = EventBus()
    publisher = EventPublisher(bus, max_causation_depth=3)

    async def on_order_created(_event: OrderCreated) -> None:
        await publisher.enqueue_pre(OrderCreated(order_id="o-1"))

    bus.subscribe(OrderCreated, on_order_created)

    with pytest.raises(RakitError) as exc_info:
        await publisher.publish_pre(OrderCreated(order_id="o-1"))

    assert exc_info.value.code == "events.causation_depth_exceeded"


@pytest.mark.anyio
async def test_after_commit_drains_events_deferred_by_handlers_during_the_same_call() -> None:
    ran: list[str] = []
    bus = EventBus()
    publisher = EventPublisher(bus)

    def on_order_created(event: OrderCreated) -> None:
        ran.append(f"created:{event.order_id}")
        # Nested publish() during after_commit() must still be drained within
        # this same after_commit() call, not stranded until a later call.
        publisher.publish(OrderArchived(order_id=event.order_id))

    def on_order_archived(event: OrderArchived) -> None:
        ran.append(f"archived:{event.order_id}")

    bus.subscribe(OrderCreated, on_order_created)
    bus.subscribe(OrderArchived, on_order_archived)

    publisher.publish(OrderCreated(order_id="o-1"))

    await publisher.after_commit()

    assert ran == ["created:o-1", "archived:o-1"]
    assert publisher.deferred == []


@pytest.mark.anyio
async def test_concurrent_dispatch_does_not_cross_contaminate_causation_chains() -> None:
    bus = EventBus()
    publisher = EventPublisher(bus)

    a_started = asyncio.Event()
    b_started = asyncio.Event()
    b_may_return = asyncio.Event()
    captured: dict[str, object] = {}

    async def on_root_a(_event: RootA) -> None:
        own_envelope = bus.current_envelope()
        assert own_envelope is not None
        captured["a_event_id"] = own_envelope.event_id
        captured["a_correlation_id"] = own_envelope.correlation_id

        a_started.set()
        # Wait until B has genuinely entered its own dispatch (pushed its own
        # envelope onto its own task context) before proceeding.
        await b_started.wait()

        # B is now concurrently "in-flight" on a sibling task, but A's own
        # context must be unaffected by that.
        assert bus.current_dispatch_depth() == 1
        assert bus.current_envelope() is own_envelope

        await publisher.enqueue_pre(ChildOfA(tag="child"))

        # Let B proceed to completion only after A has already read/used its
        # own (uncontaminated) chain.
        b_may_return.set()

    async def on_root_b(_event: RootB) -> None:
        await a_started.wait()
        b_started.set()
        # Stay "in-flight" (own envelope still pushed) until A has finished
        # reading its own chain and published its child event.
        await b_may_return.wait()

    async def on_child_of_a(_event: ChildOfA) -> None:
        envelope = bus.current_envelope()
        assert envelope is not None
        captured["child_causation_id"] = envelope.causation_id
        captured["child_correlation_id"] = envelope.correlation_id

    bus.subscribe(RootA, on_root_a)
    bus.subscribe(RootB, on_root_b)
    bus.subscribe(ChildOfA, on_child_of_a)

    task_a = asyncio.create_task(publisher.publish_pre(RootA(tag="a")))
    task_b = asyncio.create_task(publisher.publish_pre(RootB(tag="b")))

    await asyncio.gather(task_a, task_b)

    assert captured["child_causation_id"] == captured["a_event_id"]
    assert captured["child_correlation_id"] == captured["a_correlation_id"]


@pytest.mark.anyio
async def test_separate_event_buses_do_not_share_dispatch_context() -> None:
    """Two independent EventBus/EventPublisher pairs must not contaminate each
    other's envelope stack even when one's dispatch is nested (same task)
    inside the other's dispatch."""
    bus_a = EventBus()
    publisher_a = EventPublisher(bus_a)
    bus_b = EventBus()
    publisher_b = EventPublisher(bus_b)

    captured: dict[str, object] = {}

    async def on_root_a(_event: RootA) -> None:
        assert bus_a.current_dispatch_depth() == 1
        await publisher_b.publish_pre(RootB(tag="b"))

    def on_root_b(_event: RootB) -> None:
        envelope = bus_b.current_envelope()
        assert envelope is not None
        captured["b_causation_id"] = envelope.causation_id
        captured["b_dispatch_depth"] = bus_b.current_dispatch_depth()

    bus_a.subscribe(RootA, on_root_a)
    bus_b.subscribe(RootB, on_root_b)

    await publisher_a.publish_pre(RootA(tag="a"))

    assert captured["b_causation_id"] is None
    assert captured["b_dispatch_depth"] == 1


@pytest.mark.anyio
async def test_dispatch_never_has_more_than_one_active_call_even_when_nested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Instrument EventBus.dispatch itself to prove that, even across a 3+
    level deep chain of nested publish_pre calls, only one dispatch() call is
    ever active at a time -- the property the queue-based redesign exists to
    guarantee."""
    bus = EventBus()
    publisher = EventPublisher(bus)

    active = {"count": 0}
    max_active = {"value": 0}
    original_dispatch = EventBus.dispatch

    async def instrumented_dispatch(
        self: EventBus,
        envelope: EventEnvelope,
        *,
        on_handler_error: Literal["raise", "log_and_continue"] = "raise",
    ) -> None:
        active["count"] += 1
        max_active["value"] = max(max_active["value"], active["count"])
        try:
            await original_dispatch(self, envelope, on_handler_error=on_handler_error)
        finally:
            active["count"] -= 1

    monkeypatch.setattr(EventBus, "dispatch", instrumented_dispatch)

    depth_counter = {"n": 0}

    async def on_order_created(event: OrderCreated) -> None:
        depth_counter["n"] += 1
        if depth_counter["n"] < 4:
            # Nest at least 3 levels deep.
            await publisher.enqueue_pre(OrderCreated(order_id=event.order_id))

    bus.subscribe(OrderCreated, on_order_created)

    await publisher.publish_pre(OrderCreated(order_id="o-1"))

    assert depth_counter["n"] == 4
    assert max_active["value"] == 1
    assert active["count"] == 0


@pytest.mark.anyio
async def test_queue_and_causation_limits_terminate_self_triggering_chain() -> None:
    """With max_queue_depth=2 and max_causation_depth=2, a handler that keeps
    publishing one more instance of the same event must terminate with a
    RakitError rather than hanging or silently exceeding the limits. Tracing
    the implementation: the pre-drain queue never holds more than one pending
    envelope at a time for this chain shape (each dispatch pops one before
    the handler re-queues one), so causation_depth crosses the limit before
    the queue-depth check ever does."""
    bus = EventBus()
    publisher = EventPublisher(bus, max_queue_depth=2, max_causation_depth=2)

    async def on_order_created(event: OrderCreated) -> None:
        await publisher.enqueue_pre(OrderCreated(order_id=event.order_id))

    bus.subscribe(OrderCreated, on_order_created)

    with pytest.raises(RakitError) as exc_info:
        await publisher.publish_pre(OrderCreated(order_id="o-1"))

    assert exc_info.value.code == "events.causation_depth_exceeded"


@pytest.mark.anyio
async def test_unbounded_self_triggering_chain_terminates_via_causation_depth() -> None:
    """A handler that always republishes itself, run with the (generous but
    finite) default limits, must terminate with a stable RakitError rather
    than hanging. With the defaults (max_causation_depth=20,
    max_total_processed_per_drain=10_000), causation_depth grows by 1 on
    every republish of the SAME logical chain, so it crosses its limit long
    before the drain-processed budget would; that's exercised separately by
    test_drain_budget_exceeded_for_many_sibling_pre_events below."""
    bus = EventBus()
    publisher = EventPublisher(bus)

    async def on_order_created(event: OrderCreated) -> None:
        await publisher.enqueue_pre(OrderCreated(order_id=event.order_id))

    bus.subscribe(OrderCreated, on_order_created)

    with pytest.raises(RakitError) as exc_info:
        await publisher.publish_pre(OrderCreated(order_id="o-1"))

    assert exc_info.value.code == "events.causation_depth_exceeded"


@pytest.mark.anyio
async def test_drain_budget_exceeded_for_many_sibling_pre_events() -> None:
    """Exercise max_total_processed_per_drain directly: a handler that
    publishes many SIBLING events (all at the same causation depth, from the
    same outer pump) rather than deepening the causation chain. This should
    exhaust the total-processed-per-drain budget without ever approaching
    the (generous default) causation-depth limit."""
    bus = EventBus()
    publisher = EventPublisher(bus, max_total_processed_per_drain=5)

    async def on_root_a(event: RootA) -> None:
        for i in range(20):
            await publisher.enqueue_pre(ChildOfA(tag=f"{event.tag}-{i}"))

    bus.subscribe(RootA, on_root_a)
    bus.subscribe(ChildOfA, lambda _event: None)

    with pytest.raises(RakitError) as exc_info:
        await publisher.publish_pre(RootA(tag="root"))

    assert exc_info.value.code == "events.drain_budget_exceeded"


@pytest.mark.anyio
async def test_after_commit_continues_to_second_handler_after_first_raises() -> None:
    """First post-commit handler for an event raises; the second handler
    subscribed to the SAME event must still run, and after_commit() itself
    must not raise (log-and-continue, now enforced per-handler inside
    dispatch() rather than per-envelope around it)."""
    ran: list[str] = []
    bus = EventBus()

    def first_handler(_event: OrderCreated) -> None:
        raise RuntimeError("boom")

    def second_handler(event: OrderCreated) -> None:
        ran.append(event.order_id)

    bus.subscribe(OrderCreated, first_handler, priority=0)
    bus.subscribe(OrderCreated, second_handler, priority=1)

    publisher = EventPublisher(bus)
    publisher.publish(OrderCreated(order_id="o-1"))

    await publisher.after_commit()

    assert ran == ["o-1"]


@pytest.mark.anyio
async def test_publish_pre_stops_at_first_failing_handler_for_same_event() -> None:
    """First pre-event handler for an event raises; subsequent handlers
    subscribed to the SAME event must NOT run, and the exception must
    propagate (raise semantics, unlike post-commit's log-and-continue)."""
    ran = {"second": False}
    bus = EventBus()

    def first_handler(_event: OrderCreated) -> None:
        raise ValueError("rejected")

    def second_handler(_event: OrderCreated) -> None:
        ran["second"] = True

    bus.subscribe(OrderCreated, first_handler, priority=0)
    bus.subscribe(OrderCreated, second_handler, priority=1)

    publisher = EventPublisher(bus)

    with pytest.raises(ValueError, match="rejected"):
        await publisher.publish_pre(OrderCreated(order_id="o-1"))

    assert ran["second"] is False


@pytest.mark.anyio
async def test_child_task_created_during_drain_gets_own_drain_after_parent_finishes() -> None:
    """Finding 1 regression: a child asyncio.Task spawned via
    asyncio.create_task() while a parent task's publish_pre drain is active
    must NOT inherit the parent's (possibly-stale) _PreDrainState via
    ContextVar copying. If it did, the child's own later publish_pre call
    would wrongly think it is "nested" inside the parent's drain, enqueue its
    envelope, and return immediately without ever actually dispatching it
    (because the parent's pump has already finished and will never come back
    to drain it) -- silently and permanently losing the event."""
    bus = EventBus()
    publisher = EventPublisher(bus)

    child_may_publish = asyncio.Event()
    order: list[str] = []
    child_dispatched: list[str] = []

    async def on_child_event(event: ChildTaskEvent) -> None:
        order.append("child_handler_ran")
        child_dispatched.append(event.tag)

    bus.subscribe(ChildTaskEvent, on_child_event)

    task_holder: dict[str, asyncio.Task[None]] = {}

    async def child_task_body() -> None:
        await child_may_publish.wait()
        order.append("child_publish_pre_start")
        await publisher.publish_pre(ChildTaskEvent(tag="child"))
        order.append("child_publish_pre_return")

    async def on_root_a(_event: RootA) -> None:
        task_holder["task"] = asyncio.create_task(child_task_body())
        # Give the child task a chance to actually start running (and park
        # on child_may_publish) before the root's own drain finishes.
        await asyncio.sleep(0)

    bus.subscribe(RootA, on_root_a)

    await publisher.publish_pre(RootA(tag="root"))

    # The root's own publish_pre call has now fully completed; the child
    # task is still parked on child_may_publish, holding a ContextVar copy
    # inherited from the moment it was created (while root's drain was
    # active).
    assert publisher._active_state_for_current_task() is None

    child_may_publish.set()
    await task_holder["task"]

    # The event must have been dispatched exactly once -- not lost.
    assert child_dispatched == ["child"]
    # The child's own publish_pre call must not have returned before its
    # handler actually ran.
    assert order == [
        "child_publish_pre_start",
        "child_handler_ran",
        "child_publish_pre_return",
    ]
    # No stray/stranded queue state remains afterward.
    assert publisher._active_state_for_current_task() is None


@pytest.mark.anyio
async def test_child_task_started_during_active_parent_drain_is_fully_isolated() -> None:
    """Same finding-1 scenario, but with the child task's own publish_pre
    call made WHILE the parent's pump is still active (not after it
    completes) -- proving the two tasks remain fully isolated from each
    other regardless of timing, via the owner_task check."""
    bus = EventBus()
    publisher = EventPublisher(bus)

    child_dispatched: list[str] = []

    async def on_child_event(event: ChildTaskEvent) -> None:
        child_dispatched.append(event.tag)

    bus.subscribe(ChildTaskEvent, on_child_event)

    async def child_task_body() -> None:
        # Runs concurrently, on a DIFFERENT task, while root's drain is
        # still active. This must succeed as its own independent top-level
        # drain, not be mistaken for a nested call into root's drain.
        await publisher.publish_pre(ChildTaskEvent(tag="child"))

    async def on_root_a(_event: RootA) -> None:
        root_state_before = publisher._active_state_for_current_task()
        assert root_state_before is not None
        assert root_state_before.owner_task is asyncio.current_task()

        child_task = asyncio.create_task(child_task_body())
        await child_task

        # Root's own drain state must be completely unaffected by the
        # child task's independent (and already-completed) drain.
        root_state_after = publisher._active_state_for_current_task()
        assert root_state_after is root_state_before
        assert root_state_after.owner_task is asyncio.current_task()

    bus.subscribe(RootA, on_root_a)

    await publisher.publish_pre(RootA(tag="root"))

    assert child_dispatched == ["child"]
    assert publisher._active_state_for_current_task() is None


@pytest.mark.anyio
async def test_publish_pre_top_level_call_waits_for_full_transitive_drain() -> None:
    """Normal (non-nested) top-level usage: by the time
    ``await publisher.publish_pre(event)`` returns, the event and anything it
    transitively enqueued via enqueue_pre have been fully dispatched."""
    bus = EventBus()
    publisher = EventPublisher(bus)
    ran: list[str] = []

    async def on_order_created(event: OrderCreated) -> None:
        ran.append("created")
        await publisher.enqueue_pre(OrderShipped(order_id=event.order_id))

    def on_order_shipped(_event: OrderShipped) -> None:
        ran.append("shipped")

    bus.subscribe(OrderCreated, on_order_created)
    bus.subscribe(OrderShipped, on_order_shipped)

    await publisher.publish_pre(OrderCreated(order_id="o-1"))

    assert ran == ["created", "shipped"]


@pytest.mark.anyio
async def test_nested_publish_pre_from_pump_task_is_rejected() -> None:
    """A handler that calls await publisher.publish_pre(nested_event) (NOT
    enqueue_pre) from within its own execution -- same task, active drain --
    must be rejected rather than silently handled."""
    bus = EventBus()
    publisher = EventPublisher(bus)

    async def on_order_created(_event: OrderCreated) -> None:
        await publisher.publish_pre(OrderShipped(order_id="o-1"))

    bus.subscribe(OrderCreated, on_order_created)

    with pytest.raises(RakitError) as exc_info:
        await publisher.publish_pre(OrderCreated(order_id="o-1"))

    assert exc_info.value.code == "events.nested_publish_pre_not_allowed"


@pytest.mark.anyio
async def test_enqueue_pre_from_handler_is_processed_before_outer_publish_pre_returns() -> None:
    """A handler for event A calls await publisher.enqueue_pre(B); B's
    handler must run before the outermost publish_pre(A) call returns."""
    bus = EventBus()
    publisher = EventPublisher(bus)
    b_ran = {"value": False}

    async def on_order_created(_event: OrderCreated) -> None:
        await publisher.enqueue_pre(OrderShipped(order_id="o-1"))

    def on_order_shipped(_event: OrderShipped) -> None:
        b_ran["value"] = True

    bus.subscribe(OrderCreated, on_order_created)
    bus.subscribe(OrderShipped, on_order_shipped)

    assert b_ran["value"] is False
    await publisher.publish_pre(OrderCreated(order_id="o-1"))
    assert b_ran["value"] is True


@pytest.mark.anyio
async def test_enqueue_pre_child_rejection_propagates_from_outer_publish_pre() -> None:
    """A's handler calls enqueue_pre(B); B's handler raises; the OUTERMOST
    await publisher.publish_pre(A) call must raise that same exception."""
    bus = EventBus()
    publisher = EventPublisher(bus)

    async def on_order_created(_event: OrderCreated) -> None:
        await publisher.enqueue_pre(OrderShipped(order_id="o-1"))

    def rejecting_shipped_handler(_event: OrderShipped) -> None:
        raise ValueError("shipped rejected")

    bus.subscribe(OrderCreated, on_order_created)
    bus.subscribe(OrderShipped, rejecting_shipped_handler)

    with pytest.raises(ValueError, match="shipped rejected"):
        await publisher.publish_pre(OrderCreated(order_id="o-1"))


@pytest.mark.anyio
async def test_enqueue_pre_without_active_drain_raises() -> None:
    """enqueue_pre() must raise a clear RakitError when there is no active
    drain owned by the current task -- it is meaningless to call it outside
    of a publish_pre-initiated drain running on the same task."""
    bus = EventBus()
    publisher = EventPublisher(bus)

    with pytest.raises(RakitError) as exc_info:
        await publisher.enqueue_pre(OrderCreated(order_id="o-1"))

    assert exc_info.value.code == "events.enqueue_pre_without_active_drain"
