import importlib
from typing import Protocol

import click
from rakit_core.compiler import CompiledApplication


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


def load_object(spec: str) -> Compilable:
    module_name, attribute = spec.split(":", 1)
    return getattr(importlib.import_module(module_name), attribute)


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
