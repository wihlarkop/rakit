import pytest
from rakit_core.di import ServiceKey, ServiceRegistry, ServiceScope
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


class TransientWidget:
    pass


class AppServiceUsingTransient:
    def __init__(self, widget: TransientWidget) -> None:
        self.widget = widget


@pytest.mark.anyio
async def test_application_scope_may_depend_on_transient() -> None:
    registry = ServiceRegistry()
    registry.add_factory(TransientWidget, lambda _: TransientWidget(), scope=ServiceScope.TRANSIENT)
    registry.add_factory(
        AppServiceUsingTransient,
        lambda resolver: AppServiceUsingTransient(resolver.require(TransientWidget)),
        scope=ServiceScope.APPLICATION,
    )

    async with registry.application_scope() as application:
        service = application.require(AppServiceUsingTransient)
        assert isinstance(service.widget, TransientWidget)


class OperationThing:
    pass


class TransientBuilder:
    def __init__(self, thing: OperationThing) -> None:
        self.thing = thing


class AppServiceUsingTransientBuilder:
    def __init__(self, builder: TransientBuilder) -> None:
        self.builder = builder


class RequestServiceUsingTransientBuilder:
    def __init__(self, builder: TransientBuilder) -> None:
        self.builder = builder


class OperationServiceUsingTransientBuilder:
    def __init__(self, builder: TransientBuilder) -> None:
        self.builder = builder


def _build_transitive_captive_registry() -> ServiceRegistry:
    registry = ServiceRegistry()
    registry.add_factory(OperationThing, lambda _: OperationThing(), scope=ServiceScope.OPERATION)
    registry.add_factory(
        TransientBuilder,
        lambda resolver: TransientBuilder(resolver.require(OperationThing)),
        scope=ServiceScope.TRANSIENT,
    )
    return registry


@pytest.mark.anyio
async def test_application_scope_transient_transitively_capturing_operation_raises() -> None:
    registry = _build_transitive_captive_registry()
    registry.add_factory(
        AppServiceUsingTransientBuilder,
        lambda resolver: AppServiceUsingTransientBuilder(resolver.require(TransientBuilder)),
        scope=ServiceScope.APPLICATION,
    )

    async with registry.application_scope() as application:
        with pytest.raises(RakitError) as exc_info:
            application.require(AppServiceUsingTransientBuilder)

        assert exc_info.value.code == "di.captive_dependency"


@pytest.mark.anyio
async def test_request_scope_transient_transitively_capturing_operation_raises() -> None:
    registry = _build_transitive_captive_registry()
    registry.add_factory(
        RequestServiceUsingTransientBuilder,
        lambda resolver: RequestServiceUsingTransientBuilder(resolver.require(TransientBuilder)),
        scope=ServiceScope.REQUEST,
    )

    async with registry.application_scope() as application:  # noqa: SIM117
        async with application.request_scope() as request:
            with pytest.raises(RakitError) as exc_info:
                request.require(RequestServiceUsingTransientBuilder)

            assert exc_info.value.code == "di.captive_dependency"


@pytest.mark.anyio
async def test_operation_scope_transient_depending_on_operation_succeeds() -> None:
    registry = _build_transitive_captive_registry()
    registry.add_factory(
        OperationServiceUsingTransientBuilder,
        lambda resolver: OperationServiceUsingTransientBuilder(resolver.require(TransientBuilder)),
        scope=ServiceScope.OPERATION,
    )

    async with registry.application_scope() as application:  # noqa: SIM117
        async with application.operation_scope() as operation:
            service = operation.require(OperationServiceUsingTransientBuilder)
            assert isinstance(service.builder, TransientBuilder)


class Frozenable:
    pass


@pytest.mark.anyio
async def test_registry_not_frozen_accepts_registrations() -> None:
    registry = ServiceRegistry()
    registry.add_value(Frozenable, Frozenable(), scope=ServiceScope.APPLICATION)
    assert ServiceKey(Frozenable) in registry.providers


@pytest.mark.anyio
async def test_frozen_registry_rejects_add_value() -> None:
    registry = ServiceRegistry()
    registry.freeze()

    with pytest.raises(RakitError) as exc_info:
        registry.add_value(Frozenable, Frozenable(), scope=ServiceScope.APPLICATION)

    assert exc_info.value.code == "di.registry_frozen"


@pytest.mark.anyio
async def test_frozen_registry_rejects_add_factory() -> None:
    registry = ServiceRegistry()
    registry.freeze()

    with pytest.raises(RakitError) as exc_info:
        registry.add_factory(Frozenable, lambda _: Frozenable(), scope=ServiceScope.APPLICATION)

    assert exc_info.value.code == "di.registry_frozen"


class NamedDatabase:
    def __init__(self, label: str) -> None:
        self.label = label


@pytest.mark.anyio
async def test_named_services_resolve_to_different_instances() -> None:
    registry = ServiceRegistry()
    registry.add_factory(
        NamedDatabase,
        lambda _: NamedDatabase("primary"),
        scope=ServiceScope.APPLICATION,
        name="primary",
    )
    registry.add_factory(
        NamedDatabase,
        lambda _: NamedDatabase("secondary"),
        scope=ServiceScope.APPLICATION,
        name="secondary",
    )

    async with registry.application_scope() as application:
        primary = application.require(NamedDatabase, name="primary")
        secondary = application.require(NamedDatabase, name="secondary")

        assert primary.label == "primary"
        assert secondary.label == "secondary"
        assert primary is not secondary

        # cached per scope, keyed by name
        assert application.require(NamedDatabase, name="primary") is primary
        assert application.require(NamedDatabase, name="secondary") is secondary


@pytest.mark.anyio
async def test_unnamed_lookup_raises_when_only_named_registered() -> None:
    registry = ServiceRegistry()
    registry.add_factory(
        NamedDatabase,
        lambda _: NamedDatabase("primary"),
        scope=ServiceScope.APPLICATION,
        name="primary",
    )

    async with registry.application_scope() as application:
        with pytest.raises(KeyError):
            application.require(NamedDatabase)


@pytest.mark.anyio
async def test_named_and_unnamed_registration_of_same_type_coexist() -> None:
    registry = ServiceRegistry()
    registry.add_factory(
        NamedDatabase, lambda _: NamedDatabase("default"), scope=ServiceScope.APPLICATION
    )
    registry.add_factory(
        NamedDatabase,
        lambda _: NamedDatabase("primary"),
        scope=ServiceScope.APPLICATION,
        name="primary",
    )

    async with registry.application_scope() as application:
        default = application.require(NamedDatabase)
        primary = application.require(NamedDatabase, name="primary")
        assert default.label == "default"
        assert primary.label == "primary"
        assert default is not primary


@pytest.mark.anyio
async def test_duplicate_named_registration_raises() -> None:
    registry = ServiceRegistry()
    registry.add_value(
        NamedDatabase, NamedDatabase("primary"), scope=ServiceScope.APPLICATION, name="primary"
    )

    with pytest.raises(RakitError) as exc_info:
        registry.add_value(
            NamedDatabase,
            NamedDatabase("primary-2"),
            scope=ServiceScope.APPLICATION,
            name="primary",
        )

    assert exc_info.value.code == "di.duplicate_registration"


@pytest.mark.anyio
async def test_unnamed_and_named_registration_are_not_duplicates() -> None:
    registry = ServiceRegistry()
    registry.add_value(NamedDatabase, NamedDatabase("default"), scope=ServiceScope.APPLICATION)
    # Should NOT raise: different ServiceKey (name differs).
    registry.add_value(
        NamedDatabase, NamedDatabase("primary"), scope=ServiceScope.APPLICATION, name="primary"
    )

    assert ServiceKey(NamedDatabase) in registry.providers
    assert ServiceKey(NamedDatabase, "primary") in registry.providers


class NamedConsumerOfBoth:
    def __init__(self, primary: NamedDatabase, secondary: NamedDatabase) -> None:
        self.primary = primary
        self.secondary = secondary


@pytest.mark.anyio
async def test_resolving_two_named_variants_in_one_chain_is_not_a_false_cycle() -> None:
    registry = ServiceRegistry()
    registry.add_factory(
        NamedDatabase,
        lambda _: NamedDatabase("primary"),
        scope=ServiceScope.APPLICATION,
        name="primary",
    )
    registry.add_factory(
        NamedDatabase,
        lambda _: NamedDatabase("secondary"),
        scope=ServiceScope.APPLICATION,
        name="secondary",
    )
    registry.add_factory(
        NamedConsumerOfBoth,
        lambda resolver: NamedConsumerOfBoth(
            resolver.require(NamedDatabase, name="primary"),
            resolver.require(NamedDatabase, name="secondary"),
        ),
        scope=ServiceScope.APPLICATION,
    )

    async with registry.application_scope() as application:
        consumer = application.require(NamedConsumerOfBoth)
        assert consumer.primary.label == "primary"
        assert consumer.secondary.label == "secondary"
