from __future__ import annotations

from contextlib import AbstractAsyncContextManager

from rakit_core.events import EventPublisher
from rakit_core.operations import OperationContext
from rakit_core.transactions import OperationUnitOfWork, TransactionPolicy
from rakit_web.uow_selection import ResourceUnitOfWorkRegistry


class StubFactory:
    def open(
        self,
        *,
        policy: TransactionPolicy,
        event_publisher: EventPublisher | None,
        operation_context: OperationContext,
    ) -> AbstractAsyncContextManager[OperationUnitOfWork]:
        raise AssertionError("selection tests do not open transactions")


def test_resource_selection_uses_compiled_provider_binding() -> None:
    first = StubFactory()
    second = StubFactory()
    registry = ResourceUnitOfWorkRegistry(
        factories={"persistence.first": first, "persistence.second": second},
        resource_provider_ids={"users": "persistence.first", "orders": "persistence.second"},
    )

    assert registry.for_resource("users") is first
    assert registry.for_resource("orders") is second
    assert registry.for_resource("unbound") is None


def test_page_default_exists_only_when_one_provider_is_installed() -> None:
    only = StubFactory()
    assert (
        ResourceUnitOfWorkRegistry(
            factories={"persistence.only": only},
            resource_provider_ids={},
        ).sole_provider()
        is only
    )

    assert (
        ResourceUnitOfWorkRegistry(factories={}, resource_provider_ids={}).sole_provider() is None
    )
    assert (
        ResourceUnitOfWorkRegistry(
            factories={"persistence.first": StubFactory(), "persistence.second": StubFactory()},
            resource_provider_ids={},
        ).sole_provider()
        is None
    )


def test_registry_distinguishes_missing_from_ambiguous_page_provider() -> None:
    none = ResourceUnitOfWorkRegistry(factories={}, resource_provider_ids={})
    many = ResourceUnitOfWorkRegistry(
        factories={"persistence.first": StubFactory(), "persistence.second": StubFactory()},
        resource_provider_ids={},
    )

    assert none.provider_count == 0
    assert many.provider_count == 2
    assert none.has_any_provider is False
    assert many.has_any_provider is True
