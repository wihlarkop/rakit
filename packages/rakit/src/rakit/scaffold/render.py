from __future__ import annotations

from textwrap import dedent

from .model import (
    DependencyAction,
    InitConfig,
    InitMode,
    PlannedFile,
    ServerAdapter,
    StarterTemplate,
)


def _text(value: str) -> str:
    return dedent(value).lstrip("\n").rstrip() + "\n"


def _dependency_specs(config: InitConfig) -> tuple[str, ...]:
    if config.template is StarterTemplate.STANDARD:
        if config.server is ServerAdapter.UVICORN:
            return ("rakit[standard]", "aiosqlite")
        return ("rakit[sqlalchemy,auth-sqlalchemy,storage-local,granian]", "aiosqlite")
    if config.server is ServerAdapter.UVICORN:
        return ("rakit[uvicorn]",)
    return ("rakit[granian]",)


def dependency_command_for(config: InitConfig) -> tuple[str, ...]:
    if config.mode is InitMode.NEW:
        return ("uv", "sync")
    return ("uv", "add", *_dependency_specs(config))


def dependency_action_for(config: InitConfig) -> DependencyAction | None:
    if not config.install_dependencies:
        return None
    return DependencyAction(argv=dependency_command_for(config), cwd=config.target)


def _new_pyproject(config: InitConfig) -> str:
    assert config.distribution_name is not None
    dependencies = "\n".join(f'    "{item}",' for item in _dependency_specs(config))
    return (
        "[build-system]\n"
        'requires = ["hatchling>=1.27"]\n'
        'build-backend = "hatchling.build"\n'
        "\n"
        "[project]\n"
        f'name = "{config.distribution_name}"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.12"\n'
        "dependencies = [\n"
        f"{dependencies}\n"
        "]\n"
        "\n"
        "[tool.hatch.build.targets.wheel]\n"
        f'packages = ["src/{config.import_package}"]\n'
    )


def _new_gitignore(*, standard: bool) -> str:
    common = """\
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
dist/
build/
"""
    if not standard:
        return common
    return (
        common
        + """\
.env
var/*
!var/.gitkeep
"""
    )


def _minimal_app() -> str:
    return _text(
        '''
        """Small read-only Rakit starter."""

        from __future__ import annotations

        from dataclasses import dataclass
        from typing import Any

        from rakit import Admin, ResourceAdmin, SecretValue

        _ITEMS: tuple[dict[str, object], ...] = (
            {"id": 1, "name": "First item"},
            {"id": 2, "name": "Second item"},
        )


        @dataclass(frozen=True)
        class _Page:
            items: tuple[dict[str, object], ...]
            page: int
            per_page: int
            has_previous: bool
            has_next: bool
            total_count: int | None


        class ItemDataSource:
            capabilities = type("Capabilities", (), {"read": True})()
            fields = ("id", "name")
            identity_fields = ("id",)

            async def list(self, query: Any) -> _Page:
                items = list(_ITEMS)
                for sort in reversed(query.sorting):
                    items.sort(
                        key=lambda item: item.get(sort.field),
                        reverse=sort.direction.value == "desc",
                    )
                start = query.pagination.offset
                end = start + query.pagination.per_page
                return _Page(
                    items=tuple(items[start:end]),
                    page=query.pagination.page,
                    per_page=query.pagination.per_page,
                    has_previous=query.pagination.page > 1,
                    has_next=end < len(items),
                    total_count=len(items) if query.count_policy.value == "exact" else None,
                )

            async def count(self, query: Any) -> int:
                del query
                return len(_ITEMS)

            async def detail(self, identity: Any) -> dict[str, object] | None:
                wanted = identity.values["id"]
                return next((item for item in _ITEMS if item["id"] == wanted), None)


        class ItemAdmin(ResourceAdmin):
            resource_id = "items"
            path = "/items"
            label = "Items"
            singular_label = "Item"
            data_source = ItemDataSource()
            list_fields = ("id", "name")
            detail_fields = ("id", "name")
            sort_fields = ("id", "name")


        admin = Admin(
            admin_id="starter",
            title="Rakit Starter",
            debug=True,
            secret_key=SecretValue("development-only-read-only-starter"),
        )
        admin.register(ItemAdmin)
        app = admin.asgi()

        __all__ = ["admin", "app"]
        '''
    )


def _standard_db(*, existing: bool) -> str:
    default_root = ".rakit" if existing else "var"
    return _text(
        f'''
        """Starter-owned development database and runtime paths."""

        from __future__ import annotations

        import os
        from pathlib import Path

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        DATA_ROOT = Path(os.environ.get("RAKIT_DATA_ROOT", "{default_root}"))
        DATABASE_PATH = DATA_ROOT / "app.db"
        UPLOAD_ROOT = DATA_ROOT / "uploads"

        engine = create_async_engine(f"sqlite+aiosqlite:///{{DATABASE_PATH.as_posix()}}")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)


        def ensure_runtime_directories() -> None:
            DATA_ROOT.mkdir(parents=True, exist_ok=True)
            UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)


        async def database_ready() -> bool:
            try:
                ensure_runtime_directories()
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
                return True
            except Exception:
                return False


        async def dispose_database() -> None:
            await engine.dispose()


        __all__ = [
            "DATA_ROOT",
            "DATABASE_PATH",
            "UPLOAD_ROOT",
            "database_ready",
            "dispose_database",
            "engine",
            "ensure_runtime_directories",
            "session_factory",
        ]
        '''
    )


def _standard_models() -> str:
    return _text(
        '''
        """Starter-owned SQLAlchemy model."""

        from sqlalchemy import Boolean, Integer, String
        from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


        class Base(DeclarativeBase):
            pass


        class Item(Base):
            __tablename__ = "starter_items"

            id: Mapped[int] = mapped_column(primary_key=True)
            name: Mapped[str] = mapped_column(String(200), index=True)
            description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
            enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
            version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


        __all__ = ["Base", "Item"]
        '''
    )


def _standard_resources() -> str:
    return _text(
        '''
        """Starter resource using Rakit's declarative C1 CRUD surface."""

        from rakit import FieldDefinition, ModelAdmin, ResourceWriteDefinition
        from rakit.core import FormSchema

        from .models import Item

        ITEM_FORM = FormSchema(
            fields=(
                FieldDefinition(field_id="name", python_type=str, label="Name", required=True),
                FieldDefinition(
                    field_id="description",
                    python_type=str,
                    label="Description",
                    required=False,
                    nullable=True,
                ),
                FieldDefinition(
                    field_id="enabled", python_type=bool, label="Enabled", required=True
                ),
            )
        )


        class ItemAdmin(ModelAdmin):
            resource_id = "items"
            path = "/items"
            label = "Items"
            singular_label = "Item"
            model = Item
            list_fields = ("id", "name", "enabled")
            detail_fields = ("id", "name", "description", "enabled", "version")
            filter_fields = ("enabled",)
            search_fields = ("name", "description")
            sort_fields = ("id", "name")
            write = ResourceWriteDefinition(
                form_schema=ITEM_FORM,
                writable_fields=("name", "description", "enabled"),
                version_field="version",
                success_message="Item saved.",
            )


        __all__ = ["ItemAdmin"]
        '''
    )


def _standard_bootstrap() -> str:
    return _text(
        '''
        """Explicit development bootstrap; this is not a production migration system."""

        import asyncio

        from rakit.auth.sqlalchemy import AuthBase

        from .db import engine, ensure_runtime_directories
        from .models import Base


        async def bootstrap() -> None:
            ensure_runtime_directories()
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
                await connection.run_sync(AuthBase.metadata.create_all)


        def main() -> None:
            asyncio.run(bootstrap())


        if __name__ == "__main__":
            main()
        '''
    )


def _standard_app() -> str:
    return _text(
        '''
        """Rakit standard starter composition root."""

        from __future__ import annotations

        import os

        from rakit import Admin, SecretValue
        from rakit.auth.sqlalchemy import SQLAlchemyAuthPlugin, SQLAlchemyIdempotencyStore
        from rakit.sqlalchemy import SQLAlchemyPlugin
        from rakit.storage.local import LocalStorage, LocalStoragePlugin

        from .db import UPLOAD_ROOT, database_ready, dispose_database, session_factory
        from .resources import ItemAdmin


        def _secret_key() -> SecretValue:
            value = os.environ.get("RAKIT_SECRET_KEY")
            if not value:
                raise RuntimeError(
                    "Set RAKIT_SECRET_KEY before importing the standard starter app."
                )
            return SecretValue(value)


        auth = SQLAlchemyAuthPlugin(session_factory)
        idempotency_store = SQLAlchemyIdempotencyStore(session_factory)

        admin = Admin(
            admin_id="starter",
            title="Rakit Starter",
            debug=True,
            secret_key=_secret_key(),
            auth_backend=auth.auth_backend,
            session_store=auth.session_store,
            operation_idempotency_store=idempotency_store,
        )
        admin.install(SQLAlchemyPlugin(session_factory=session_factory))
        admin.install(
            LocalStoragePlugin(
                storages=(
                    LocalStorage(
                        storage_id="uploads",
                        root=UPLOAD_ROOT,
                    ),
                )
            )
        )
        admin.register(ItemAdmin)
        admin.add_health_check(
            "database",
            database_ready,
            critical=True,
            timeout_seconds=2.0,
            cache_seconds=1.0,
        )
        admin.on_shutdown(dispose_database)

        app = admin.asgi()

        __all__ = ["admin", "app"]
        '''
    )


def _new_readme(config: InitConfig) -> str:
    if config.template is StarterTemplate.MINIMAL:
        return _text(
            f"""
            # {config.distribution_name}

            Generated by `rakit init` with the minimal read-only starter.

            ## Run

            ```bash
            uv sync
            uv run rakit check {config.import_package}.app:admin
            uv run rakit run {config.import_package}.app:admin \\
              --server {config.server.value} --reload
            ```
            """
        )

    return _text(
        f"""
        # {config.distribution_name}

        Generated by `rakit init` with the standard starter.

        This starter owns a development SQLite database under `var/`. The bootstrap
        command below creates starter and Rakit auth tables for development only; it is
        not a production migration strategy.

        `.env.example` documents the required secret variable, but the starter does not
        auto-load `.env` files. Export the variable in your shell or use your application's
        environment loader.

        ## Bootstrap and run

        ```bash
        uv sync
        export RAKIT_SECRET_KEY="replace-with-a-long-random-secret"
        uv run python -m {config.import_package}.bootstrap
        uv run rakit check {config.import_package}.app:admin
        uv run rakit permissions sync {config.import_package}.app:admin
        uv run rakit createsuperuser {config.import_package}.app:admin --email admin@example.com
        uv run rakit run {config.import_package}.app:admin \\
          --server {config.server.value} --reload
        ```
        """
    )


def _existing_readme(config: InitConfig) -> str:
    if config.template is StarterTemplate.MINIMAL:
        return _text(
            f"""
            # Rakit admin module

            This Rakit-owned module was generated additively. No host entrypoint was
            modified.

            Run it standalone with:

            ```bash
            uv run rakit check {config.import_package}.app:admin
            uv run rakit run {config.import_package}.app:admin \\
              --server {config.server.value} --reload
            ```
            """
        )

    return _text(
        f"""
        # Rakit admin module

        This Rakit-owned module was generated additively. No host entrypoint,
        database/session configuration, root `.env`, or root `.gitignore` was modified.

        Until you deliberately replace the generated composition, this module owns a
        development SQLite database and uploads under `.rakit/`. Add `.rakit/` to your VCS
        ignore rules if appropriate for your project.

        The module reads `RAKIT_SECRET_KEY` directly from the process environment and does
        not auto-load `.env` files.

        Development bootstrap:

        ```bash
        export RAKIT_SECRET_KEY="replace-with-a-long-random-secret"
        uv run python -m {config.import_package}.bootstrap
        uv run rakit check {config.import_package}.app:admin
        uv run rakit permissions sync {config.import_package}.app:admin
        uv run rakit createsuperuser {config.import_package}.app:admin --email admin@example.com
        uv run rakit run {config.import_package}.app:admin \\
          --server {config.server.value} --reload
        ```
        """
    )


def render_scaffold_files(config: InitConfig) -> tuple[PlannedFile, ...]:
    files: list[PlannedFile] = []

    if config.mode is InitMode.NEW:
        files.extend(
            (
                PlannedFile(config.target / "pyproject.toml", _new_pyproject(config)),
                PlannedFile(config.target / ".python-version", "3.12\n"),
                PlannedFile(
                    config.target / ".gitignore",
                    _new_gitignore(standard=config.template is StarterTemplate.STANDARD),
                ),
                PlannedFile(config.target / "README.md", _new_readme(config)),
            )
        )

    files.append(PlannedFile(config.module_root / "__init__.py", ""))

    if config.template is StarterTemplate.MINIMAL:
        files.append(PlannedFile(config.module_root / "app.py", _minimal_app()))
        if config.mode is InitMode.EXISTING:
            files.append(PlannedFile(config.module_root / "README.md", _existing_readme(config)))
        return tuple(files)

    if config.mode is InitMode.NEW:
        files.extend(
            (
                PlannedFile(
                    config.target / ".env.example",
                    "RAKIT_SECRET_KEY=<generate-a-real-secret>\n",
                ),
                PlannedFile(config.target / "var" / ".gitkeep", ""),
            )
        )

    files.extend(
        (
            PlannedFile(
                config.module_root / "db.py",
                _standard_db(existing=config.mode is InitMode.EXISTING),
            ),
            PlannedFile(config.module_root / "models.py", _standard_models()),
            PlannedFile(config.module_root / "resources.py", _standard_resources()),
            PlannedFile(config.module_root / "bootstrap.py", _standard_bootstrap()),
            PlannedFile(config.module_root / "app.py", _standard_app()),
        )
    )
    if config.mode is InitMode.EXISTING:
        files.append(PlannedFile(config.module_root / "README.md", _existing_readme(config)))
    return tuple(files)


def _mount_snippet(config: InitConfig) -> tuple[str, ...]:
    if config.host_framework not in {"fastapi", "starlette"}:
        return ()
    return (
        "Host integration snippet (not applied automatically):",
        f"from {config.import_package}.app import app as rakit_app",
        'app.mount("/admin", rakit_app, name="rakit-admin")',
    )


def guidance_for(config: InitConfig) -> tuple[str, ...]:
    guidance: list[str] = []
    target_module = f"{config.import_package}.app:admin"

    if config.mode is InitMode.NEW:
        guidance.append(f"cd {config.target.name}")

    if not config.install_dependencies:
        guidance.append(
            "Install dependencies when ready: " + " ".join(dependency_command_for(config))
        )

    if config.template is StarterTemplate.STANDARD:
        guidance.extend(
            (
                "Set RAKIT_SECRET_KEY in the process environment "
                "(the generated app does not auto-load .env).",
                f"uv run python -m {config.import_package}.bootstrap",
                f"uv run rakit check {target_module}",
                f"uv run rakit permissions sync {target_module}",
                f"uv run rakit createsuperuser {target_module} --email admin@example.com",
                f"uv run rakit run {target_module} --server {config.server.value} --reload",
            )
        )
    else:
        guidance.extend(
            (
                f"uv run rakit check {target_module}",
                f"uv run rakit run {target_module} --server {config.server.value} --reload",
            )
        )

    if config.mode is InitMode.EXISTING:
        guidance.append("No host entrypoint or arbitrary host source file was edited.")
        if config.template is StarterTemplate.STANDARD:
            guidance.append(
                "The generated standard module uses isolated .rakit/ development data "
                "until you replace its persistence composition explicitly."
            )
        guidance.extend(_mount_snippet(config))

    return tuple(guidance)


__all__ = [
    "dependency_action_for",
    "dependency_command_for",
    "guidance_for",
    "render_scaffold_files",
]
