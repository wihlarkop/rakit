import asyncio
import importlib
from typing import Any, Protocol, cast

import click
from rakit_core.compiler import CompiledApplication
from rakit_core.di import ServiceRegistry

from ._optional import optional_import
from ._server import run as run_server


class Compilable(Protocol):
    """Anything with a no-arg ``compile()`` producing a ``CompiledApplication``.

    ``load_object`` resolves an arbitrary ``module:attribute`` spec supplied
    by the user (e.g. ``myapp:admin``), so its return type can't be more
    specific than "the object at that attribute is expected to be
    compilable" -- this Protocol expresses exactly that contract instead of
    widening to bare ``object`` and suppressing the resulting attribute
    errors.
    """

    def compile(self) -> CompiledApplication: ...


class AdminLike(Compilable, Protocol):
    """The subset of `Admin`'s surface the auth commands need beyond plain
    `Compilable`: access to the compiled `builder.registry` (to resolve the
    installed `async_sessionmaker`) and to the compiled application's
    resources (to generate the permission catalogue)."""

    @property
    def builder(self) -> Any: ...

    @property
    def compiled(self) -> CompiledApplication | None: ...

    @property
    def config(self) -> Any: ...


def load_object(spec: str) -> Compilable:
    module_name, attribute = spec.split(":", 1)
    return getattr(importlib.import_module(module_name), attribute)


def _load_admin(target: str) -> AdminLike:
    admin = load_object(target)
    admin.compile()
    return cast(AdminLike, admin)


async def _resolve_session_factory(registry: ServiceRegistry) -> Any:
    """Resolve the `async_sessionmaker` an installed `SQLAlchemyPlugin`
    registered -- the same DI value both app resources and the built-in
    auth schema share, so no separate auth-specific plugin is needed."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async with registry.application_scope() as resolver:
        return resolver.require(async_sessionmaker)


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.argument("target")
def check(target: str) -> None:
    compiled = load_object(target).compile()
    click.echo("Rakit configuration is valid.")
    click.echo(f"Routes: {len(compiled.routes)}")
    click.echo(f"Plugins: {len(compiled.plugins)}")


@cli.command()
@click.argument("target")
def routes(target: str) -> None:
    for route in load_object(target).compile().routes:
        click.echo(f"{','.join(route.methods):8} {route.path:30} {route.route_name}")


@cli.command("run")
@click.argument("target")
@click.option("--server", "server_name", default="uvicorn", show_default=True)
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", type=click.IntRange(1, 65535), default=8000, show_default=True)
@click.option("--workers", type=click.IntRange(min=1), default=1, show_default=True)
@click.option("--reload", is_flag=True, default=False)
@click.option("--log-level", default=None)
def run_command(
    target: str,
    server_name: str,
    host: str,
    port: int,
    workers: int,
    reload: bool,
    log_level: str | None,
) -> None:
    """Serve TARGET through an installed Rakit server adapter."""
    run_server(
        target,
        server=server_name,
        host=host,
        port=port,
        workers=workers,
        reload=reload,
        log_level=log_level,
    )


@cli.command()
@click.argument("target")
@click.option("--email", required=True, help="Login identifier for the new superuser.")
@click.option("--username", default=None, help="Optional separate username.")
def createsuperuser(target: str, email: str, username: str | None) -> None:
    """Create a superuser account against TARGET's installed SQLAlchemy plugin.

    Requires the optional ``rakit[auth-sqlalchemy]`` distribution.
    """
    with optional_import("rakit_auth_sqlalchemy", extra="auth-sqlalchemy"):
        from rakit_auth_sqlalchemy.models import User
        from rakit_auth_sqlalchemy.passwords import Argon2PasswordHasher

    from sqlalchemy import select
    from sqlalchemy.exc import OperationalError, ProgrammingError

    admin = _load_admin(target)
    password = click.prompt("Password", hide_input=True, confirmation_prompt=True)

    async def _run() -> int:
        try:
            session_factory = await _resolve_session_factory(admin.builder.registry)
        except KeyError:
            click.echo(
                "No SQLAlchemy plugin is installed on this admin. createsuperuser "
                "requires an installed SQLAlchemyPlugin with a session factory.",
                err=True,
            )
            return 1

        hasher = Argon2PasswordHasher()
        password_hash = await hasher.hash(password)

        try:
            async with session_factory() as session:
                existing = await session.scalar(select(User).where(User.email == email))
                if existing is not None:
                    click.echo(f"A user with email {email!r} already exists.", err=True)
                    return 1
                session.add(
                    User(
                        email=email,
                        username=username,
                        password_hash=password_hash,
                        is_superuser=True,
                    )
                )
                await session.commit()
        except (OperationalError, ProgrammingError) as exc:
            click.echo(
                f"Database schema error -- has the auth migration been applied? ({exc})",
                err=True,
            )
            return 1

        click.echo(f"Superuser {email!r} created.")
        return 0

    exit_code = asyncio.run(_run())
    if exit_code != 0:
        raise SystemExit(exit_code)


@cli.group()
def permissions() -> None:
    pass


@permissions.command("sync")
@click.argument("target")
def permissions_sync(target: str) -> None:
    """Synchronize TARGET's generated permission catalogue into storage.

    Adds and updates permission rows; never deletes one -- a definition no
    longer generated is marked orphaned instead. Requires the optional
    ``rakit[auth-sqlalchemy]`` distribution.
    """
    with optional_import("rakit_auth_sqlalchemy", extra="auth-sqlalchemy"):
        from rakit_auth_sqlalchemy.rbac import sync_permissions

    from rakit_core.permission_catalogue import generate_permission_catalogue

    admin = _load_admin(target)
    compiled = admin.compiled
    assert compiled is not None
    catalogue = generate_permission_catalogue(
        admin_id=admin.config.admin_id,
        admin_label=admin.config.title,
        resources=tuple(compiled.resources),
    )

    async def _run() -> int:
        try:
            session_factory = await _resolve_session_factory(admin.builder.registry)
        except KeyError:
            click.echo(
                "No SQLAlchemy plugin is installed on this admin. permissions sync "
                "requires an installed SQLAlchemyPlugin with a session factory.",
                err=True,
            )
            return 1

        async with session_factory() as session:
            result = await sync_permissions(session, catalogue)
            await session.commit()

        click.echo(f"added={result.added} updated={result.updated} orphaned={result.orphaned}")
        return 0

    exit_code = asyncio.run(_run())
    if exit_code != 0:
        raise SystemExit(exit_code)
