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
