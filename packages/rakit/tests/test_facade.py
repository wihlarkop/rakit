import sys

import pytest
from rakit import RakitConfig
from rakit._optional import RakitOptionalDependencyError, require_module


def test_core_type_is_reexported() -> None:
    assert RakitConfig.__module__ == "rakit_core.config"


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
