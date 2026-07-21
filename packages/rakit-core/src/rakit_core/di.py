from collections.abc import Callable
from contextlib import AsyncExitStack
from enum import StrEnum
from types import TracebackType
from typing import Any, TypeVar

from rakit_core.errors import ErrorCode, RakitError

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


class _ResolutionContext:
    __slots__ = ("effective_scope_stack", "resolving")

    def __init__(self) -> None:
        self.resolving: set[type[Any]] = set()
        self.effective_scope_stack: list[ServiceScope] = []


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
        self._resolution_context: _ResolutionContext | None = None

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
        self._frozen: bool = False

    def freeze(self) -> None:
        self._frozen = True

    def add_value(self, service_type: type[T], value: T, *, scope: ServiceScope) -> None:
        self._check_frozen(service_type)
        self._check_duplicate_registration(service_type)
        self.providers[service_type] = (scope, lambda _: value)

    def add_factory(self, service_type: type[T], factory: Factory, *, scope: ServiceScope) -> None:
        self._check_frozen(service_type)
        self._check_duplicate_registration(service_type)
        self.providers[service_type] = (scope, factory)

    def _check_frozen(self, service_type: type[Any]) -> None:
        if self._frozen:
            raise RakitError(
                code=ErrorCode.DI_REGISTRY_FROZEN,
                message=(
                    f"Cannot register {service_type.__name__}: the service registry has "
                    "already been frozen and no longer accepts new registrations."
                ),
                status_code=500,
                details={"service_type": service_type.__name__},
            )

    def _check_duplicate_registration(self, service_type: type[Any]) -> None:
        if service_type in self.providers:
            raise RakitError(
                code=ErrorCode.DI_DUPLICATE_REGISTRATION,
                message=(
                    f"Service {service_type.__name__} is already registered; "
                    "re-registration would silently overwrite the previous provider."
                ),
                status_code=500,
                details={"service_type": service_type.__name__},
            )

    def resolve(self, service_type: type[T], resolver: ServiceResolver) -> T:
        is_top_level = resolver._resolution_context is None
        if is_top_level:
            resolver._resolution_context = _ResolutionContext()
        context = resolver._resolution_context
        assert context is not None
        try:
            return self._resolve(service_type, resolver, context)
        finally:
            if is_top_level:
                resolver._resolution_context = None

    def _resolve(
        self, service_type: type[T], resolver: ServiceResolver, context: _ResolutionContext
    ) -> T:
        scope, factory = self.providers[service_type]
        self._check_captive_dependency(service_type, scope, context)

        if scope is ServiceScope.TRANSIENT:
            return self._invoke_factory(service_type, scope, factory, resolver, context)

        owner = resolver
        while owner.scope is not scope and owner.parent is not None:
            owner = owner.parent
        if owner.scope is not scope:
            raise RuntimeError(f"No {scope} scope is active for {service_type.__name__}")

        if service_type not in owner.instances:
            owner.instances[service_type] = self._invoke_factory(
                service_type, scope, factory, resolver, context
            )

        return owner.instances[service_type]

    def application_scope(self) -> ServiceResolver:
        return ServiceResolver(self, ServiceScope.APPLICATION)

    def _check_captive_dependency(
        self, service_type: type[Any], scope: ServiceScope, context: _ResolutionContext
    ) -> None:
        if scope is ServiceScope.TRANSIENT:
            return
        if not context.effective_scope_stack:
            return
        consumer_scope = context.effective_scope_stack[-1]
        if _SCOPE_RANK[consumer_scope] < _SCOPE_RANK[scope]:
            raise RakitError(
                code=ErrorCode.DI_CAPTIVE_DEPENDENCY,
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
        context: _ResolutionContext,
    ) -> Any:
        if service_type in context.resolving:
            raise RakitError(
                code=ErrorCode.DI_CIRCULAR_DEPENDENCY,
                message=f"Circular dependency detected while resolving {service_type.__name__}.",
                status_code=500,
            )
        context.resolving.add(service_type)
        if scope is ServiceScope.TRANSIENT:
            effective_scope = (
                context.effective_scope_stack[-1] if context.effective_scope_stack else scope
            )
        else:
            effective_scope = scope
        context.effective_scope_stack.append(effective_scope)
        try:
            return factory(resolver)
        finally:
            context.effective_scope_stack.pop()
            context.resolving.discard(service_type)
