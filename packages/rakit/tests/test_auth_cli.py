from pathlib import Path

from click.testing import CliRunner
from rakit.cli import cli


def _write_auth_app(tmp_path: Path, db_path: Path, module_name: str) -> None:
    (tmp_path / f"{module_name}.py").write_text(
        "import asyncio\n"
        "\n"
        "from rakit import Admin, SecretValue\n"
        "from rakit.sqlalchemy import SQLAlchemyPlugin\n"
        "from rakit_auth_sqlalchemy.models import Base\n"
        "from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine\n"
        "\n"
        f"_db_path = {str(db_path.as_posix())!r}\n"
        "_engine = create_async_engine(f'sqlite+aiosqlite:///{_db_path}')\n"
        "\n"
        "\n"
        "async def _create_schema() -> None:\n"
        "    async with _engine.begin() as conn:\n"
        "        await conn.run_sync(Base.metadata.create_all)\n"
        "\n"
        "\n"
        "asyncio.run(_create_schema())\n"
        "\n"
        "session_factory = async_sessionmaker(_engine, expire_on_commit=False)\n"
        "\n"
        "admin = Admin(\n"
        "    admin_id='operations', title='Operations', debug=False,\n"
        "    secret_key=SecretValue('x' * 32),\n"
        ")\n"
        "admin.install(SQLAlchemyPlugin(session_factory=session_factory))\n",
        encoding="utf-8",
    )


def test_create_superuser_hides_password(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "auth.sqlite3"
    _write_auth_app(tmp_path, db_path, "auth_app")
    monkeypatch.syspath_prepend(str(tmp_path))

    result = CliRunner().invoke(
        cli,
        ["createsuperuser", "auth_app:admin", "--email", "admin@example.com"],
        input="secret-password\nsecret-password\n",
    )

    assert result.exit_code == 0
    assert "secret-password" not in result.output


def test_create_superuser_rejects_duplicate_email(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "auth_dupe.sqlite3"
    _write_auth_app(tmp_path, db_path, "auth_app_dupe")
    monkeypatch.syspath_prepend(str(tmp_path))

    runner = CliRunner()
    first = runner.invoke(
        cli,
        ["createsuperuser", "auth_app_dupe:admin", "--email", "admin@example.com"],
        input="secret-password\nsecret-password\n",
    )
    assert first.exit_code == 0

    second = runner.invoke(
        cli,
        ["createsuperuser", "auth_app_dupe:admin", "--email", "admin@example.com"],
        input="another-password\nanother-password\n",
    )
    assert second.exit_code != 0


def test_create_superuser_without_sqlalchemy_plugin_fails_clearly(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "no_auth_app.py").write_text(
        "from rakit import Admin, SecretValue\n"
        "\n"
        "admin = Admin(title='Operations', debug=False, secret_key=SecretValue('x' * 32))\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    result = CliRunner().invoke(
        cli,
        ["createsuperuser", "no_auth_app:admin", "--email", "admin@example.com"],
        input="secret-password\nsecret-password\n",
    )

    assert result.exit_code != 0


def test_permissions_sync_reports_counts(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "auth_perms.sqlite3"
    (tmp_path / "perms_app.py").write_text(
        "import asyncio\n"
        "\n"
        "from rakit import Admin, ModelAdmin, SecretValue\n"
        "from rakit.sqlalchemy import SQLAlchemyPlugin\n"
        "from rakit_auth_sqlalchemy.models import Base\n"
        "from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine\n"
        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n"
        "\n"
        f"_db_path = {str(db_path.as_posix())!r}\n"
        "_engine = create_async_engine(f'sqlite+aiosqlite:///{_db_path}')\n"
        "\n"
        "\n"
        "class AppBase(DeclarativeBase):\n"
        "    pass\n"
        "\n"
        "\n"
        "class Widget(AppBase):\n"
        "    __tablename__ = 'widgets'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    name: Mapped[str]\n"
        "\n"
        "\n"
        "async def _create_schema() -> None:\n"
        "    async with _engine.begin() as conn:\n"
        "        await conn.run_sync(Base.metadata.create_all)\n"
        "        await conn.run_sync(AppBase.metadata.create_all)\n"
        "\n"
        "\n"
        "asyncio.run(_create_schema())\n"
        "\n"
        "session_factory = async_sessionmaker(_engine, expire_on_commit=False)\n"
        "\n"
        "admin = Admin(\n"
        "    admin_id='operations', title='Operations', debug=False,\n"
        "    secret_key=SecretValue('x' * 32),\n"
        ")\n"
        "admin.install(SQLAlchemyPlugin(session_factory=session_factory))\n"
        "\n"
        "\n"
        "class WidgetAdmin(ModelAdmin):\n"
        "    resource_id = 'widgets'\n"
        "    path = '/widgets'\n"
        "    label = 'Widgets'\n"
        "    singular_label = 'Widget'\n"
        "    model = Widget\n"
        "    list_fields = ('id', 'name')\n"
        "    detail_fields = ('id', 'name')\n"
        "\n"
        "\n"
        "admin.register(WidgetAdmin)\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    result = CliRunner().invoke(cli, ["permissions", "sync", "perms_app:admin"])

    assert result.exit_code == 0
    assert "added" in result.output.lower()
