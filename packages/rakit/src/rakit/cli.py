import importlib

import click


def load_object(spec: str) -> object:
    module_name, attribute = spec.split(":", 1)
    return getattr(importlib.import_module(module_name), attribute)


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.argument("target")
def check(target: str) -> None:
    compiled = load_object(target).compile()  # ty: ignore[unresolved-attribute]
    click.echo("Rakit configuration is valid.")
    click.echo(f"Routes: {len(compiled.routes)}")
    click.echo(f"Plugins: {len(compiled.plugins)}")


@cli.command()
@click.argument("target")
def routes(target: str) -> None:
    for route in load_object(target).compile().routes:  # ty: ignore[unresolved-attribute]
        click.echo(f"{','.join(route.methods):8} {route.path:30} {route.route_name}")
