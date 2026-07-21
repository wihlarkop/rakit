import pytest
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.definitions import RouteDefinition
from rakit_core.di import ServiceScope
from rakit_core.errors import RakitError


def test_duplicate_method_and_path_fail() -> None:
    builder = ApplicationBuilder()
    builder.add_route(
        RouteDefinition(
            route_name="rakit.operations.pages.home",
            methods=("GET",),
            path="/",
            owner_id="home",
        )
    )
    builder.add_route(
        RouteDefinition(
            route_name="rakit.operations.pages.other",
            methods=("GET",),
            path="/",
            owner_id="other",
        )
    )
    with pytest.raises(RakitError) as caught:
        compile_application(builder)
    assert caught.value.code == "config.route_collision"


class _PluginWithMissingDependency:
    plugin_id = "reports"
    depends_on = ("auth",)

    def configure(self, builder: ApplicationBuilder) -> None:
        pass


def test_missing_plugin_dependency_fails() -> None:
    builder = ApplicationBuilder()
    with pytest.raises(RakitError) as caught:
        builder.install(_PluginWithMissingDependency())
    assert caught.value.code == "config.missing_plugin_dependency"


class _PluginA:
    plugin_id = "a"

    def configure(self, builder: ApplicationBuilder) -> None:
        pass


class _PluginBConflictsWithA:
    plugin_id = "b"
    conflicts_with = ("a",)

    def configure(self, builder: ApplicationBuilder) -> None:
        pass


def test_plugin_conflict_fails() -> None:
    builder = ApplicationBuilder()
    builder.install(_PluginA())
    with pytest.raises(RakitError) as caught:
        builder.install(_PluginBConflictsWithA())
    assert caught.value.code == "config.plugin_conflict"


class _ServiceA:
    pass


def test_duplicate_di_registration_fails() -> None:
    builder = ApplicationBuilder()
    builder.registry.add_value(_ServiceA, _ServiceA(), scope=ServiceScope.APPLICATION)
    with pytest.raises(RakitError) as caught:
        builder.registry.add_value(_ServiceA, _ServiceA(), scope=ServiceScope.APPLICATION)
    assert caught.value.code == "di.duplicate_registration"


def test_reserved_path_fails() -> None:
    builder = ApplicationBuilder()
    builder.add_route(
        RouteDefinition(
            route_name="app.custom",
            methods=("GET",),
            path="/_system/custom",
            owner_id="custom",
        )
    )
    with pytest.raises(RakitError) as caught:
        compile_application(builder)
    assert caught.value.code == "config.reserved_path"


def test_duplicate_route_name_fails() -> None:
    builder = ApplicationBuilder()
    builder.add_route(
        RouteDefinition(
            route_name="app.duplicate",
            methods=("GET",),
            path="/one",
            owner_id="one",
        )
    )
    builder.add_route(
        RouteDefinition(
            route_name="app.duplicate",
            methods=("POST",),
            path="/two",
            owner_id="two",
        )
    )
    with pytest.raises(RakitError) as caught:
        compile_application(builder)
    assert caught.value.code == "config.route_name_collision"


def test_package_version_mismatch_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    versions = {
        "rakit": "0.1.0a1",
        "rakit-core": "0.2.0a1",
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


def test_add_route_after_successful_compile_fails() -> None:
    builder = ApplicationBuilder()
    builder.add_route(
        RouteDefinition(
            route_name="app.home",
            methods=("GET",),
            path="/",
            owner_id="home",
        )
    )
    compile_application(builder)
    with pytest.raises(RakitError) as caught:
        builder.add_route(
            RouteDefinition(
                route_name="app.other",
                methods=("GET",),
                path="/other",
                owner_id="other",
            )
        )
    assert caught.value.code == "config.already_compiled"


def test_install_after_successful_compile_fails() -> None:
    builder = ApplicationBuilder()
    compile_application(builder)
    with pytest.raises(RakitError) as caught:
        builder.install(_PluginA())
    assert caught.value.code == "config.already_compiled"


def test_registry_mutation_after_successful_compile_fails() -> None:
    builder = ApplicationBuilder()
    compile_application(builder)
    with pytest.raises(RakitError) as caught:
        builder.registry.add_value(_ServiceA, _ServiceA(), scope=ServiceScope.APPLICATION)
    assert caught.value.code == "di.registry_frozen"

    with pytest.raises(RakitError) as caught_factory:
        builder.registry.add_factory(
            _ServiceA, lambda _: _ServiceA(), scope=ServiceScope.APPLICATION
        )
    assert caught_factory.value.code == "di.registry_frozen"


def test_failed_compile_leaves_builder_editable() -> None:
    builder = ApplicationBuilder()
    builder.add_route(
        RouteDefinition(
            route_name="app.custom",
            methods=("GET",),
            path="/_system/custom",
            owner_id="custom",
        )
    )
    with pytest.raises(RakitError) as caught:
        compile_application(builder)
    assert caught.value.code == "config.reserved_path"

    builder.add_route(
        RouteDefinition(
            route_name="app.valid",
            methods=("GET",),
            path="/valid",
            owner_id="valid",
        )
    )
    assert any(route.route_name == "app.valid" for route in builder.routes)


def test_routes_and_plugins_are_read_only_tuples() -> None:
    builder = ApplicationBuilder()
    assert isinstance(builder.routes, tuple)
    assert isinstance(builder.plugins, tuple)
    builder.add_route(
        RouteDefinition(
            route_name="app.home",
            methods=("GET",),
            path="/",
            owner_id="home",
        )
    )
    builder.install(_PluginA())
    assert isinstance(builder.routes, tuple)
    assert isinstance(builder.plugins, tuple)
    compile_application(builder)
    assert isinstance(builder.routes, tuple)
    assert isinstance(builder.plugins, tuple)
