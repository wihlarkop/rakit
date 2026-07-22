from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from .compatibility import validate_official_package_versions
from .datasource import DataSource
from .definitions import ResourceDefinition, RouteDefinition
from .di import ServiceRegistry, _RegistrySnapshot
from .errors import ErrorCode, RakitError

RESERVED_PATH_PREFIXES = ("/_system",)

OFFICIAL_PACKAGE_NAMES = (
    "rakit",
    "rakit-core",
    "rakit-web",
    "rakit-sqlalchemy",
    "rakit-auth-sqlalchemy",
    "rakit-storage",
    "rakit-storage-local",
    "rakit-server-uvicorn",
)


class Plugin(Protocol):
    plugin_id: str

    def configure(self, builder: "ApplicationBuilder") -> None: ...


def _is_path_parameter(segment: str) -> bool:
    return len(segment) > 2 and segment.startswith("{") and segment.endswith("}")


def _path_patterns_overlap(first: str, second: str) -> bool:
    """Return whether two backend-neutral route patterns can match one URL path."""

    first_segments = () if first == "/" else tuple(first.removeprefix("/").split("/"))
    second_segments = () if second == "/" else tuple(second.removeprefix("/").split("/"))
    if len(first_segments) != len(second_segments):
        return False
    return all(
        first_segment == second_segment
        or _is_path_parameter(first_segment)
        or _is_path_parameter(second_segment)
        for first_segment, second_segment in zip(first_segments, second_segments, strict=True)
    )


def _has_path_parameter(path: str) -> bool:
    return any(_is_path_parameter(segment) for segment in path.split("/"))


def _is_safe_owned_static_precedence(
    first_path: str,
    first_owner: str,
    second_path: str,
    second_owner: str,
) -> bool:
    """Allow a same-owner static route to precede its dynamic fallback route."""

    return (
        first_owner == second_owner
        and first_path != second_path
        and not _has_path_parameter(first_path)
        and _has_path_parameter(second_path)
    )


@dataclass
class ApplicationBuilder:
    _routes: list[RouteDefinition] = field(default_factory=list)
    _resources: list[ResourceDefinition] = field(default_factory=list)
    _plugin_ids: list[str] = field(default_factory=list)
    _registry: ServiceRegistry = field(default_factory=ServiceRegistry)
    _plugin_conflicts: dict[str, tuple[str, ...]] = field(default_factory=dict)
    _adapters: dict[str, Callable[[type], DataSource | None]] = field(default_factory=dict)
    _compiled: bool = field(default=False, init=False)
    _install_depth: int = field(default=0, init=False)

    @property
    def routes(self) -> tuple[RouteDefinition, ...]:
        return tuple(self._routes)

    @property
    def resources(self) -> tuple[ResourceDefinition, ...]:
        return tuple(self._resources)

    @property
    def plugins(self) -> tuple[str, ...]:
        return tuple(self._plugin_ids)

    @property
    def registry(self) -> ServiceRegistry:
        return self._registry

    def _check_not_compiled(self) -> None:
        if self._compiled:
            raise RakitError(
                code=ErrorCode.CONFIG_ALREADY_COMPILED,
                message="Cannot modify an ApplicationBuilder after it has been compiled.",
                status_code=500,
            )

    def _mark_compiled(self) -> None:
        self._compiled = True
        self.registry._freeze()

    def add_route(self, route: RouteDefinition) -> None:
        self._check_not_compiled()
        self._routes.append(route)

    def add_resource(self, definition: ResourceDefinition) -> None:
        self._check_not_compiled()
        if any(existing.resource_id == definition.resource_id for existing in self._resources):
            raise RakitError(
                code=ErrorCode.CONFIG_DUPLICATE_RESOURCE,
                message=f'Resource "{definition.resource_id}" is already registered.',
                status_code=500,
                details={"resource_id": definition.resource_id},
            )
        self._resources.append(definition)

    def register_adapter(self, name: str, claim: Callable[[type], DataSource | None]) -> None:
        self._check_not_compiled()
        if name in self._adapters:
            raise RakitError(
                code=ErrorCode.CONFIG_DUPLICATE_ADAPTER,
                message=f'Adapter "{name}" is already registered.',
                status_code=500,
                details={"adapter": name},
            )
        self._adapters[name] = claim

    def install(self, plugin: Plugin) -> None:
        self._check_not_compiled()
        if plugin.plugin_id in self._plugin_ids:
            raise RakitError(
                code=ErrorCode.CONFIG_DUPLICATE_PLUGIN,
                message=f'Plugin "{plugin.plugin_id}" is already installed.',
                status_code=500,
            )

        depends_on: tuple[str, ...] = getattr(plugin, "depends_on", ())
        for dependency_id in depends_on:
            if dependency_id not in self._plugin_ids:
                raise RakitError(
                    code=ErrorCode.CONFIG_MISSING_PLUGIN_DEPENDENCY,
                    message=(
                        f'Plugin "{plugin.plugin_id}" depends on "{dependency_id}", '
                        "which is not installed."
                    ),
                    status_code=500,
                    details={"plugin": plugin.plugin_id, "missing_dependency": dependency_id},
                )

        conflicts_with: tuple[str, ...] = getattr(plugin, "conflicts_with", ())
        for conflicting_id in conflicts_with:
            if conflicting_id in self._plugin_ids:
                raise RakitError(
                    code=ErrorCode.CONFIG_PLUGIN_CONFLICT,
                    message=(
                        f'Plugin "{plugin.plugin_id}" conflicts with already-installed '
                        f'plugin "{conflicting_id}".'
                    ),
                    status_code=500,
                    details={"plugin": plugin.plugin_id, "conflicts_with": conflicting_id},
                )

        for installed_id, installed_conflicts in self._plugin_conflicts.items():
            if plugin.plugin_id in installed_conflicts:
                raise RakitError(
                    code=ErrorCode.CONFIG_PLUGIN_CONFLICT,
                    message=(
                        f'Plugin "{plugin.plugin_id}" conflicts with already-installed '
                        f'plugin "{installed_id}".'
                    ),
                    status_code=500,
                    details={"plugin": plugin.plugin_id, "conflicts_with": installed_id},
                )

        snapshot = _InstallSnapshot.capture(self)

        self._plugin_ids.append(plugin.plugin_id)
        self._plugin_conflicts[plugin.plugin_id] = conflicts_with
        self._install_depth += 1
        try:
            plugin.configure(self)
            if self._registry._frozen and not snapshot.registry.frozen:
                raise RakitError(
                    code=ErrorCode.CONFIG_PLUGIN_FROZE_REGISTRY,
                    message=(
                        f'Plugin "{plugin.plugin_id}" left the service registry frozen without '
                        "the application being compiled; this is not allowed."
                    ),
                    status_code=500,
                    details={"plugin": plugin.plugin_id},
                )
        except BaseException:
            snapshot.restore(self)
            raise
        finally:
            self._install_depth -= 1


@dataclass
class _InstallSnapshot:
    routes: list[RouteDefinition]
    resources: list[ResourceDefinition]
    plugin_ids: list[str]
    plugin_conflicts: dict[str, tuple[str, ...]]
    adapters: dict[str, Callable[[type], DataSource | None]]
    compiled: bool
    registry: _RegistrySnapshot

    @classmethod
    def capture(cls, builder: "ApplicationBuilder") -> "_InstallSnapshot":
        return cls(
            routes=list(builder._routes),
            resources=list(builder._resources),
            plugin_ids=list(builder._plugin_ids),
            plugin_conflicts=dict(builder._plugin_conflicts),
            adapters=dict(builder._adapters),
            compiled=builder._compiled,
            registry=builder.registry._snapshot(),
        )

    def restore(self, builder: "ApplicationBuilder") -> None:
        builder._routes[:] = self.routes
        builder._resources[:] = self.resources
        builder._plugin_ids[:] = self.plugin_ids
        builder._plugin_conflicts.clear()
        builder._plugin_conflicts.update(self.plugin_conflicts)
        builder._adapters.clear()
        builder._adapters.update(self.adapters)
        builder._compiled = self.compiled
        builder.registry._restore(self.registry)


@dataclass(frozen=True)
class CompiledApplication:
    routes: tuple[RouteDefinition, ...]
    plugins: tuple[str, ...]
    resources: tuple[ResourceDefinition, ...]


def compile_application(builder: ApplicationBuilder) -> CompiledApplication:
    if builder._install_depth > 0:
        raise RakitError(
            code=ErrorCode.CONFIG_COMPILE_DURING_PLUGIN_INSTALL,
            message="Cannot compile the application while a plugin's configure() is still running.",
            status_code=500,
        )

    validate_official_package_versions(OFFICIAL_PACKAGE_NAMES)

    seen: dict[str, list[tuple[str, str, str]]] = {}
    seen_route_names: dict[str, RouteDefinition] = {}
    for route in builder.routes:
        if any(
            route.path == prefix or route.path.startswith(f"{prefix}/")
            for prefix in RESERVED_PATH_PREFIXES
        ):
            raise RakitError(
                code=ErrorCode.CONFIG_RESERVED_PATH,
                message=f'Route path "{route.path}" is reserved for framework use.',
                status_code=500,
                details={"path": route.path, "route_name": route.route_name},
            )

        if route.route_name in seen_route_names:
            raise RakitError(
                code=ErrorCode.CONFIG_ROUTE_NAME_COLLISION,
                message=f'Route name "{route.route_name}" is already used by another route.',
                status_code=500,
                details={"route_name": route.route_name},
            )
        seen_route_names[route.route_name] = route

        for method in route.methods:
            normalized_method = method.upper()
            for first_path, first_name, first_owner in seen.get(normalized_method, []):
                if _path_patterns_overlap(first_path, route.path) and not (
                    _is_safe_owned_static_precedence(
                        first_path,
                        first_owner,
                        route.path,
                        route.owner_id,
                    )
                ):
                    raise RakitError(
                        code=ErrorCode.CONFIG_ROUTE_COLLISION,
                        message=f"Route collision for {normalized_method} {route.path}.",
                        status_code=500,
                        details={"first": first_name, "second": route.route_name},
                    )
            seen.setdefault(normalized_method, []).append(
                (route.path, route.route_name, route.owner_id)
            )

    builder._mark_compiled()
    return CompiledApplication(builder.routes, builder.plugins, builder.resources)
