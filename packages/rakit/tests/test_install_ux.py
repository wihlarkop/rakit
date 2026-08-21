from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from rakit._install import InstallExtra, format_uv_add_command, rakit_requirement, uv_add_command


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_RAKIT_PYPROJECT = _REPOSITORY_ROOT / "packages" / "rakit" / "pyproject.toml"


def test_canonical_extras_match_package_metadata() -> None:
    project = tomllib.loads(_RAKIT_PYPROJECT.read_text(encoding="utf-8"))["project"]
    optional = project["optional-dependencies"]

    assert set(optional) == {
        "uvicorn",
        "granian",
        "sqlalchemy",
        "auth-sqlalchemy",
        "storage-local",
        "standard",
    }
    assert {extra.value for extra in InstallExtra} == set(optional)
    assert "server-uvicorn" not in optional


def test_standard_extra_is_server_neutral_and_driver_neutral() -> None:
    project = tomllib.loads(_RAKIT_PYPROJECT.read_text(encoding="utf-8"))["project"]

    assert project["optional-dependencies"]["standard"] == [
        "rakit-sqlalchemy==0.1.0a1",
        "rakit-auth-sqlalchemy==0.1.0a1",
        "rakit-storage-local==0.1.0a1",
    ]


def test_requirement_formatting_is_deterministic_and_deduplicated() -> None:
    assert rakit_requirement() == "rakit"
    assert rakit_requirement(InstallExtra.SQLALCHEMY) == "rakit[sqlalchemy]"
    assert (
        rakit_requirement(
            InstallExtra.UVICORN,
            InstallExtra.STANDARD,
            InstallExtra.STANDARD,
        )
        == "rakit[standard,uvicorn]"
    )
    assert (
        rakit_requirement(
            InstallExtra.GRANIAN,
            InstallExtra.STORAGE_LOCAL,
            InstallExtra.AUTH_SQLALCHEMY,
            InstallExtra.SQLALCHEMY,
            InstallExtra.STANDARD,
        )
        == "rakit[standard,sqlalchemy,auth-sqlalchemy,storage-local,granian]"
    )


def test_uv_add_command_keeps_application_packages_outside_extras() -> None:
    assert uv_add_command(
        InstallExtra.STANDARD,
        InstallExtra.UVICORN,
        packages=("aiosqlite",),
    ) == ("uv", "add", "rakit[standard,uvicorn]", "aiosqlite")
    assert (
        format_uv_add_command(
            InstallExtra.STANDARD,
            InstallExtra.GRANIAN,
            packages=("asyncpg",),
        )
        == 'uv add "rakit[standard,granian]" asyncpg'
    )


def test_raw_extra_names_are_rejected_at_runtime() -> None:
    with pytest.raises(TypeError, match="InstallExtra"):
        rakit_requirement("uvicorn")  # type: ignore[arg-type]
