import asyncio
import importlib
from pathlib import Path

from click.testing import CliRunner
from rakit.cli import cli


def test_generated_standard_project_bootstraps_and_passes_existing_cli(
    monkeypatch,
) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        generated = runner.invoke(
            cli,
            ["init", "standard-generated", "--template", "standard", "--no-install", "--yes"],
        )
        assert generated.exit_code == 0, generated.output

        project = Path("standard-generated").resolve()
        monkeypatch.syspath_prepend(str(project / "src"))
        monkeypatch.setenv("RAKIT_SECRET_KEY", "generated-test-secret-value-12345678901234567890")
        monkeypatch.setenv("RAKIT_DATA_ROOT", str(project / "var"))
        importlib.invalidate_caches()

        bootstrap = importlib.import_module("standard_generated.bootstrap")
        asyncio.run(bootstrap.bootstrap())

        check = runner.invoke(cli, ["check", "standard_generated.app:admin"])
        assert check.exit_code == 0, check.output
        assert "Rakit configuration is valid." in check.output

        permissions = runner.invoke(
            cli,
            ["permissions", "sync", "standard_generated.app:admin"],
        )
        assert permissions.exit_code == 0, permissions.output
        assert "added=" in permissions.output

        database = importlib.import_module("standard_generated.db")
        asyncio.run(database.dispose_database())


def test_generated_minimal_project_passes_existing_check_command(monkeypatch) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        generated = runner.invoke(
            cli,
            [
                "init",
                "minimal-generated",
                "--template",
                "minimal",
                "--server",
                "granian",
                "--no-install",
                "--yes",
            ],
        )
        assert generated.exit_code == 0, generated.output

        project = Path("minimal-generated").resolve()
        monkeypatch.syspath_prepend(str(project / "src"))
        importlib.invalidate_caches()

        check = runner.invoke(cli, ["check", "minimal_generated.app:admin"])
        assert check.exit_code == 0, check.output
        assert "Rakit configuration is valid." in check.output
        assert "minimal_generated" not in generated.output or "Package: minimal_generated" in generated.output
