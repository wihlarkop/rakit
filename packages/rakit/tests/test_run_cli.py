import importlib
import sys
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from rakit.cli import cli


def test_run_command_delegates_to_programmatic_api(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_run(target: str, **kwargs: Any) -> None:
        calls.append((target, kwargs))

    monkeypatch.setattr("rakit.cli.run_server", fake_run)

    result = CliRunner().invoke(
        cli,
        [
            "run",
            "sample:admin",
            "--server",
            "granian",
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "--workers",
            "4",
            "--reload",
            "--log-level",
            "warning",
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        (
            "sample:admin",
            {
                "server": "granian",
                "host": "0.0.0.0",
                "port": 9000,
                "workers": 4,
                "reload": True,
                "log_level": "warning",
            },
        )
    ]


def test_run_command_defaults_to_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "rakit.cli.run_server",
        lambda target, **kwargs: calls.append((target, kwargs)),
    )

    result = CliRunner().invoke(cli, ["run", "sample:admin"])

    assert result.exit_code == 0
    assert calls[0][0] == "sample:admin"
    assert calls[0][1]["server"] == "uvicorn"
    assert calls[0][1]["host"] == "127.0.0.1"
    assert calls[0][1]["port"] == 8000
    assert calls[0][1]["workers"] == 1
    assert calls[0][1]["reload"] is False


def test_run_command_makes_working_directory_importable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "rakit_cli_local_target_fixture"
    (tmp_path / f"{module_name}.py").write_text("marker = 'loaded-from-cwd'\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    working_directory = str(tmp_path.resolve())
    monkeypatch.setattr(
        sys,
        "path",
        [entry for entry in sys.path if entry not in {"", working_directory}],
    )
    sys.modules.pop(module_name, None)

    imported: list[str] = []

    def fake_run(target: str, **kwargs: Any) -> None:
        del kwargs
        target_module, _ = target.split(":", 1)
        imported.append(importlib.import_module(target_module).marker)

    monkeypatch.setattr("rakit.cli.run_server", fake_run)

    result = CliRunner().invoke(cli, ["run", f"{module_name}:admin"])

    assert result.exit_code == 0
    assert imported == ["loaded-from-cwd"]
