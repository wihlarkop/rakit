from collections.abc import Callable
from contextlib import AsyncExitStack
from enum import StrEnum
from types import TracebackType
from typing import Any, TypeVar

from rakit_core.errors import RakitError

T = TypeVar("T")


class ServiceScope(StrEnum):
    APPLICATION = "application"
    REQUEST = "request"
    OPERATION = "operation"
    TRANSIENT = "transient"


_SCOPE_RANK: dict[ServiceScope, int] = {
    ServiceScope.APPLICATION: 0,
    ServiceScope.REQUEST: 1,
    ServiceScope.OPERATION: 2,
    ServiceScope.TRANSIENT: 3,
}


class ServiceResolver:
    def __init__(
        self,
        registry: "ServiceRegistry",
        scope: ServiceScope,
        parent: "ServiceResolver | None" = None,
    ) -> None:
        self.registry = registry
        self.scope = scope
        self.parent = parent
        self.instances: dict[type[Any], Any] = {}
        self.stack = AsyncExitStack()

    async def __aenter__(self) -> "ServiceResolver":
        await self.stack.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.stack.__aexit__(exc_type, exc_value, traceback)

    def require(self, service_type: type[T]) -> T:
        return self.registry.resolve(service_type, self)

    def request_scope(self) -> "ServiceResolver":
        return ServiceResolver(self.registry, ServiceScope.REQUEST, self)

    def operation_scope(self) -> "ServiceResolver":
        return ServiceResolver(self.registry, ServiceScope.OPERATION, self)


Factory = Callable[[ServiceResolver], Any]


class ServiceRegistry:
    def __init__(self) -> None:
        self.providers: dict[type[Any], tuple[ServiceScope, Factory]] = {}
        self._resolving: set[type[Any]] = set()
        self._consumer_scope_stack: list[ServiceScope] = []

    def add_value(self, service_type: type[T], value: T, *, scope: ServiceScope) -> None:
        self.providers[service_type] = (scope, lambda _: value)

    def add_factory(self, service_type: type[T], factory: Factory, *, scope: ServiceScope) -> None:
        self.providers[service_type] = (scope, factory)

    def resolve(self, service_type: type[T], resolver: ServiceResolver) -> T:
        scope, factory = self.providers[service_type]
        self._check_captive_dependency(service_type, scope)

        if scope is ServiceScope.TRANSIENT:
            return self._invoke_factory(service_type, scope, factory, resolver)

        owner = resolver
        while owner.scope is not scope and owner.parent is not None:
            owner = owner.parent
        if owner.scope is not scope:
            raise RuntimeError(f"No {scope} scope is active for {service_type.__name__}")

        if service_type not in owner.instances:
            owner.instances[service_type] = self._invoke_factory(
                service_type, scope, factory, resolver
            )

        return owner.instances[service_type]

    def application_scope(self) -> ServiceResolver:
        return ServiceResolver(self, ServiceScope.APPLICATION)

    def _check_captive_dependency(self, service_type: type[Any], scope: ServiceScope) -> None:
        if scope is ServiceScope.TRANSIENT:
            return
        if not self._consumer_scope_stack:
            return
        consumer_scope = self._consumer_scope_stack[-1]
        if _SCOPE_RANK[consumer_scope] < _SCOPE_RANK[scope]:
            raise RakitError(
                code="di.captive_dependency",
                message=(
                    f"Captive dependency detected: a {consumer_scope} service cannot depend on "
                    f"{service_type.__name__}, which is registered at the narrower {scope} scope."
                ),
                status_code=500,
            )

    def _invoke_factory(
        self,
        service_type: type[Any],
        scope: ServiceScope,
        factory: Factory,
        resolver: ServiceResolver,
    ) -> Any:
        if service_type in self._resolving:
            raise RakitError(
                code="di.circular_dependency",
                message=f"Circular dependency detected while resolving {service_type.__name__}.",
                status_code=500,
            )
        self._resolving.add(service_type)
        self._consumer_scope_stack.append(scope)
        try:
            return factory(resolver)
        finally:
            self._consumer_scope_stack.pop()
            self._resolving.discard(service_type)
