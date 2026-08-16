import contextlib

import pytest
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.datasource import DataSource
from rakit_core.definitions import RouteDefinition
from rakit_core.di import ServiceRegistry, ServiceScope
from rakit_core.errors import ErrorCode, RakitError


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


@pytest.mark.parametrize(
    "paths",
    (
        ("/users/{identity}", "/users/settings"),
        ("/users/settings", "/users/{identity}"),
        ("/teams/{team_id}/users", "/teams/{slug}/users"),
    ),
)
def test_runtime_equivalent_path_patterns_fail_in_either_order(
    paths: tuple[str, str],
) -> None:
    builder = ApplicationBuilder()
    for index, path in enumerate(paths):
        builder.add_route(
            RouteDefinition(
                route_name=f"app.route_{index}",
                methods=("GET",),
                path=path,
                owner_id=f"owner_{index}",
            )
        )

    with pytest.raises(RakitError) as caught:
        compile_application(builder)

    assert caught.value.code == ErrorCode.CONFIG_ROUTE_COLLISION
    assert caught.value.details == {"first": "app.route_0", "second": "app.route_1"}


def test_static_paths_with_different_segments_do_not_collide() -> None:
    builder = ApplicationBuilder()
    for index, path in enumerate(("/users/settings", "/users/profile")):
        builder.add_route(
            RouteDefinition(
                route_name=f"app.route_{index}",
                methods=("GET",),
                path=path,
                owner_id=f"owner_{index}",
            )
        )

    compiled = compile_application(builder)

    assert tuple(route.path for route in compiled.routes) == (
        "/users/settings",
        "/users/profile",
    )


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


class _ServiceB:
    pass


class _PluginThatFailsMidConfigure:
    plugin_id = "flaky"

    def configure(self, builder: ApplicationBuilder) -> None:
        builder.add_route(
            RouteDefinition(
                route_name="app.flaky",
                methods=("GET",),
                path="/flaky",
                owner_id="flaky",
            )
        )
        builder.registry.add_factory(
            _ServiceB, lambda _: _ServiceB(), scope=ServiceScope.APPLICATION
        )
        raise RuntimeError("boom")


class _PluginThatSucceeds:
    plugin_id = "flaky"

    def configure(self, builder: ApplicationBuilder) -> None:
        builder.add_route(
            RouteDefinition(
                route_name="app.flaky",
                methods=("GET",),
                path="/flaky",
                owner_id="flaky",
            )
        )
        builder.registry.add_factory(
            _ServiceB, lambda _: _ServiceB(), scope=ServiceScope.APPLICATION
        )


def test_failed_install_rolls_back_routes_plugin_ids_conflicts_and_providers() -> None:
    builder = ApplicationBuilder()
    plugin = _PluginThatFailsMidConfigure()

    with pytest.raises(RuntimeError, match="boom"):
        builder.install(plugin)

    assert builder.routes == ()
    assert builder.plugins == ()
    assert plugin.plugin_id not in builder._plugin_conflicts
    assert all(key.service_type is not _ServiceB for key in builder.registry.providers)

    # Proves the registration was genuinely removed, not just hidden from view.
    builder.registry.add_factory(_ServiceB, lambda _: _ServiceB(), scope=ServiceScope.APPLICATION)


def test_corrected_plugin_can_be_installed_after_rollback() -> None:
    builder = ApplicationBuilder()
    failing_plugin = _PluginThatFailsMidConfigure()

    with pytest.raises(RuntimeError, match="boom"):
        builder.install(failing_plugin)

    corrected_plugin = _PluginThatSucceeds()
    builder.install(corrected_plugin)

    assert builder.plugins == ("flaky",)
    assert len(builder.routes) == 1
    assert builder.routes[0].route_name == "app.flaky"
    assert any(key.service_type is _ServiceB for key in builder.registry.providers)


def test_successful_install_survives_compile_with_rollback_machinery_in_place() -> None:
    builder = ApplicationBuilder()
    builder.install(_PluginThatSucceeds())

    compiled = compile_application(builder)

    assert any(route.route_name == "app.flaky" for route in compiled.routes)
    assert "flaky" in compiled.plugins

    with pytest.raises(RakitError) as caught:
        builder.registry.add_factory(
            _ServiceA, lambda _: _ServiceA(), scope=ServiceScope.APPLICATION
        )
    assert caught.value.code == "di.registry_frozen"


class _PluginThatRecompilesRecursively:
    plugin_id = "recompiler"

    def configure(self, builder: ApplicationBuilder) -> None:
        builder.add_route(
            RouteDefinition(
                route_name="app.recompiler",
                methods=("GET",),
                path="/recompiler",
                owner_id="recompiler",
            )
        )
        builder.registry.add_factory(
            _ServiceB, lambda _: _ServiceB(), scope=ServiceScope.APPLICATION
        )
        compile_application(builder)


def test_recursive_compile_during_configure_is_rejected_and_rolled_back() -> None:
    builder = ApplicationBuilder()
    plugin = _PluginThatRecompilesRecursively()

    with pytest.raises(RakitError) as caught:
        builder.install(plugin)
    assert caught.value.code == "config.compile_during_plugin_install"

    assert builder._compiled is False
    assert builder.routes == ()
    assert builder.plugins == ()
    assert plugin.plugin_id not in builder._plugin_conflicts
    assert all(key.service_type is not _ServiceB for key in builder.registry.providers)

    # Proves the registration was genuinely removed, not just hidden from view.
    builder.registry.add_factory(_ServiceB, lambda _: _ServiceB(), scope=ServiceScope.APPLICATION)

    corrected_plugin = _PluginThatSucceeds()
    with pytest.raises(RakitError) as duplicate_caught:
        builder.install(corrected_plugin)
    assert duplicate_caught.value.code == "di.duplicate_registration"


def test_recursive_compile_during_configure_allows_clean_reinstall_afterward() -> None:
    builder = ApplicationBuilder()
    plugin = _PluginThatRecompilesRecursively()

    with pytest.raises(RakitError) as caught:
        builder.install(plugin)
    assert caught.value.code == "config.compile_during_plugin_install"

    corrected_plugin = _PluginThatSucceeds()
    builder.install(corrected_plugin)
    assert builder.plugins == ("flaky",)

    compiled = compile_application(builder)
    assert "flaky" in compiled.plugins


class _PluginThatFreezesRegistryThenFails:
    plugin_id = "freezer"

    def configure(self, builder: ApplicationBuilder) -> None:
        builder.add_route(
            RouteDefinition(
                route_name="app.freezer",
                methods=("GET",),
                path="/freezer",
                owner_id="freezer",
            )
        )
        builder.registry.add_factory(
            _ServiceB, lambda _: _ServiceB(), scope=ServiceScope.APPLICATION
        )
        builder.registry._freeze()
        raise RuntimeError("freezer boom")


class _ServiceProbe:
    pass


def test_direct_freeze_during_configure_is_rolled_back() -> None:
    builder = ApplicationBuilder()
    plugin = _PluginThatFreezesRegistryThenFails()

    with pytest.raises(RuntimeError, match="freezer boom"):
        builder.install(plugin)

    assert builder.plugins == ()
    assert builder.routes == ()
    assert plugin.plugin_id not in builder._plugin_conflicts

    # _frozen must have been rolled back to False, otherwise this raises di.registry_frozen.
    builder.registry.add_factory(
        _ServiceProbe, lambda _: _ServiceProbe(), scope=ServiceScope.APPLICATION
    )

    corrected_plugin = _PluginThatSucceeds()
    builder.install(corrected_plugin)
    assert builder.plugins == ("flaky",)

    compiled = compile_application(builder)
    assert "flaky" in compiled.plugins


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


# --- Finding 1: registry field is read-only -------------------------------


def test_registry_rebinding_raises_attribute_error() -> None:
    builder = ApplicationBuilder()
    with pytest.raises(AttributeError):
        builder.registry = ServiceRegistry()  # type: ignore


def test_registry_rebinding_raises_attribute_error_after_compile() -> None:
    builder = ApplicationBuilder()
    compile_application(builder)
    with pytest.raises(AttributeError):
        builder.registry = ServiceRegistry()  # type: ignore


# --- Finding 2: reentrant-safe install depth counter -----------------------


class _InnerPluginOk:
    plugin_id = "inner-ok"

    def configure(self, builder: ApplicationBuilder) -> None:
        builder.add_route(
            RouteDefinition(
                route_name="app.inner",
                methods=("GET",),
                path="/inner",
                owner_id="inner",
            )
        )


class _OuterPluginRecompilesAfterInnerInstall:
    plugin_id = "outer-recompiles"

    def configure(self, builder: ApplicationBuilder) -> None:
        builder.install(_InnerPluginOk())
        compile_application(builder)


def test_outer_install_guard_survives_inner_install_completion() -> None:
    builder = ApplicationBuilder()

    with pytest.raises(RakitError) as caught:
        builder.install(_OuterPluginRecompilesAfterInnerInstall())
    assert caught.value.code == "config.compile_during_plugin_install"

    # Outer's own transaction (including the inner plugin it installed) is
    # fully rolled back too.
    assert builder.plugins == ()
    assert builder.routes == ()
    assert builder._install_depth == 0


def test_inner_install_completion_does_not_clear_outer_install_depth() -> None:
    builder = ApplicationBuilder()
    observed: dict[str, int] = {}

    class _Outer:
        plugin_id = "outer-observe"

        def configure(self, builder: ApplicationBuilder) -> None:
            builder.install(_InnerPluginOk())
            observed["depth_after_inner"] = builder._install_depth

    builder.install(_Outer())
    assert observed["depth_after_inner"] >= 1
    assert builder._install_depth == 0


class _ServiceNested:
    pass


def test_nested_install_failure_isolates_outer_state() -> None:
    builder = ApplicationBuilder()

    class _InnerFails:
        plugin_id = "inner-fail"

        def configure(self, builder: ApplicationBuilder) -> None:
            builder.add_route(
                RouteDefinition(
                    route_name="app.inner_fail",
                    methods=("GET",),
                    path="/inner-fail",
                    owner_id="inner_fail",
                )
            )
            builder.registry.add_factory(
                _ServiceNested, lambda _: _ServiceNested(), scope=ServiceScope.APPLICATION
            )
            raise RuntimeError("inner boom")

    class _OuterCatchesInnerFailure:
        plugin_id = "outer-catches"

        def configure(self, builder: ApplicationBuilder) -> None:
            builder.add_route(
                RouteDefinition(
                    route_name="app.outer",
                    methods=("GET",),
                    path="/outer",
                    owner_id="outer",
                )
            )
            with contextlib.suppress(RuntimeError):
                builder.install(_InnerFails())

    builder.install(_OuterCatchesInnerFailure())

    assert builder.plugins == ("outer-catches",)
    assert [route.route_name for route in builder.routes] == ["app.outer"]
    assert all(key.service_type is not _ServiceNested for key in builder.registry.providers)
    assert builder._install_depth == 0


def test_install_depth_returns_to_zero_after_normal_install() -> None:
    builder = ApplicationBuilder()
    builder.install(_PluginA())
    assert builder._install_depth == 0


def test_install_depth_returns_to_zero_after_regular_exception() -> None:
    builder = ApplicationBuilder()
    with pytest.raises(RuntimeError, match="boom"):
        builder.install(_PluginThatFailsMidConfigure())
    assert builder._install_depth == 0


class _WeirdBaseException(BaseException):
    pass


class _PluginRaisesNonExceptionBaseException:
    plugin_id = "weird"

    def configure(self, builder: ApplicationBuilder) -> None:
        raise _WeirdBaseException("weird")


def test_install_depth_returns_to_zero_after_non_exception_base_exception() -> None:
    builder = ApplicationBuilder()
    with pytest.raises(_WeirdBaseException):
        builder.install(_PluginRaisesNonExceptionBaseException())
    assert builder._install_depth == 0


def test_corrected_plugin_installable_after_nested_failure_and_compiles() -> None:
    builder = ApplicationBuilder()

    class _InnerFails:
        plugin_id = "inner-fail"

        def configure(self, builder: ApplicationBuilder) -> None:
            raise RuntimeError("inner boom")

    class _OuterCatchesInnerFailure:
        plugin_id = "outer-catches"

        def configure(self, builder: ApplicationBuilder) -> None:
            with contextlib.suppress(RuntimeError):
                builder.install(_InnerFails())

    builder.install(_OuterCatchesInnerFailure())

    corrected_inner = _InnerPluginOk()
    builder.install(corrected_inner)
    assert "inner-ok" in builder.plugins

    compiled = compile_application(builder)
    assert "inner-ok" in compiled.plugins
    assert "outer-catches" in compiled.plugins


# --- Finding 3: plugins cannot freeze the registry without raising ---------


class _PluginThatFreezesAndReturnsNormally:
    plugin_id = "sneaky-freezer"

    def configure(self, builder: ApplicationBuilder) -> None:
        builder.add_route(
            RouteDefinition(
                route_name="app.sneaky",
                methods=("GET",),
                path="/sneaky",
                owner_id="sneaky",
            )
        )
        builder.registry._freeze()


def test_plugin_that_freezes_registry_and_returns_normally_is_rejected() -> None:
    builder = ApplicationBuilder()

    with pytest.raises(RakitError) as caught:
        builder.install(_PluginThatFreezesAndReturnsNormally())
    assert caught.value.code == "config.plugin_froze_registry"


def test_after_rejected_freezing_plugin_registry_and_builder_remain_usable() -> None:
    builder = ApplicationBuilder()

    with pytest.raises(RakitError) as caught:
        builder.install(_PluginThatFreezesAndReturnsNormally())
    assert caught.value.code == "config.plugin_froze_registry"

    assert "sneaky-freezer" not in builder.plugins
    assert builder.routes == ()

    # Registry is unfrozen again; a new registration succeeds.
    builder.registry.add_factory(
        _ServiceNested, lambda _: _ServiceNested(), scope=ServiceScope.APPLICATION
    )

    # Builder itself is not considered compiled, so further calls are fine.
    builder._check_not_compiled()

    # A different, well-behaved plugin can still install afterward.
    builder.install(_PluginThatSucceeds())
    assert "flaky" in builder.plugins


def test_normal_compile_still_freezes_registry() -> None:
    builder = ApplicationBuilder()
    builder.install(_PluginThatSucceeds())
    compile_application(builder)
    assert builder.registry._frozen is True


def test_post_compile_mutation_still_raises_registry_frozen() -> None:
    builder = ApplicationBuilder()
    compile_application(builder)
    with pytest.raises(RakitError) as caught:
        builder.registry.add_value(_ServiceA, _ServiceA(), scope=ServiceScope.APPLICATION)
    assert caught.value.code == "di.registry_frozen"


# --- register_adapter --------------------------------------------------


def test_register_adapter_stores_claim_callback() -> None:
    builder = ApplicationBuilder()

    def claim(model: type, policy: object) -> DataSource | None:
        return None

    builder.register_adapter("sqlalchemy", claim)
    assert builder._adapters["sqlalchemy"] is claim


def test_register_duplicate_adapter_fails() -> None:
    builder = ApplicationBuilder()
    builder.register_adapter("sqlalchemy", lambda model, policy: None)
    with pytest.raises(RakitError) as caught:
        builder.register_adapter("sqlalchemy", lambda model, policy: None)
    assert caught.value.code == "config.duplicate_adapter"


def test_register_adapter_after_successful_compile_fails() -> None:
    builder = ApplicationBuilder()
    compile_application(builder)
    with pytest.raises(RakitError) as caught:
        builder.register_adapter("sqlalchemy", lambda model, policy: None)
    assert caught.value.code == "config.already_compiled"


class _PluginRegistersAdapterThenFails:
    plugin_id = "adapter-flaky"

    def configure(self, builder: ApplicationBuilder) -> None:
        builder.register_adapter("sqlalchemy", lambda model, policy: None)
        raise RuntimeError("adapter boom")


def test_failed_install_rolls_back_registered_adapters() -> None:
    builder = ApplicationBuilder()
    plugin = _PluginRegistersAdapterThenFails()

    with pytest.raises(RuntimeError, match="adapter boom"):
        builder.install(plugin)

    assert "sqlalchemy" not in builder._adapters

    # Proves the registration was genuinely removed, not just hidden from view.
    builder.register_adapter("sqlalchemy", lambda model, policy: None)


@pytest.mark.parametrize(
    "path",
    ["/auth", "/auth/login", "/auth/logout", "/auth/custom", "/auth/deeply/nested"],
)
def test_auth_namespace_is_reserved(path: str) -> None:
    """`/auth` is framework-owned: the login/logout routes live there, and
    `AuthorizationMiddleware` classifies `/auth/login` and `/auth/logout` as
    explicitly public. An application route allowed to occupy that namespace
    is therefore served to anonymous callers with no permission check -- a
    direct authorization bypass. Reserve it the same way `/_system` is."""
    builder = ApplicationBuilder()
    builder.add_route(
        RouteDefinition(route_name="app.evil", methods=("GET",), path=path, owner_id="evil")
    )
    with pytest.raises(RakitError) as caught:
        compile_application(builder)
    assert caught.value.code == "config.reserved_path"


@pytest.mark.parametrize("path", ["/authors", "/authentication", "/auth-log"])
def test_paths_merely_prefixed_by_auth_are_not_reserved(path: str) -> None:
    """Reservation must match at a segment boundary, not as a bare prefix --
    `/authors` is an ordinary application resource, not framework-owned."""
    builder = ApplicationBuilder()
    builder.add_route(
        RouteDefinition(route_name="app.ok", methods=("GET",), path=path, owner_id="ok")
    )
    compile_application(builder)


def test_framework_owned_routes_may_occupy_the_reserved_auth_namespace() -> None:
    """The framework's own login/logout routes must be representable in the
    compiled route graph (so `rakit routes` and collision checks reflect
    runtime reality) despite living under the reserved prefix."""
    builder = ApplicationBuilder()
    builder.add_route(
        RouteDefinition(
            route_name="rakit.auth.login",
            methods=("GET",),
            path="/auth/login",
            owner_id="rakit",
            framework_owned=True,
        )
    )
    compiled = compile_application(builder)
    assert any(route.path == "/auth/login" for route in compiled.routes)


def test_framework_owned_flag_cannot_be_forged_by_owner_id_alone() -> None:
    """Claiming `owner_id="rakit"` must not be enough to occupy a reserved
    path -- otherwise a ResourceAdmin whose resource_id happens to be
    "rakit" would slip straight through the reservation."""
    builder = ApplicationBuilder()
    builder.add_route(
        RouteDefinition(
            route_name="app.pretender", methods=("GET",), path="/auth/login", owner_id="rakit"
        )
    )
    with pytest.raises(RakitError) as caught:
        compile_application(builder)
    assert caught.value.code == "config.reserved_path"
