import dataclasses
from collections.abc import Callable
from typing import Any

import pytest

from rakit_core.actions import ActionDefinition, ActionScope
from rakit_core.compiler import (
    ApplicationBuilder,
    OFFICIAL_PACKAGE_NAMES,
    Plugin,
    compile_application,
)
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import (
    EndpointDefinition,
    PageDefinition,
    ResourceDefinition,
    ResourceFieldPolicy,
    RouteDefinition,
)
from rakit_core.endpoints import (
    EndpointAccessPolicy,
    EndpointInputSource,
    EndpointMethod,
    EndpointResponseKind,
)
from rakit_core.errors import RakitError
from rakit_core.pages import PageExecutionResult
from rakit_core.permissions import PermissionRequirement
from rakit_core.query import PageResult, ResourceQuery
from rakit_core.relationships import (
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipDestructivePolicy,
    RelationshipEditMode,
    RelationshipKind,
)


class FakeDataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query: ResourceQuery) -> PageResult:
        del query
        return PageResult(items=[], total=0, page=1, per_page=20)

    async def count(self, query: ResourceQuery) -> int:
        del query
        return 0

    async def detail(self, identity: object) -> object:
        del identity
        return object()


def _resource(resource_id: str, path: str) -> ResourceDefinition:
    return ResourceDefinition(
        resource_id=resource_id,
        label=resource_id.title(),
        path=path,
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "name"),
            detail_fields=("id", "name"),
        ),
    )


def _endpoint(
    *,
    endpoint_id: str,
    path: str,
    methods: tuple[str, ...] = ("GET",),
    public: bool = False,
) -> EndpointDefinition:
    return EndpointDefinition(
        endpoint_id=endpoint_id,
        path=path,
        methods=methods,
        handler=lambda _context: None,
        access=EndpointAccessPolicy.PUBLIC if public else EndpointAccessPolicy.PRIVATE,
    )


def test_builder_rejects_mutation_after_compile() -> None:
    builder = ApplicationBuilder()
    compile_application(builder)

    with pytest.raises(RakitError) as caught:
        builder.add_route(
            RouteDefinition(route_name="late", methods=("GET",), path="/late", owner_id="late")
        )

    assert caught.value.code == "config.already_compiled"


def test_duplicate_route_name_is_rejected() -> None:
    builder = ApplicationBuilder()
    builder.add_route(RouteDefinition(route_name="same", methods=("GET",), path="/a", owner_id="a"))
    builder.add_route(RouteDefinition(route_name="same", methods=("GET",), path="/b", owner_id="b"))

    with pytest.raises(RakitError) as caught:
        compile_application(builder)

    assert caught.value.code == "config.route_name_collision"


def test_package_version_mismatch_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    versions = {
        "rakit": "0.1.0a1",
        "rakit-core": "0.2.0a1",
        "rakit-server": "0.1.0a1",
        "rakit-web": "0.1.0a1",
        "rakit-sqlalchemy": "0.1.0a1",
        "rakit-auth-sqlalchemy": "0.1.0a1",
        "rakit-storage": "0.1.0a1",
        "rakit-storage-local": "0.1.0a1",
        "rakit-server-uvicorn": "0.1.0a1",
    }
    monkeypatch.setattr(
        "rakit_core.compatibility.metadata.version",
        lambda name: versions[name],
    )
    builder = ApplicationBuilder()
    with pytest.raises(RakitError) as caught:
        compile_application(builder)
    assert caught.value.code == "config.package_version_mismatch"


def test_compiles_successfully_with_lockstep_versions() -> None:
    builder = ApplicationBuilder()
    builder.add_route(
        RouteDefinition(
            route_name="app.home",
            methods=("GET",),
            path="/",
            owner_id="home",
        )
    )
    compiled = compile_application(builder)
    assert compiled.routes[0].route_name == "app.home"


def test_builder_install_rolls_back_nested_plugin_failure() -> None:
    builder = ApplicationBuilder()

    @dataclasses.dataclass(frozen=True)
    class ChildPlugin:
        plugin_id: str = "child"

        def configure(self, application: ApplicationBuilder) -> None:
            application.add_route(
                RouteDefinition(
                    route_name="child.route",
                    methods=("GET",),
                    path="/child",
                    owner_id="child",
                )
            )
            raise RuntimeError("boom")

    @dataclasses.dataclass(frozen=True)
    class ParentPlugin:
        plugin_id: str = "parent"

        def configure(self, application: ApplicationBuilder) -> None:
            application.install(ChildPlugin())

    with pytest.raises(RuntimeError, match="boom"):
        builder.install(ParentPlugin())

    assert builder.plugins == ()
    assert builder.routes == ()


def test_builder_install_rolls_back_direct_plugin_failure() -> None:
    builder = ApplicationBuilder()

    @dataclasses.dataclass(frozen=True)
    class BrokenPlugin:
        plugin_id: str = "broken"

        def configure(self, application: ApplicationBuilder) -> None:
            application.add_route(
                RouteDefinition(
                    route_name="broken.route",
                    methods=("GET",),
                    path="/broken",
                    owner_id="broken",
                )
            )
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        builder.install(BrokenPlugin())

    assert builder.plugins == ()
    assert builder.routes == ()


def test_plugin_cannot_leave_registry_frozen() -> None:
    builder = ApplicationBuilder()

    @dataclasses.dataclass(frozen=True)
    class FreezingPlugin:
        plugin_id: str = "freezer"

        def configure(self, application: ApplicationBuilder) -> None:
            application.registry._freeze()

    with pytest.raises(RakitError) as caught:
        builder.install(FreezingPlugin())

    assert caught.value.code == "config.plugin_froze_registry"
    assert builder.plugins == ()
    assert builder.registry._frozen is False


def test_plugin_dependency_is_required_before_install() -> None:
    builder = ApplicationBuilder()

    @dataclasses.dataclass(frozen=True)
    class DependentPlugin:
        plugin_id: str = "dependent"
        depends_on: tuple[str, ...] = ("base",)

        def configure(self, application: ApplicationBuilder) -> None:
            del application

    with pytest.raises(RakitError) as caught:
        builder.install(DependentPlugin())

    assert caught.value.code == "config.missing_plugin_dependency"


def test_plugin_conflict_is_rejected_in_both_directions() -> None:
    @dataclasses.dataclass(frozen=True)
    class PluginA:
        plugin_id: str = "a"
        conflicts_with: tuple[str, ...] = ("b",)

        def configure(self, application: ApplicationBuilder) -> None:
            del application

    @dataclasses.dataclass(frozen=True)
    class PluginB:
        plugin_id: str = "b"

        def configure(self, application: ApplicationBuilder) -> None:
            del application

    builder = ApplicationBuilder()
    builder.install(PluginA())
    with pytest.raises(RakitError) as caught:
        builder.install(PluginB())
    assert caught.value.code == "config.plugin_conflict"

    builder = ApplicationBuilder()
    builder.install(PluginB())
    with pytest.raises(RakitError) as caught:
        builder.install(PluginA())
    assert caught.value.code == "config.plugin_conflict"


def test_official_package_names_are_unique() -> None:
    assert len(OFFICIAL_PACKAGE_NAMES) == len(set(OFFICIAL_PACKAGE_NAMES))


def test_compiler_rejects_route_overlap_for_unrelated_owners() -> None:
    builder = ApplicationBuilder()
    builder.add_route(
        RouteDefinition(
            route_name="orders.dynamic",
            methods=("GET",),
            path="/orders/{identity}",
            owner_id="orders",
        )
    )
    builder.add_route(
        RouteDefinition(
            route_name="other.static",
            methods=("GET",),
            path="/orders/new",
            owner_id="other",
        )
    )

    with pytest.raises(RakitError) as caught:
        compile_application(builder)

    assert caught.value.code == "config.route_collision"


def test_compiler_allows_same_owner_static_route_precedence() -> None:
    builder = ApplicationBuilder()
    builder.add_route(
        RouteDefinition(
            route_name="orders.dynamic",
            methods=("GET",),
            path="/orders/{identity}",
            owner_id="orders",
        )
    )
    builder.add_route(
        RouteDefinition(
            route_name="orders.static",
            methods=("GET",),
            path="/orders/new",
            owner_id="orders",
        )
    )

    compiled = compile_application(builder)
    assert {route.route_name for route in compiled.routes} == {
        "orders.dynamic",
        "orders.static",
    }


def test_reserved_framework_prefix_rejects_application_route() -> None:
    builder = ApplicationBuilder()
    builder.add_route(
        RouteDefinition(
            route_name="app.auth",
            methods=("GET",),
            path="/auth/custom",
            owner_id="app",
        )
    )

    with pytest.raises(RakitError) as caught:
        compile_application(builder)

    assert caught.value.code == "config.reserved_path"


def test_framework_owned_route_can_use_reserved_prefix() -> None:
    builder = ApplicationBuilder()
    builder.add_route(
        RouteDefinition(
            route_name="framework.auth",
            methods=("GET",),
            path="/auth/custom",
            owner_id="framework",
            framework_owned=True,
        )
    )

    compiled = compile_application(builder)
    assert compiled.routes[0].path == "/auth/custom"


def test_resource_reserved_subpath_rejects_application_route() -> None:
    builder = ApplicationBuilder()
    builder.add_resource(_resource("orders", "/orders"), FakeDataSource())
    builder.add_route(
        RouteDefinition(
            route_name="app.action",
            methods=("POST",),
            path="/orders/{identity}/_actions/custom",
            owner_id="app",
        )
    )

    with pytest.raises(RakitError) as caught:
        compile_application(builder)

    assert caught.value.code == "config.reserved_path"


def test_unrelated_reserved_segment_name_is_allowed() -> None:
    builder = ApplicationBuilder()
    builder.add_resource(_resource("orders", "/orders"), FakeDataSource())
    builder.add_route(
        RouteDefinition(
            route_name="reports.actions",
            methods=("GET",),
            path="/reports/_actions",
            owner_id="reports",
        )
    )

    compiled = compile_application(builder)
    assert compiled.routes[-1].path == "/reports/_actions"


def test_resource_relationship_target_must_be_registered() -> None:
    builder = ApplicationBuilder()
    resource = _resource("orders", "/orders")
    resource = dataclasses.replace(
        resource,
        relationships=(
            RelationshipDefinition(
                relationship_id="customer",
                target_resource_id="customers",
                kind=RelationshipKind.TO_ONE,
                cardinality=RelationshipCardinality.TO_ONE,
            ),
        ),
    )
    builder.add_resource(resource, FakeDataSource())

    with pytest.raises(RakitError) as caught:
        compile_application(builder)

    assert caught.value.code == "config.invalid"
    assert caught.value.details["reason"] == "target_resource_not_registered"


def test_public_endpoint_path_cannot_overlap_private_sibling() -> None:
    builder = ApplicationBuilder()
    builder.add_endpoint(_endpoint(endpoint_id="public", path="/api/status", public=True))
    builder.add_endpoint(_endpoint(endpoint_id="private", path="/api/{name}"))

    with pytest.raises(RakitError) as caught:
        compile_application(builder)

    assert caught.value.code == "config.route_collision"


def test_endpoint_method_source_defaults_are_compiled() -> None:
    builder = ApplicationBuilder()
    builder.add_endpoint(
        EndpointDefinition(
            endpoint_id="status",
            path="/api/status",
            methods=("GET",),
            handler=lambda _context: None,
        )
    )
    compiled = compile_application(builder)
    endpoint = compiled.compiled_endpoints[0]

    assert endpoint.methods == (EndpointMethod.GET,)
    assert endpoint.input_source is EndpointInputSource.QUERY
    assert endpoint.response_kind is EndpointResponseKind.JSON


def test_post_endpoint_defaults_to_json_and_requires_private_access() -> None:
    builder = ApplicationBuilder()
    builder.add_endpoint(
        EndpointDefinition(
            endpoint_id="update",
            path="/api/update",
            methods=("POST",),
            handler=lambda _context: None,
        )
    )
    compiled = compile_application(builder)
    endpoint = compiled.compiled_endpoints[0]

    assert endpoint.methods == (EndpointMethod.POST,)
    assert endpoint.input_source is EndpointInputSource.JSON
    assert endpoint.access is EndpointAccessPolicy.PRIVATE


def test_public_post_endpoint_is_rejected() -> None:
    builder = ApplicationBuilder()
    builder.add_endpoint(
        EndpointDefinition(
            endpoint_id="public-write",
            path="/api/public-write",
            methods=("POST",),
            handler=lambda _context: None,
            access=EndpointAccessPolicy.PUBLIC,
        )
    )

    with pytest.raises(RakitError) as caught:
        compile_application(builder)

    assert caught.value.details["reason"] == "public_post_not_supported"


def test_endpoint_cannot_mix_get_and_post() -> None:
    builder = ApplicationBuilder()
    builder.add_endpoint(
        EndpointDefinition(
            endpoint_id="mixed",
            path="/api/mixed",
            methods=("GET", "POST"),
            handler=lambda _context: None,
        )
    )

    with pytest.raises(RakitError) as caught:
        compile_application(builder)

    assert caught.value.details["reason"] == "multiple_methods_not_supported"


def test_endpoint_parameterized_path_is_rejected() -> None:
    builder = ApplicationBuilder()
    builder.add_endpoint(
        EndpointDefinition(
            endpoint_id="item",
            path="/api/items/{identity}",
            methods=("GET",),
            handler=lambda _context: None,
        )
    )

    with pytest.raises(RakitError) as caught:
        compile_application(builder)

    assert caught.value.details["reason"] == "parameterized_path_not_supported"


def test_endpoint_form_source_is_explicit() -> None:
    builder = ApplicationBuilder()
    builder.add_endpoint(
        EndpointDefinition(
            endpoint_id="form",
            path="/api/form",
            methods=("POST",),
            handler=lambda _context: None,
            input_source=EndpointInputSource.FORM,
        )
    )
    compiled = compile_application(builder)

    assert compiled.compiled_endpoints[0].input_source is EndpointInputSource.FORM


def test_endpoint_advanced_response_is_rejected() -> None:
    builder = ApplicationBuilder()
    builder.add_endpoint(
        EndpointDefinition(
            endpoint_id="advanced",
            path="/api/advanced",
            methods=("GET",),
            handler=lambda _context: None,
            response_kind=EndpointResponseKind.ADVANCED,
        )
    )

    with pytest.raises(RakitError) as caught:
        compile_application(builder)

    assert caught.value.details["reason"] == "advanced_response_not_supported"


def test_page_action_owner_must_exist() -> None:
    builder = ApplicationBuilder()
    builder.add_action(
        ActionDefinition(
            action_id="refresh",
            label="Refresh",
            scope=ActionScope.PAGE,
            page_id="dashboard",
            handler=lambda _context: None,
        )
    )

    with pytest.raises(RakitError) as caught:
        compile_application(builder)

    assert caught.value.details["reason"] == "page_owner_not_registered"


def test_page_action_owner_compiles_when_page_exists() -> None:
    builder = ApplicationBuilder()
    builder.add_page(
        PageDefinition(
            page_id="dashboard",
            label="Dashboard",
            path="/dashboard",
            handler=lambda _context: PageExecutionResult(content="ok"),
        )
    )
    builder.add_action(
        ActionDefinition(
            action_id="refresh",
            label="Refresh",
            scope=ActionScope.PAGE,
            page_id="dashboard",
            handler=lambda _context: None,
        )
    )

    compiled = compile_application(builder)
    assert compiled.compiled_actions[0].definition.page_id == "dashboard"
