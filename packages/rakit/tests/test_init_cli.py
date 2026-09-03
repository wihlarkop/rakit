from pathlib import Path

from click.testing import CliRunner
from rakit.cli import cli


def test_interactive_init_uses_standard_uvicorn_defaults_and_prompt_order() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init"], input="demo-admin\n\n\nn\n")

        assert result.exit_code == 0, result.output
        assert Path("demo-admin/src/demo_admin/app.py").is_file()
        assert Path("demo-admin/src/demo_admin/db.py").is_file()
        assert result.output.index("Project name") < result.output.index("Starter template")
        assert result.output.index("Starter template") < result.output.index("Server adapter")
        assert result.output.index("Server adapter") < result.output.index(
            "Install dependencies now"
        )


def test_yes_mode_is_non_interactive_and_uses_defaults() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init", "demo-admin", "--yes", "--no-install"])

        assert result.exit_code == 0, result.output
        assert "Project name:" not in result.output
        assert "Starter template" not in result.output
        assert "Server adapter" not in result.output
        assert "Install dependencies now?" not in result.output
        assert "Template: standard" in result.output
        assert "Server: uvicorn" in result.output


def test_dry_run_prints_complete_plan_without_creating_target() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init", "dry-demo", "--yes", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "Mode: new" in result.output
        assert "Dependencies: uv sync" in result.output
        assert "create" in result.output
        assert not Path("dry-demo").exists()


def test_new_project_rejects_existing_mode_and_package_options() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            ["init", "demo", "--existing", ".", "--yes", "--no-install"],
        )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output

        package_result = runner.invoke(
            cli,
            ["init", "demo", "--package", "host_app", "--yes", "--no-install"],
        )
        assert package_result.exit_code != 0
        assert "only valid with --existing" in package_result.output


def test_existing_ambiguous_package_fails_under_yes_and_explicit_package_resolves() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        root = Path("host")
        for name in ("alpha", "beta"):
            package = root / "src" / name
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
        (root / "pyproject.toml").write_text(
            '[project]\nname = "host"\nversion = "0.1.0"\ndependencies = []\n',
            encoding="utf-8",
        )

        result = runner.invoke(
            cli,
            ["init", "--existing", "host", "--template", "minimal", "--no-install", "--yes"],
        )
        assert result.exit_code != 0
        assert "--package" in result.output

        resolved = runner.invoke(
            cli,
            [
                "init",
                "--existing",
                "host",
                "--package",
                "alpha",
                "--template",
                "minimal",
                "--no-install",
                "--yes",
            ],
        )
        assert resolved.exit_code == 0, resolved.output
        assert (root / "src" / "alpha" / "rakit_admin" / "app.py").is_file()
        assert not (root / "src" / "beta" / "rakit_admin").exists()


def test_existing_fastapi_mode_is_additive_and_prints_composition_snippet() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        root = Path("host")
        package = root / "src" / "host_app"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        host_source = package / "main.py"
        host_source.write_text("host_owned = True\n", encoding="utf-8")
        (root / "pyproject.toml").write_text(
            '[project]\nname = "host"\nversion = "0.1.0"\ndependencies = ["fastapi"]\n',
            encoding="utf-8",
        )

        result = runner.invoke(
            cli,
            ["init", "--existing", "host", "--no-install", "--yes"],
        )

        assert result.exit_code == 0, result.output
        assert host_source.read_text(encoding="utf-8") == "host_owned = True\n"
        assert (package / "rakit_admin" / "app.py").is_file()
        assert not (root / ".env.example").exists()
        assert "No host entrypoint" in result.output
        assert "from rakit import compose_asgi" in result.output
        assert 'app = compose_asgi(app, rakit_admin, path="/admin")' in result.output
        assert 'app.mount("/admin", rakit_app' not in result.output
