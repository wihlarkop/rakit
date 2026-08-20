from pathlib import Path

import pytest
from rakit.scaffold.detection import (
    PackageResolutionRequired,
    ScaffoldDetectionError,
    detect_host_framework,
    normalize_distribution_name,
    resolve_existing_package,
)


def test_normalize_distribution_name_preserves_distribution_and_normalizes_import() -> None:
    assert normalize_distribution_name("my-admin") == ("my-admin", "my_admin")
    assert normalize_distribution_name("Admin2") == ("Admin2", "Admin2")


@pytest.mark.parametrize(
    "name",
    ("", " bad", "bad ", "../bad", "bad/name", "2bad", "class", "bad.name"),
)
def test_normalize_distribution_name_rejects_unsafe_values(name: str) -> None:
    with pytest.raises(ScaffoldDetectionError):
        normalize_distribution_name(name)


def test_resolve_existing_package_prefers_unambiguous_src_layout(tmp_path: Path) -> None:
    package = tmp_path / "src" / "host_app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")

    resolution = resolve_existing_package(tmp_path, None, interactive=False)

    assert resolution.host_package == "host_app"
    assert resolution.module_package == "host_app.rakit_admin"
    assert resolution.module_root == package / "rakit_admin"


def test_resolve_existing_package_supports_unambiguous_flat_layout(tmp_path: Path) -> None:
    package = tmp_path / "host_app"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")

    resolution = resolve_existing_package(tmp_path, None, interactive=False)

    assert resolution.host_package == "host_app"
    assert resolution.module_root == package / "rakit_admin"


def test_resolve_existing_package_requires_explicit_choice_when_ambiguous(tmp_path: Path) -> None:
    for name in ("alpha", "beta"):
        package = tmp_path / "src" / name
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")

    with pytest.raises(PackageResolutionRequired) as exc_info:
        resolve_existing_package(tmp_path, None, interactive=False)

    assert exc_info.value.candidates == ("alpha", "beta")

    resolution = resolve_existing_package(tmp_path, "beta", interactive=False)
    assert resolution.module_package == "beta.rakit_admin"
    assert resolution.module_root == tmp_path / "src" / "beta" / "rakit_admin"


def test_resolve_existing_package_falls_back_only_for_clearly_flat_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='host'\n", encoding="utf-8")

    resolution = resolve_existing_package(tmp_path, None, interactive=False)

    assert resolution.host_package is None
    assert resolution.module_package == "rakit_admin"
    assert resolution.module_root == tmp_path / "rakit_admin"


def test_detect_host_framework_reads_dependency_metadata_without_importing_host() -> None:
    fastapi = """
[project]
name = "host"
dependencies = ["starlette>=1", "fastapi>=0.100"]
"""
    starlette = """
[project]
name = "host"
dependencies = []

[project.optional-dependencies]
web = ["starlette>=1"]
"""

    assert detect_host_framework(fastapi) == "fastapi"
    assert detect_host_framework(starlette) == "starlette"
    assert detect_host_framework("[project]\nname='host'\ndependencies=[]\n") is None
    assert detect_host_framework("not = [valid") is None
