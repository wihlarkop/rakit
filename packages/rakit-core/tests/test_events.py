import asyncio
from dataclasses import dataclass

import pytest
from rakit_core.errors import RakitError
from rakit_core.events import DomainEvent, EventBus, EventPublisher


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
async def test_correlation_and_causation_propagate_through_nested_publish_pre() -> None:
    bus = EventBus()
    publisher = EventPublisher(bus)

    captured: dict[str, object] = {}

    async def on_order_created(_event: OrderCreated) -> None:
        first_envelope = bus.current_envelope()
        assert first_envelope is not None
        captured["first_event_id"] = first_envelope.event_id
        captured["first_correlation_id"] = first_envelope.correlation_id

        await publisher.publish_pre(OrderShipped(order_id="o-1"))

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
async def test_cycle_diagnostics_raises_on_deep_nested_publish_pre() -> None:
    bus = EventBus()
    publisher = EventPublisher(bus, max_causation_depth=3)

    async def on_order_created(_event: OrderCreated) -> None:
        await publisher.publish_pre(OrderCreated(order_id="o-1"))

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

        await publisher.publish_pre(ChildOfA(tag="child"))

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
