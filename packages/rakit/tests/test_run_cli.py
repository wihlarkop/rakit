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
