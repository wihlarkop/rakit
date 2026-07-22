from collections.abc import Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType, TracebackType
from typing import Any, TypeVar

from rakit_core.errors import ErrorCode, RakitError

T = TypeVar("T")


@dataclass(frozen=True)
class ServiceKey[T]:
    """Identifies a registered service by type and an optional name.

    Two providers may be registered for the same ``service_type`` as long as
    they use different ``name`` values, allowing optional named services
    (e.g. ``resolver.require(Database, name="primary")``). A ``name`` of
    ``None`` is the default, unnamed registration for a type and behaves
    exactly as service lookups did before named services existed.
    """

    service_type: type[T]
    name: str | None = None


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
        self.resolving: set[ServiceKey[Any]] = set()
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
        self.instances: dict[ServiceKey[Any], Any] = {}
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

    def require(self, service_type: type[T], *, name: str | None = None) -> T:
        return self.registry.resolve(service_type, self, name=name)

    def request_scope(self) -> "ServiceResolver":
        return ServiceResolver(self.registry, ServiceScope.REQUEST, self)

    def operation_scope(self) -> "ServiceResolver":
        return ServiceResolver(self.registry, ServiceScope.OPERATION, self)


Factory = Callable[[ServiceResolver], Any]


@dataclass(frozen=True)
class _RegistrySnapshot:
    providers: dict[ServiceKey[Any], tuple[ServiceScope, Factory]]
    frozen: bool


class ServiceRegistry:
    def __init__(self) -> None:
        self._providers: dict[ServiceKey[Any], tuple[ServiceScope, Factory]] = {}
        self._frozen: bool = False

    @property
    def providers(self) -> Mapping[ServiceKey[Any], tuple[ServiceScope, Factory]]:
        return MappingProxyType(self._providers)

    def _freeze(self) -> None:
        self._frozen = True

    def _snapshot(self) -> "_RegistrySnapshot":
        return _RegistrySnapshot(providers=dict(self._providers), frozen=self._frozen)

    def _restore(self, snapshot: "_RegistrySnapshot") -> None:
        self._providers.clear()
        self._providers.update(snapshot.providers)
        self._frozen = snapshot.frozen

    def add_value(
        self, service_type: type[T], value: T, *, scope: ServiceScope, name: str | None = None
    ) -> None:
        if scope is not ServiceScope.APPLICATION:
            raise RakitError(
                code=ErrorCode.DI_INVALID_VALUE_SCOPE,
                message=(
                    "add_value() only supports ServiceScope.APPLICATION; use add_factory() for "
                    "REQUEST, OPERATION, and TRANSIENT scopes."
                ),
                status_code=500,
                details={"service_type": service_type.__name__, "scope": str(scope)},
            )
        key = ServiceKey(service_type, name)
        self._check_frozen(key)
        self._check_duplicate_registration(key)
        self._providers[key] = (scope, lambda _: value)

    def add_factory(
        self,
        service_type: type[T],
        factory: Factory,
        *,
        scope: ServiceScope,
        name: str | None = None,
    ) -> None:
        key = ServiceKey(service_type, name)
        self._check_frozen(key)
        self._check_duplicate_registration(key)
        self._providers[key] = (scope, factory)

    def _check_frozen(self, key: ServiceKey[Any]) -> None:
        if self._frozen:
            raise RakitError(
                code=ErrorCode.DI_REGISTRY_FROZEN,
                message=(
                    f"Cannot register {key.service_type.__name__}: the service registry has "
                    "already been frozen and no longer accepts new registrations."
                ),
                status_code=500,
                details={"service_type": key.service_type.__name__},
            )

    def _check_duplicate_registration(self, key: ServiceKey[Any]) -> None:
        if key in self._providers:
            raise RakitError(
                code=ErrorCode.DI_DUPLICATE_REGISTRATION,
                message=(
                    f"Service {key.service_type.__name__} is already registered; "
                    "re-registration would silently overwrite the previous provider."
                ),
                status_code=500,
                details={"service_type": key.service_type.__name__},
            )

    def resolve(
        self, service_type: type[T], resolver: ServiceResolver, *, name: str | None = None
    ) -> T:
        is_top_level = resolver._resolution_context is None
        if is_top_level:
            resolver._resolution_context = _ResolutionContext()
        context = resolver._resolution_context
        assert context is not None
        try:
            return self._resolve(ServiceKey(service_type, name), resolver, context)
        finally:
            if is_top_level:
                resolver._resolution_context = None

    def _resolve(
        self, key: ServiceKey[T], resolver: ServiceResolver, context: _ResolutionContext
    ) -> T:
        scope, factory = self._providers[key]
        self._check_captive_dependency(key, scope, context)

        if scope is ServiceScope.TRANSIENT:
            return self._invoke_factory(key, scope, factory, resolver, context)

        owner = resolver
        while owner.scope is not scope and owner.parent is not None:
            owner = owner.parent
        if owner.scope is not scope:
            raise RuntimeError(f"No {scope} scope is active for {key.service_type.__name__}")

        if key not in owner.instances:
            owner.instances[key] = self._invoke_factory(key, scope, factory, owner, context)

        return owner.instances[key]

    def application_scope(self) -> ServiceResolver:
        return ServiceResolver(self, ServiceScope.APPLICATION)

    def _check_captive_dependency(
        self, key: ServiceKey[Any], scope: ServiceScope, context: _ResolutionContext
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
                    f"{key.service_type.__name__}, which is registered at the narrower "
                    f"{scope} scope."
                ),
                status_code=500,
            )

    def _invoke_factory(
        self,
        key: ServiceKey[Any],
        scope: ServiceScope,
        factory: Factory,
        resolver: ServiceResolver,
        context: _ResolutionContext,
    ) -> Any:
        if key in context.resolving:
            raise RakitError(
                code=ErrorCode.DI_CIRCULAR_DEPENDENCY,
                message=(
                    f"Circular dependency detected while resolving {key.service_type.__name__}."
                ),
                status_code=500,
            )
        context.resolving.add(key)
        if scope is ServiceScope.TRANSIENT:
            effective_scope = (
                context.effective_scope_stack[-1] if context.effective_scope_stack else scope
            )
        else:
            effective_scope = scope
        context.effective_scope_stack.append(effective_scope)
        owns_resolver_context = resolver._resolution_context is None
        if owns_resolver_context:
            resolver._resolution_context = context
        try:
            return factory(resolver)
        finally:
            if owns_resolver_context:
                resolver._resolution_context = None
            context.effective_scope_stack.pop()
            context.resolving.discard(key)
