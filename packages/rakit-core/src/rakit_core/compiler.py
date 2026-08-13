from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from .compatibility import validate_official_package_versions
from .datasource import DataSource
from .definitions import (
    ActionDefinition,
    CompiledActionDefinition,
    CompiledEndpointDefinition,
    CompiledPageDefinition,
    EndpointDefinition,
    PageDefinition,
    ResourceDefinition,
    ResourceFieldPolicy,
    RouteDefinition,
)
from .di import ServiceRegistry, _RegistrySnapshot
from .errors import ErrorCode, RakitError
from .permissions import PermissionRequirement
from .relationships import CompiledRelationship

# Path prefixes Rakit owns. An application route allowed to occupy one of
# these is an authorization bypass, not merely a collision: `/auth/login`
# and `/auth/logout` are classified as explicitly public by
# `rakit_web`'s `AuthorizationMiddleware`, so a resource mounted there
# would be served to anonymous callers with no permission check at all.
# Only routes flagged `framework_owned` may live here.
RESERVED_PATH_PREFIXES = ("/_system", "/auth")
RESERVED_RESOURCE_SEGMENTS = frozenset({"_actions", "_relationships"})

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


type AdapterClaim = Callable[[type, ResourceFieldPolicy], DataSource | None]


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


def _uses_reserved_resource_segment(path: str) -> bool:
    return bool(RESERVED_RESOURCE_SEGMENTS.intersection(path.removeprefix("/").split("/")))


def _is_safe_owned_static_precedence(
    first_path: str,
    first_owner: str,
    second_path: str,
    second_owner: str,
) -> bool:
    """Allow a same-owner static route beside its dynamic fallback route.

    The compiled graph is deliberately backend-neutral; web routing places
    static write endpoints ahead of a resource detail fallback at runtime.
    Requiring their declaration order here would reject that safe graph even
    though both routes are owned by the same compiled resource.
    """

    return (
        first_owner == second_owner
        and first_path != second_path
        and _has_path_parameter(first_path) != _has_path_parameter(second_path)
    )


@dataclass
class ApplicationBuilder:
    admin_id: str = "admin"
    _routes: list[RouteDefinition] = field(default_factory=list)
    _resources: list[ResourceDefinition] = field(default_factory=list)
    _pages: list[PageDefinition] = field(default_factory=list)
    _actions: list[ActionDefinition] = field(default_factory=list)
    _endpoints: list[EndpointDefinition] = field(default_factory=list)
    _plugin_ids: list[str] = field(default_factory=list)
    _registry: ServiceRegistry = field(default_factory=ServiceRegistry)
    _plugin_conflicts: dict[str, tuple[str, ...]] = field(default_factory=dict)
    _adapters: dict[str, AdapterClaim] = field(default_factory=dict)
    _resource_data_sources: dict[str, DataSource] = field(default_factory=dict)
    _compiled: bool = field(default=False, init=False)
    _install_depth: int = field(default=0, init=False)

    @property
    def routes(self) -> tuple[RouteDefinition, ...]:
        return tuple(self._routes)

    @property
    def resources(self) -> tuple[ResourceDefinition, ...]:
        return tuple(self._resources)

    @property
    def pages(self) -> tuple[PageDefinition, ...]:
        return tuple(self._pages)

    @property
    def actions(self) -> tuple[ActionDefinition, ...]:
        return tuple(self._actions)

    @property
    def endpoints(self) -> tuple[EndpointDefinition, ...]:
        return tuple(self._endpoints)

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

    def add_resource(self, definition: ResourceDefinition, data_source: DataSource) -> None:
        self._check_not_compiled()
        if any(existing.resource_id == definition.resource_id for existing in self._resources):
            raise RakitError(
                code=ErrorCode.CONFIG_DUPLICATE_RESOURCE,
                message=f'Resource "{definition.resource_id}" is already registered.',
                status_code=500,
                details={"resource_id": definition.resource_id},
            )
        self._resources.append(definition)
        self._resource_data_sources[definition.resource_id] = data_source

    def add_page(self, definition: PageDefinition) -> None:
        self._check_not_compiled()
        if any(existing.page_id == definition.page_id for existing in self._pages):
            raise _duplicate_definition("page", definition.page_id)
        self._pages.append(definition)

    def add_action(self, definition: ActionDefinition) -> None:
        self._check_not_compiled()
        if any(existing.action_id == definition.action_id for existing in self._actions):
            raise _duplicate_definition("action", definition.action_id)
        self._actions.append(definition)

    def add_endpoint(self, definition: EndpointDefinition) -> None:
        self._check_not_compiled()
        if any(existing.endpoint_id == definition.endpoint_id for existing in self._endpoints):
            raise _duplicate_definition("endpoint", definition.endpoint_id)
        self._endpoints.append(definition)

    def register_adapter(self, name: str, claim: AdapterClaim) -> None:
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
    pages: list[PageDefinition]
    actions: list[ActionDefinition]
    endpoints: list[EndpointDefinition]
    plugin_ids: list[str]
    plugin_conflicts: dict[str, tuple[str, ...]]
    adapters: dict[str, AdapterClaim]
    resource_data_sources: dict[str, DataSource]
    compiled: bool
    registry: _RegistrySnapshot

    @classmethod
    def capture(cls, builder: "ApplicationBuilder") -> "_InstallSnapshot":
        return cls(
            routes=list(builder._routes),
            resources=list(builder._resources),
            pages=list(builder._pages),
            actions=list(builder._actions),
            endpoints=list(builder._endpoints),
            plugin_ids=list(builder._plugin_ids),
            plugin_conflicts=dict(builder._plugin_conflicts),
            adapters=dict(builder._adapters),
            resource_data_sources=dict(builder._resource_data_sources),
            compiled=builder._compiled,
            registry=builder.registry._snapshot(),
        )

    def restore(self, builder: "ApplicationBuilder") -> None:
        builder._routes[:] = self.routes
        builder._resources[:] = self.resources
        builder._pages[:] = self.pages
        builder._actions[:] = self.actions
        builder._endpoints[:] = self.endpoints
        builder._plugin_ids[:] = self.plugin_ids
        builder._plugin_conflicts.clear()
        builder._plugin_conflicts.update(self.plugin_conflicts)
        builder._adapters.clear()
        builder._adapters.update(self.adapters)
        builder._resource_data_sources.clear()
        builder._resource_data_sources.update(self.resource_data_sources)
        builder._compiled = self.compiled
        builder.registry._restore(self.registry)


@dataclass(frozen=True)
class CompiledApplication:
    routes: tuple[RouteDefinition, ...]
    plugins: tuple[str, ...]
    resources: tuple[ResourceDefinition, ...]
    pages: tuple[PageDefinition, ...] = ()
    actions: tuple[ActionDefinition, ...] = ()
    endpoints: tuple[EndpointDefinition, ...] = ()
    relationships: tuple[CompiledRelationship, ...] = ()
    compiled_pages: tuple[CompiledPageDefinition, ...] = ()
    compiled_actions: tuple[CompiledActionDefinition, ...] = ()
    compiled_endpoints: tuple[CompiledEndpointDefinition, ...] = ()


def _invalid_datasource(resource_id: str, reason: str) -> RakitError:
    return RakitError(
        code=ErrorCode.CONFIG_INVALID_DATASOURCE,
        message=f'Resource "{resource_id}" has an invalid read data source.',
        status_code=500,
        details={"resource_id": resource_id, "reason": reason},
    )


def _duplicate_definition(kind: str, identifier: str) -> RakitError:
    return RakitError(
        code=ErrorCode.CONFIG_INVALID,
        message=f'A {kind} with id "{identifier}" is already registered.',
        status_code=500,
        details={"kind": kind, "identifier": identifier, "reason": "duplicate_definition"},
    )


def _invalid_relationship(resource_id: str, relationship_id: str, reason: str) -> RakitError:
    return RakitError(
        code=ErrorCode.CONFIG_INVALID,
        message="Invalid relationship configuration.",
        status_code=500,
        details={"resource_id": resource_id, "relationship_id": relationship_id, "reason": reason},
    )


def _invalid_policy(resource_id: str, policy: str, reason: str) -> RakitError:
    return RakitError(
        code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,
        message=f'Resource "{resource_id}" has an invalid field policy.',
        status_code=500,
        details={"resource_id": resource_id, "policy": policy, "reason": reason},
    )


def _validate_resource_contract(
    definition: ResourceDefinition,
    data_source: DataSource,
) -> None:
    resource_id = definition.resource_id
    capabilities = getattr(data_source, "capabilities", None)
    if capabilities is None or getattr(capabilities, "read", False) is not True:
        raise _invalid_datasource(resource_id, "read_not_supported")

    for method_name in ("list", "count", "detail"):
        if not callable(getattr(data_source, method_name, None)):
            raise _invalid_datasource(resource_id, f"missing_{method_name}")

    try:
        fields = tuple(data_source.fields)
        identity_fields = tuple(data_source.identity_fields)
    except (AttributeError, TypeError) as exc:
        raise _invalid_datasource(resource_id, "field_metadata_unavailable") from exc

    if not fields:
        raise _invalid_datasource(resource_id, "fields_empty")
    if any(not isinstance(field_name, str) or not field_name for field_name in fields):
        raise _invalid_datasource(resource_id, "fields_invalid")
    if len(set(fields)) != len(fields):
        raise _invalid_datasource(resource_id, "fields_not_unique")
    if not identity_fields:
        raise _invalid_datasource(resource_id, "identity_fields_empty")
    if any(not isinstance(field_name, str) or not field_name for field_name in identity_fields):
        raise _invalid_datasource(resource_id, "identity_fields_invalid")
    if len(set(identity_fields)) != len(identity_fields):
        raise _invalid_datasource(resource_id, "identity_fields_not_unique")
    if not set(identity_fields) <= set(fields):
        raise _invalid_datasource(resource_id, "identity_fields_unknown")

    known_fields = set(fields)
    policy = definition.field_policy
    for policy_name in (
        "list_fields",
        "detail_fields",
        "filter_fields",
        "search_fields",
        "sort_fields",
    ):
        policy_fields = getattr(policy, policy_name)
        if policy_name in {"list_fields", "detail_fields"} and not policy_fields:
            raise _invalid_policy(resource_id, policy_name, "fields_empty")
        if len(set(policy_fields)) != len(policy_fields):
            raise _invalid_policy(resource_id, policy_name, "fields_not_unique")
        if not set(policy_fields) <= known_fields:
            raise _invalid_policy(resource_id, policy_name, "unknown_field")


def _validate_plan05_definitions(
    builder: ApplicationBuilder,
) -> tuple[
    tuple[CompiledRelationship, ...],
    tuple[CompiledPageDefinition, ...],
    tuple[CompiledActionDefinition, ...],
    tuple[CompiledEndpointDefinition, ...],
]:
    resources = {resource.resource_id: resource for resource in builder.resources}
    compiled_relationships: list[CompiledRelationship] = []
    compiled_pages = tuple(
        CompiledPageDefinition(
            definition=page,
            permission=page.permission
            or PermissionRequirement.all_of(f"{builder.admin_id}.pages.{page.page_id}.view"),
        )
        for page in builder.pages
    )
    compiled_actions: list[CompiledActionDefinition] = []
    compiled_endpoints: list[CompiledEndpointDefinition] = []
    for resource in builder.resources:
        seen_relationships: set[str] = set()
        source_data_source = builder._resource_data_sources[resource.resource_id]
        for relationship in resource.relationships:
            if relationship.relationship_id in seen_relationships:
                raise _invalid_relationship(
                    resource.resource_id, relationship.relationship_id, "duplicate_relationship"
                )
            seen_relationships.add(relationship.relationship_id)
            target = resources.get(relationship.target_resource_id)
            if target is None:
                raise _invalid_relationship(
                    resource.resource_id,
                    relationship.relationship_id,
                    "target_resource_not_registered",
                )
            if relationship.destructive_policy.permits_persistent_delete and target is None:
                raise _invalid_relationship(
                    resource.resource_id, relationship.relationship_id, "target_delete_unresolvable"
                )
            if relationship.association_fields and relationship.kind.value != "association_object":
                raise _invalid_relationship(
                    resource.resource_id,
                    relationship.relationship_id,
                    "association_fields_not_allowed",
                )
            if (
                relationship.association_target_resource_id is not None
                and relationship.association_target_resource_id not in resources
            ):
                raise _invalid_relationship(
                    resource.resource_id,
                    relationship.relationship_id,
                    "association_target_resource_not_registered",
                )
            validate_relationship = getattr(source_data_source, "validate_relationship", None)
            if not callable(validate_relationship):
                raise _invalid_relationship(
                    resource.resource_id,
                    relationship.relationship_id,
                    "relationship_metadata_unavailable",
                )
            validate_relationship(
                relationship,
                builder._resource_data_sources[relationship.target_resource_id],
                (
                    builder._resource_data_sources[relationship.association_target_resource_id]
                    if relationship.association_target_resource_id is not None
                    else None
                ),
            )
            mutation_permission = relationship.permission or PermissionRequirement.all_of(
                f"{builder.admin_id}.resources.{resource.resource_id}.update"
            )
            target_delete_permission = (
                PermissionRequirement.all_of(
                    f"{builder.admin_id}.resources.{relationship.target_resource_id}.delete"
                )
                if relationship.destructive_policy.permits_persistent_delete
                else None
            )
            compiled_relationships.append(
                CompiledRelationship(
                    source_resource_id=resource.resource_id,
                    definition=relationship,
                    mutation_permission=mutation_permission,
                    target_delete_permission=target_delete_permission,
                    route_path=(
                        f"{resource.path}/{{identity}}/_relationships/{relationship.relationship_id}"
                    ),
                )
            )

    for action in builder.actions:
        if action.scope.value in {"resource", "record", "bulk"} and (
            action.resource_id is None or action.resource_id not in resources
        ):
            raise _duplicate_definition("action", action.action_id)
        if action.scope.value != "bulk" and action.bulk_policy is not None:
            raise _duplicate_definition("action", action.action_id)
        compiled_actions.append(
            CompiledActionDefinition(
                definition=action,
                permission=action.permission
                or PermissionRequirement.all_of(
                    f"{builder.admin_id}.actions.{action.action_id}.execute"
                ),
            )
        )

    for endpoint in builder.endpoints:
        if not endpoint.methods:
            raise _duplicate_definition("endpoint", endpoint.endpoint_id)
        if len(set(endpoint.methods)) != len(endpoint.methods):
            raise _duplicate_definition("endpoint", endpoint.endpoint_id)
        if endpoint.input_schema is None and endpoint.input_source is not None:
            raise _duplicate_definition("endpoint", endpoint.endpoint_id)
        compiled_endpoints.append(
            CompiledEndpointDefinition(
                definition=endpoint,
                permission=endpoint.permission
                or PermissionRequirement.all_of(
                    f"{builder.admin_id}.endpoints.{endpoint.endpoint_id}.invoke"
                ),
            )
        )
    return (
        tuple(compiled_relationships),
        compiled_pages,
        tuple(compiled_actions),
        tuple(compiled_endpoints),
    )


def _definition_routes(builder: ApplicationBuilder) -> tuple[RouteDefinition, ...]:
    routes: list[RouteDefinition] = []
    resources = {resource.resource_id: resource for resource in builder.resources}
    for page in builder.pages:
        routes.append(
            RouteDefinition(
                route_name=f"page:{page.page_id}",
                methods=("GET", "POST") if page.mutating else ("GET",),
                path=page.path,
                owner_id=page.page_id,
            )
        )
    for endpoint in builder.endpoints:
        routes.append(
            RouteDefinition(
                route_name=f"endpoint:{endpoint.endpoint_id}",
                methods=tuple(method.value for method in endpoint.methods),
                path=endpoint.path,
                owner_id=endpoint.endpoint_id,
            )
        )
    for resource in builder.resources:
        for relationship in resource.relationships:
            routes.append(
                RouteDefinition(
                    route_name=(
                        f"resource:{resource.resource_id}:relationship:{relationship.relationship_id}"
                    ),
                    methods=("GET", "POST"),
                    path=(
                        f"{resource.path}/{{identity}}/_relationships/"
                        f"{relationship.relationship_id}"
                    ),
                    owner_id=resource.resource_id,
                    framework_owned=True,
                )
            )
    for action in builder.actions:
        if action.scope.value == "page":
            continue
        if action.resource_id is None:
            continue
        resource = resources[action.resource_id]
        suffix = "{identity}/_actions" if action.scope.value == "record" else "_actions"
        routes.append(
            RouteDefinition(
                route_name=f"resource:{resource.resource_id}:action:{action.action_id}",
                methods=("GET", "POST") if action.mutating else ("GET",),
                path=f"{resource.path}/{suffix}/{action.action_id}",
                owner_id=resource.resource_id,
                framework_owned=True,
            )
        )
    return tuple(routes)


def compile_application(builder: ApplicationBuilder) -> CompiledApplication:
    if builder._install_depth > 0:
        raise RakitError(
            code=ErrorCode.CONFIG_COMPILE_DURING_PLUGIN_INSTALL,
            message="Cannot compile the application while a plugin's configure() is still running.",
            status_code=500,
        )

    validate_official_package_versions(OFFICIAL_PACKAGE_NAMES)

    for resource in builder.resources:
        data_source = builder._resource_data_sources.get(resource.resource_id)
        if data_source is None:
            raise _invalid_datasource(resource.resource_id, "missing_registration")
        _validate_resource_contract(resource, data_source)

    (
        compiled_relationships,
        compiled_pages,
        compiled_actions,
        compiled_endpoints,
    ) = _validate_plan05_definitions(builder)

    seen: dict[str, list[tuple[str, str, str]]] = {}
    seen_route_names: dict[str, RouteDefinition] = {}
    all_routes = (*builder.routes, *_definition_routes(builder))
    for route in all_routes:
        if not route.framework_owned and any(
            route.path == prefix or route.path.startswith(f"{prefix}/")
            for prefix in RESERVED_PATH_PREFIXES
        ):
            raise RakitError(
                code=ErrorCode.CONFIG_RESERVED_PATH,
                message=f'Route path "{route.path}" is reserved for framework use.',
                status_code=500,
                details={"path": route.path, "route_name": route.route_name},
            )

        if not route.framework_owned and _uses_reserved_resource_segment(route.path):
            raise RakitError(
                code=ErrorCode.CONFIG_RESERVED_PATH,
                message=f'Route path "{route.path}" uses a reserved framework segment.',
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
    return CompiledApplication(
        all_routes,
        builder.plugins,
        builder.resources,
        builder.pages,
        builder.actions,
        builder.endpoints,
        compiled_relationships,
        compiled_pages,
        compiled_actions,
        compiled_endpoints,
    )
