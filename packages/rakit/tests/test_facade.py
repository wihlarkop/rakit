import sys

import pytest
from rakit import RakitConfig
from rakit._optional import RakitOptionalDependencyError, optional_import, require_module


def test_core_type_is_reexported() -> None:
    assert RakitConfig.__module__ == "rakit_core.config"


def test_admin_types_are_reexported() -> None:
    from rakit import ModelAdmin, ResourceAdmin
    from rakit_core.admin_types import ModelAdmin as RealModelAdmin
    from rakit_core.admin_types import ResourceAdmin as RealResourceAdmin

    assert ModelAdmin is RealModelAdmin
    assert ResourceAdmin is RealResourceAdmin


def test_plan01_core_types_are_reexported_with_preserved_identity() -> None:
    from rakit.core import EventBus, ServiceScope
    from rakit_core.di import ServiceScope as RealServiceScope
    from rakit_core.events import EventBus as RealEventBus

    assert ServiceScope is RealServiceScope
    assert EventBus is RealEventBus
    assert ServiceScope.__module__ == "rakit_core.di"
    assert EventBus.__module__ == "rakit_core.events"


def test_plan02_core_types_are_reexported_with_preserved_identity() -> None:
    from rakit.core import (
        CountPolicy,
        DataSource,
        DataSourceCapabilities,
        Filter,
        FilterOperator,
        IdentityCodec,
        NullPlacement,
        OffsetPagination,
        PageResult,
        RecordIdentity,
        ResourceQuery,
        ResourceService,
        Sort,
        SortDirection,
    )
    from rakit_core.datasource import DataSource as RealDataSource
    from rakit_core.datasource import DataSourceCapabilities as RealDataSourceCapabilities
    from rakit_core.identity import IdentityCodec as RealIdentityCodec
    from rakit_core.identity import RecordIdentity as RealRecordIdentity
    from rakit_core.query import CountPolicy as RealCountPolicy
    from rakit_core.query import Filter as RealFilter
    from rakit_core.query import FilterOperator as RealFilterOperator
    from rakit_core.query import NullPlacement as RealNullPlacement
    from rakit_core.query import OffsetPagination as RealOffsetPagination
    from rakit_core.query import PageResult as RealPageResult
    from rakit_core.query import ResourceQuery as RealResourceQuery
    from rakit_core.query import Sort as RealSort
    from rakit_core.query import SortDirection as RealSortDirection
    from rakit_core.resources import ResourceService as RealResourceService

    assert CountPolicy is RealCountPolicy
    assert DataSource is RealDataSource
    assert DataSourceCapabilities is RealDataSourceCapabilities
    assert Filter is RealFilter
    assert FilterOperator is RealFilterOperator
    assert IdentityCodec is RealIdentityCodec
    assert NullPlacement is RealNullPlacement
    assert OffsetPagination is RealOffsetPagination
    assert PageResult is RealPageResult
    assert RecordIdentity is RealRecordIdentity
    assert ResourceQuery is RealResourceQuery
    assert ResourceService is RealResourceService
    assert Sort is RealSort
    assert SortDirection is RealSortDirection


def test_importing_core_plan02_facade_does_not_load_optional_sqlalchemy(monkeypatch) -> None:
    for name in list(sys.modules):
        if name == "rakit" or name.startswith("rakit.") or name.startswith("rakit_sqlalchemy"):
            monkeypatch.delitem(sys.modules, name, raising=False)

    from rakit.core import ResourceQuery

    assert ResourceQuery.__module__ == "rakit_core.query"
    assert "rakit_sqlalchemy" not in sys.modules


def test_missing_dependency_includes_uv_command() -> None:
    with pytest.raises(RakitOptionalDependencyError) as caught:
        require_module("missing_rakit_dependency", extra="sqlalchemy")
    assert 'uv add "rakit[sqlalchemy]"' in str(caught.value)


def test_transitive_missing_dependency_propagates_unchanged(tmp_path, monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "rakit_test_fake_optional", raising=False)
    fake_module = tmp_path / "rakit_test_fake_optional.py"
    fake_module.write_text("import this_transitive_dependency_does_not_exist_anywhere  # noqa\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(ModuleNotFoundError) as caught:
        require_module("rakit_test_fake_optional", extra="whatever")

    assert caught.value.name == "this_transitive_dependency_does_not_exist_anywhere"
    assert not isinstance(caught.value, RakitOptionalDependencyError)


def test_optional_import_converts_expected_missing_module() -> None:
    with (
        pytest.raises(RakitOptionalDependencyError) as caught,
        optional_import("missing_rakit_dependency", extra="server-uvicorn"),
    ):
        import missing_rakit_dependency  # noqa: F401  # ty: ignore[unresolved-import]
    assert 'uv add "rakit[server-uvicorn]"' in str(caught.value)


def test_optional_import_propagates_transitive_missing_dependency_unchanged(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delitem(sys.modules, "rakit_test_fake_optional_ctx", raising=False)
    fake_module = tmp_path / "rakit_test_fake_optional_ctx.py"
    fake_module.write_text("import this_transitive_dependency_does_not_exist_anywhere  # noqa\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    with (
        pytest.raises(ModuleNotFoundError) as caught,
        optional_import("rakit_test_fake_optional_ctx", extra="whatever"),
    ):
        from rakit_test_fake_optional_ctx import (  # noqa: F401  # ty: ignore[unresolved-import]
            something,
        )

    assert caught.value.name == "this_transitive_dependency_does_not_exist_anywhere"
    assert not isinstance(caught.value, RakitOptionalDependencyError)


def test_importing_rakit_does_not_eagerly_import_uvicorn(monkeypatch) -> None:
    # Use monkeypatch (not a bare `del`) so the removed modules -- including
    # rakit._optional -- are restored after the test. Otherwise later tests
    # that import a class from a freshly re-created rakit._optional module
    # would get an object that's no longer `is`-identical to the one other
    # tests captured at collection time (e.g. RakitOptionalDependencyError).
    for name in list(sys.modules):
        if name == "rakit" or name.startswith("rakit."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.delitem(sys.modules, "uvicorn", raising=False)

    import rakit  # noqa: F401

    assert "uvicorn" not in sys.modules


def test_server_uvicorn_facade_reexports_real_class() -> None:
    from rakit.server.uvicorn import UvicornServer
    from rakit_server_uvicorn.server import UvicornServer as RealUvicornServer

    assert UvicornServer is RealUvicornServer

    server = UvicornServer(app="module:app")
    assert server.host == "127.0.0.1"
    assert server.port == 8000
    assert server.reload is False
    assert server.log_level is None


def test_server_uvicorn_facade_raises_friendly_error_when_missing(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "rakit_server_uvicorn", None)
    sys.modules.pop("rakit.server.uvicorn", None)

    with pytest.raises(RakitOptionalDependencyError) as caught:
        import rakit.server.uvicorn  # noqa: F401

    assert 'uv add "rakit[server-uvicorn]"' in str(caught.value)
