from pathlib import Path

from click.testing import CliRunner
from rakit.cli import cli


def test_check_imports_and_compiles(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "sample_app.py").write_text(
        "from rakit import Admin, SecretValue\n"
        "admin = Admin(title='Sample', debug=False, secret_key=SecretValue('x' * 32))\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    result = CliRunner().invoke(cli, ["check", "sample_app:admin"])
    assert result.exit_code == 0
    assert "Rakit configuration is valid." in result.output


def test_routes_lists_registered_routes(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "sample_routes_app.py").write_text(
        "from rakit import Admin, SecretValue\n"
        "from rakit_core.compiler import ApplicationBuilder\n"
        "from rakit_core.definitions import RouteDefinition\n"
        "\n"
        "\n"
        "class _RoutePlugin:\n"
        "    plugin_id = 'sample_routes'\n"
        "\n"
        "    def configure(self, builder: ApplicationBuilder) -> None:\n"
        "        builder.add_route(\n"
        "            RouteDefinition(\n"
        "                route_name='sample.home',\n"
        "                methods=('GET',),\n"
        "                path='/sample',\n"
        "                owner_id='sample_routes',\n"
        "            )\n"
        "        )\n"
        "\n"
        "\n"
        "admin = Admin(title='Sample', debug=False, secret_key=SecretValue('x' * 32))\n"
        "admin.install(_RoutePlugin())\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    result = CliRunner().invoke(cli, ["routes", "sample_routes_app:admin"])
    assert result.exit_code == 0
    assert "GET" in result.output
    assert "/sample" in result.output
    assert "sample.home" in result.output
