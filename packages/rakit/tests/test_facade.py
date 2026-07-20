import pytest
from rakit import RakitConfig
from rakit._optional import RakitOptionalDependencyError, require_module


def test_core_type_is_reexported() -> None:
    assert RakitConfig.__module__ == "rakit_core.config"


def test_missing_dependency_includes_uv_command() -> None:
    with pytest.raises(RakitOptionalDependencyError) as caught:
        require_module("missing_rakit_dependency", extra="sqlalchemy")
    assert 'uv add "rakit[sqlalchemy]"' in str(caught.value)
