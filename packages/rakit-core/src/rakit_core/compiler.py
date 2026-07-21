from dataclasses import dataclass, field
from typing import Protocol

from .compatibility import validate_official_package_versions
from .definitions import RouteDefinition
from .di import ServiceRegistry
from .errors import RakitError

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


@dataclass
class ApplicationBuilder:
    routes: list[RouteDefinition] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)
    registry: ServiceRegistry = field(default_factory=ServiceRegistry)
    _plugin_conflicts: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def add_route(self, route: RouteDefinition) -> None:
        self.routes.append(route)

    def install(self, plugin: Plugin) -> None:
        if plugin.plugin_id in self.plugins:
            raise RakitError(
                code="config.duplicate_plugin",
                message=f'Plugin "{plugin.plugin_id}" is already installed.',
                status_code=500,
            )

        depends_on: tuple[str, ...] = getattr(plugin, "depends_on", ())
        for dependency_id in depends_on:
            if dependency_id not in self.plugins:
                raise RakitError(
                    code="config.missing_plugin_dependency",
                    message=(
                        f'Plugin "{plugin.plugin_id}" depends on "{dependency_id}", '
                        "which is not installed."
                    ),
                    status_code=500,
                    details={"plugin": plugin.plugin_id, "missing_dependency": dependency_id},
                )

        conflicts_with: tuple[str, ...] = getattr(plugin, "conflicts_with", ())
        for conflicting_id in conflicts_with:
            if conflicting_id in self.plugins:
                raise RakitError(
                    code="config.plugin_conflict",
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
                    code="config.plugin_conflict",
                    message=(
                        f'Plugin "{plugin.plugin_id}" conflicts with already-installed '
                        f'plugin "{installed_id}".'
                    ),
                    status_code=500,
                    details={"plugin": plugin.plugin_id, "conflicts_with": installed_id},
                )

        self.plugins.append(plugin.plugin_id)
        self._plugin_conflicts[plugin.plugin_id] = conflicts_with
        plugin.configure(self)


@dataclass(frozen=True)
class CompiledApplication:
    routes: tuple[RouteDefinition, ...]
    plugins: tuple[str, ...]


def compile_application(builder: ApplicationBuilder) -> CompiledApplication:
    validate_official_package_versions(OFFICIAL_PACKAGE_NAMES)

    seen: dict[tuple[str, str], str] = {}
    seen_route_names: dict[str, RouteDefinition] = {}
    for route in builder.routes:
        if any(
            route.path == prefix or route.path.startswith(f"{prefix}/")
            for prefix in RESERVED_PATH_PREFIXES
        ):
            raise RakitError(
                code="config.reserved_path",
                message=f'Route path "{route.path}" is reserved for framework use.',
                status_code=500,
                details={"path": route.path, "route_name": route.route_name},
            )

        if route.route_name in seen_route_names:
            raise RakitError(
                code="config.route_name_collision",
                message=f'Route name "{route.route_name}" is already used by another route.',
                status_code=500,
                details={"route_name": route.route_name},
            )
        seen_route_names[route.route_name] = route

        for method in route.methods:
            key = (method.upper(), route.path)
            if key in seen:
                raise RakitError(
                    code="config.route_collision",
                    message=f"Route collision for {method.upper()} {route.path}.",
                    status_code=500,
                    details={"first": seen[key], "second": route.route_name},
                )
            seen[key] = route.route_name
    return CompiledApplication(tuple(builder.routes), tuple(builder.plugins))
