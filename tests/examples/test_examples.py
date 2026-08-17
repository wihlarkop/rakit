"""Release smoke tests for the official executable examples."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from click.testing import CliRunner
from rakit.cli import cli

EXAMPLES = (
    "examples.minimal.main",
    "examples.fastapi_sqlalchemy.main",
    "examples.builtin_auth.main",
    "examples.relationships.main",
    "examples.internal_tools.main",
    "examples.custom_datasource.main",
    "examples.dashboard.main",
)

TARGETS = tuple(f"{module}:admin" for module in EXAMPLES)


def _prepend_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(repository))


@pytest.mark.parametrize("module_name", EXAMPLES)
def test_official_example_compiles(
    module_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepend_repository(monkeypatch)
    module = importlib.import_module(module_name)
    compiled = module.admin.compile()
    assert compiled.admin_id
    assert compiled.routes


@pytest.mark.parametrize("target", TARGETS)
def test_official_example_passes_rakit_check(
    target: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepend_repository(monkeypatch)
    result = CliRunner().invoke(cli, ["check", target])
    assert result.exit_code == 0, result.output
    assert "Rakit configuration is valid." in result.output
