"""Fast release metadata checks.

The expensive clean-install smoke lives in ``scripts/check_artifacts.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _load_checker(monkeypatch: pytest.MonkeyPatch):
    repository = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(repository))
    from scripts import check_artifacts

    return repository, check_artifacts


def test_workspace_release_inventory_is_derived_and_version_locked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, checker = _load_checker(monkeypatch)
    projects = checker.discover_projects(repository)

    assert projects
    assert {project.version for project in projects} == {checker.VERSION}
    assert {project.name for project in projects} == {
        path.parent.name for path in (repository / "packages").glob("*/pyproject.toml")
    }


def test_every_official_source_distribution_is_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, checker = _load_checker(monkeypatch)
    for project in checker.discover_projects(repository):
        typed = project.root / "src" / project.import_root / "py.typed"
        assert typed.is_file(), f"{project.name} is missing {typed.relative_to(repository)}"


def test_standard_extra_is_server_neutral_reference_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, checker = _load_checker(monkeypatch)
    checker.check_standard_extra(repository)


def test_facade_declares_storage_contract_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, checker = _load_checker(monkeypatch)
    checker.check_facade_dependencies(repository)


def test_artifact_checker_does_not_write_dist_into_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, checker = _load_checker(monkeypatch)
    source = (repository / "scripts" / "check_artifacts.py").read_text(encoding="utf-8")
    assert "TemporaryDirectory" in source
    assert 'root / "dist"' not in source
    assert checker.repository_root() == repository


def test_clean_import_probe_uses_isolated_interpreter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, _checker = _load_checker(monkeypatch)
    source = (repository / "scripts" / "check_artifacts.py").read_text(encoding="utf-8")
    assert '"-I"' in source
    assert "PYTHONNOUSERSITE" in source
    assert "working-tree import leaked" in source
    assert sys.version_info >= (3, 12)


def test_clean_install_resolves_cli_after_standard_uvicorn_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, _checker = _load_checker(monkeypatch)
    source = (repository / "scripts" / "check_artifacts.py").read_text(encoding="utf-8")
    install_marker = '_install_extra(dist, python, workspace, "standard,uvicorn")'
    cli_marker = "cli = _venv_rakit(venv)"
    assert source.index(install_marker) < source.index(cli_marker)


def test_release_gate_requires_complete_web_runtime_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repository, checker = _load_checker(monkeypatch)
    required = set(checker._REQUIRED_WHEEL_PATHS["rakit-web"])

    assert {
        "rakit_web/static/rakit.css",
        "rakit_web/static/rakit-ui.js",
        "rakit_web/static/rakit-widgets.js",
        "rakit_web/static/rakit-shell.js",
        "rakit_web/static/theme.js",
        "rakit_web/static/htmx.min.js",
        "rakit_web/static/HTMX_LICENSE.txt",
        "rakit_web/static/HTMX_PROVENANCE.md",
    } <= required


def test_release_gate_smokes_optional_granian_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, checker = _load_checker(monkeypatch)
    source = (repository / "scripts" / "check_artifacts.py").read_text(encoding="utf-8")

    assert checker._GRANIAN_MODULES == (
        "rakit.server.granian",
        "rakit_server_granian",
    )
    assert '_install_extra(dist, python, workspace, "granian")' in source
