import pytest
from rakit_core.di import ServiceRegistry, ServiceScope
from rakit_core.errors import RakitError


class Database:
    pass


class UnitOfWork:
    def __init__(self, database: Database) -> None:
        self.database = database


@pytest.mark.anyio
async def test_operation_service_is_reused_inside_one_operation() -> None:
    registry = ServiceRegistry()
    registry.add_value(Database, Database(), scope=ServiceScope.APPLICATION)
    registry.add_factory(
        UnitOfWork,
        lambda resolver: UnitOfWork(resolver.require(Database)),
        scope=ServiceScope.OPERATION,
    )

    async with registry.application_scope() as application:  # noqa: SIM117
        async with application.operation_scope() as operation:
            assert operation.require(UnitOfWork) is operation.require(UnitOfWork)


class ServiceA:
    def __init__(self, b: "ServiceB") -> None:
        self.b = b


class ServiceB:
    def __init__(self, a: ServiceA) -> None:
        self.a = a


@pytest.mark.anyio
async def test_circular_dependency_raises_rakit_error() -> None:
    registry = ServiceRegistry()
    registry.add_factory(
        ServiceA,
        lambda resolver: ServiceA(resolver.require(ServiceB)),
        scope=ServiceScope.APPLICATION,
    )
    registry.add_factory(
        ServiceB,
        lambda resolver: ServiceB(resolver.require(ServiceA)),
        scope=ServiceScope.APPLICATION,
    )

    async with registry.application_scope() as application:
        with pytest.raises(RakitError) as exc_info:
            application.require(ServiceA)

        assert exc_info.value.code == "di.circular_dependency"


class NarrowService:
    pass


class WideServiceDependingOnNarrow:
    def __init__(self, narrow: NarrowService) -> None:
        self.narrow = narrow


@pytest.mark.anyio
async def test_captive_dependency_raises_rakit_error() -> None:
    registry = ServiceRegistry()
    registry.add_factory(NarrowService, lambda _: NarrowService(), scope=ServiceScope.OPERATION)
    registry.add_factory(
        WideServiceDependingOnNarrow,
        lambda resolver: WideServiceDependingOnNarrow(resolver.require(NarrowService)),
        scope=ServiceScope.APPLICATION,
    )

    async with registry.application_scope() as application:
        with pytest.raises(RakitError) as exc_info:
            application.require(WideServiceDependingOnNarrow)

        assert exc_info.value.code == "di.captive_dependency"
