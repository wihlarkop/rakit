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
        first_envelope = bus._dispatch_stack[-1]
        captured["first_event_id"] = first_envelope.event_id
        captured["first_correlation_id"] = first_envelope.correlation_id

        await publisher.publish_pre(OrderShipped(order_id="o-1"))

    def on_order_shipped(_event: OrderShipped) -> None:
        second_envelope = bus._dispatch_stack[-1]
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
