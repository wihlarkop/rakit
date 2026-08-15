"""PLAN 05 action-route compiler contract through Task 5.

The compiler owns action route metadata (path, methods, stable route name,
owner). Every executable PAGE / RESOURCE / RECORD / BULK action exposes
GET + POST; ``mutating`` is execution/transaction semantics, not an
HTTP-method switch. Task 5 extends the Task 4 contract by making BULK routes
compiler-owned too.
"""

from rakit_core.actions import (
    ActionDefinition,
    ActionScope,
    ActionSuccess,
    DomainActionExecutor,
)
from rakit_core.compiler import ApplicationBuilder, CompiledApplication, compile_application
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import (
    CompiledActionDefinition,
    PageDefinition,
    ResourceDefinition,
    ResourceFieldPolicy,
    RouteDefinition,
)
from rakit_core.identity import RecordIdentity
from rakit_core.permissions import PermissionRequirement
from rakit_core.query import PageResult, ResourceQuery


class _DataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query: ResourceQuery) -> PageResult:  # pragma: no cover
        raise AssertionError

    async def count(self, query: ResourceQuery) -> int:  # pragma: no cover
        raise AssertionError

    async def detail(self, identity: RecordIdentity) -> object:  # pragma: no cover
        raise AssertionError


def _resource(resource_id: str, path: str) -> ResourceDefinition:
    return ResourceDefinition(
        resource_id=resource_id,
        path=path,
        label=resource_id.title(),
        singular_label=resource_id.title(),
        field_policy=ResourceFieldPolicy(list_fields=("id",), detail_fields=("id",)),
    )


def _executor() -> DomainActionExecutor:
    return DomainActionExecutor(lambda _context: ActionSuccess())


def _builder(admin_id: str = "ops") -> ApplicationBuilder:
    builder = ApplicationBuilder(admin_id=admin_id)
    builder.add_resource(_resource("orders", "/orders"), _DataSource())
    builder.add_page(PageDefinition(page_id="report", path="/reports", label="Report"))
    builder.add_action(
        ActionDefinition(
            action_id="export",
            label="Export orders",
            scope=ActionScope.RESOURCE,
            resource_id="orders",
            permission=PermissionRequirement.all_of("ops.actions.export.execute"),
            executor=_executor(),
        )
    )
    builder.add_action(
        ActionDefinition(
            action_id="approve",
            label="Approve order",
            scope=ActionScope.RECORD,
            resource_id="orders",
            executor=_executor(),
        )
    )
    builder.add_action(
        ActionDefinition(
            action_id="refresh",
            label="Refresh",
            scope=ActionScope.PAGE,
            page_id="report",
            permission=PermissionRequirement.all_of("ops.actions.refresh.execute"),
            executor=_executor(),
        )
    )
    builder.add_action(
        ActionDefinition(
            action_id="bulk_archive",
            label="Bulk archive",
            scope=ActionScope.BULK,
            resource_id="orders",
            executor=_executor(),
        )
    )
    return builder


def _compiled() -> tuple[ApplicationBuilder, CompiledApplication]:
    builder = _builder()
    return builder, compile_application(builder)


def test_resource_record_page_and_bulk_action_paths_are_canonical() -> None:
    builder, compiled = _compiled()
    assert builder.resources[0].path == "/orders"

    by_name = {route.route_name: route for route in compiled.routes}
    assert by_name["resource:orders:action:export"].path == "/orders/_actions/export"
    assert by_name["resource:orders:action:approve"].path == "/orders/{identity}/_actions/approve"
    assert by_name["page:report:action:refresh"].path == "/reports/_actions/refresh"
    assert by_name["resource:orders:action:bulk_archive"].path == ("/orders/_actions/bulk_archive")


def test_every_executable_action_route_declares_get_and_post() -> None:
    _, compiled = _compiled()
    action_routes = [route for route in compiled.routes if ":action:" in route.route_name]
    assert len(action_routes) == 4
    assert all(route.methods == ("GET", "POST") for route in action_routes)


def test_route_names_are_owner_aware_and_stable() -> None:
    _, compiled = _compiled()
    by_name = {route.route_name: route for route in compiled.routes}
    assert set(by_name) >= {
        "resource:orders:action:export",
        "resource:orders:action:approve",
        "resource:orders:action:bulk_archive",
        "page:report:action:refresh",
    }
    assert by_name["resource:orders:action:export"].owner_id == "orders"
    assert by_name["resource:orders:action:bulk_archive"].owner_id == "orders"
    assert by_name["page:report:action:refresh"].owner_id == "report"


def test_explicit_permission_survives_compilation() -> None:
    _, compiled = _compiled()
    by_id = {
        compiled_action.definition.action_id: compiled_action
        for compiled_action in compiled.compiled_actions
    }
    assert by_id["export"].permission == PermissionRequirement.all_of("ops.actions.export.execute")
    assert by_id["refresh"].permission == PermissionRequirement.all_of(
        "ops.actions.refresh.execute"
    )


def test_omitted_permission_receives_generated_default() -> None:
    _, compiled = _compiled()
    by_id = {
        compiled_action.definition.action_id: compiled_action
        for compiled_action in compiled.compiled_actions
    }
    assert by_id["approve"].permission == PermissionRequirement.all_of(
        "ops.actions.approve.execute"
    )
    assert by_id["bulk_archive"].permission == PermissionRequirement.all_of(
        "ops.actions.bulk_archive.execute"
    )


def test_bulk_actions_compile_with_routes_and_pairs() -> None:
    _, compiled = _compiled()
    bulk = next(
        compiled_action
        for compiled_action in compiled.compiled_actions
        if compiled_action.definition.action_id == "bulk_archive"
    )
    route = next(
        route
        for route in compiled.routes
        if route.route_name == "resource:orders:action:bulk_archive"
    )

    assert bulk.definition.scope is ActionScope.BULK
    assert route.path == "/orders/_actions/bulk_archive"
    assert (route, bulk) in compiled.action_routes


def test_action_routes_pair_every_compiled_action() -> None:
    _, compiled = _compiled()
    paired = {compiled_action.definition.action_id for _, compiled_action in compiled.action_routes}
    compiled_ids = {
        compiled_action.definition.action_id for compiled_action in compiled.compiled_actions
    }
    assert paired == compiled_ids == {"export", "approve", "refresh", "bulk_archive"}

    for route, compiled_action in compiled.action_routes:
        assert route in compiled.routes
        assert isinstance(compiled_action, CompiledActionDefinition)
        assert isinstance(route, RouteDefinition)


def test_action_routes_are_frozen_compiler_metadata() -> None:
    _, compiled = _compiled()
    for route, compiled_action in compiled.action_routes:
        assert route.framework_owned is False
        assert route.methods == ("GET", "POST")
        assert compiled_action.permission is not None


def test_root_page_owner_action_path_is_canonical() -> None:
    builder = ApplicationBuilder(admin_id="ops")
    builder.add_page(PageDefinition(page_id="root", path="/", label="Root"))
    builder.add_action(
        ActionDefinition(
            action_id="refresh",
            label="Refresh",
            scope=ActionScope.PAGE,
            page_id="root",
            executor=_executor(),
        )
    )

    compiled = compile_application(builder)

    by_name = {route.route_name: route for route in compiled.routes}
    assert by_name["page:root:action:refresh"].path == "/_actions/refresh"
    assert all("//" not in route.path for route in compiled.routes)
    assert compiled.action_routes[0][0].path == "/_actions/refresh"


def test_root_resource_owner_action_paths_are_canonical_including_bulk() -> None:
    builder = ApplicationBuilder(admin_id="ops")
    builder.add_resource(_resource("orders", "/"), _DataSource())
    builder.add_action(
        ActionDefinition(
            action_id="export",
            label="Export",
            scope=ActionScope.RESOURCE,
            resource_id="orders",
            executor=_executor(),
        )
    )
    builder.add_action(
        ActionDefinition(
            action_id="approve",
            label="Approve",
            scope=ActionScope.RECORD,
            resource_id="orders",
            executor=_executor(),
        )
    )
    builder.add_action(
        ActionDefinition(
            action_id="bulk_archive",
            label="Bulk archive",
            scope=ActionScope.BULK,
            resource_id="orders",
            executor=_executor(),
        )
    )

    compiled = compile_application(builder)

    by_name = {route.route_name: route for route in compiled.routes}
    assert by_name["resource:orders:action:export"].path == "/_actions/export"
    assert by_name["resource:orders:action:approve"].path == "/{identity}/_actions/approve"
    assert by_name["resource:orders:action:bulk_archive"].path == "/_actions/bulk_archive"
    assert all("//" not in route.path for route in compiled.routes)
    paired = {compiled_action.definition.action_id for _, compiled_action in compiled.action_routes}
    assert paired == {"export", "approve", "bulk_archive"}


def test_normal_non_root_action_paths_are_byte_for_byte_unchanged() -> None:
    _, compiled = _compiled()
    by_name = {route.route_name: route for route in compiled.routes}
    assert by_name["resource:orders:action:export"].path == "/orders/_actions/export"
    assert by_name["resource:orders:action:approve"].path == "/orders/{identity}/_actions/approve"
    assert by_name["resource:orders:action:bulk_archive"].path == ("/orders/_actions/bulk_archive")
    assert by_name["page:report:action:refresh"].path == "/reports/_actions/refresh"
