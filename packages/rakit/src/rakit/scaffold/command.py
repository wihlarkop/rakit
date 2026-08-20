from __future__ import annotations

from pathlib import Path

import click

from .apply import ScaffoldApplyError, apply_scaffold_plan
from .detection import (
    PackageResolutionRequired,
    ScaffoldDetectionError,
    detect_host_framework,
    normalize_distribution_name,
    resolve_existing_package,
)
from .model import (
    InitConfig,
    InitMode,
    PackageResolution,
    ScaffoldPlan,
    ServerAdapter,
    StarterTemplate,
)
from .planner import ScaffoldPlanError, build_scaffold_plan, classify_plan

_TEMPLATE_VALUES = tuple(item.value for item in StarterTemplate)
_SERVER_VALUES = tuple(item.value for item in ServerAdapter)


def _choice_or_prompt(
    value: str | None,
    *,
    yes: bool,
    label: str,
    values: tuple[str, ...],
    default: str,
) -> str:
    if value is not None:
        return value
    if yes:
        return default
    return click.prompt(label, type=click.Choice(values), default=default, show_choices=True)


def _install_or_prompt(value: bool | None, *, yes: bool) -> bool:
    if value is not None:
        return value
    if yes:
        return True
    return click.confirm("Install dependencies now?", default=True)


def _read_pyproject(root: Path) -> str | None:
    path = root / "pyproject.toml"
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScaffoldDetectionError(f"Could not read {path}: {exc}") from exc


def _resolve_package_interactively(
    root: Path,
    explicit_package: str | None,
    *,
    yes: bool,
) -> PackageResolution:
    try:
        return resolve_existing_package(root, explicit_package, interactive=not yes)
    except PackageResolutionRequired as exc:
        if yes:
            raise
        if exc.candidates:
            selected = click.prompt(
                "Host package",
                type=click.Choice(exc.candidates),
                show_choices=True,
            )
        else:
            selected = click.prompt("Host package")
        return resolve_existing_package(root, selected, interactive=True)


def _resolved_template_and_server(
    *,
    template_name: str | None,
    server_name: str | None,
    yes: bool,
) -> tuple[StarterTemplate, ServerAdapter]:
    template = StarterTemplate(
        _choice_or_prompt(
            template_name,
            yes=yes,
            label="Starter template",
            values=_TEMPLATE_VALUES,
            default=StarterTemplate.STANDARD.value,
        )
    )
    server = ServerAdapter(
        _choice_or_prompt(
            server_name,
            yes=yes,
            label="Server adapter",
            values=_SERVER_VALUES,
            default=ServerAdapter.UVICORN.value,
        )
    )
    return template, server


def _normalize_config(
    *,
    project_name: str | None,
    existing: Path | None,
    template_name: str | None,
    server_name: str | None,
    package_name: str | None,
    yes: bool,
    install_dependencies: bool | None,
    dry_run: bool,
) -> InitConfig:
    if project_name is not None and existing is not None:
        raise ScaffoldDetectionError("PROJECT_NAME and --existing are mutually exclusive.")
    if existing is None and package_name is not None:
        raise ScaffoldDetectionError("--package is only valid with --existing.")

    if existing is None:
        if project_name is None:
            if yes:
                raise ScaffoldDetectionError("PROJECT_NAME is required when --yes is used.")
            project_name = click.prompt("Project name")
        distribution_name, import_package = normalize_distribution_name(project_name)
        target = (Path.cwd() / distribution_name).resolve()
        template, server = _resolved_template_and_server(
            template_name=template_name,
            server_name=server_name,
            yes=yes,
        )
        install = _install_or_prompt(install_dependencies, yes=yes)
        return InitConfig(
            mode=InitMode.NEW,
            target=target,
            distribution_name=distribution_name,
            import_package=import_package,
            module_root=target / "src" / import_package,
            template=template,
            server=server,
            install_dependencies=install,
            dry_run=dry_run,
        )

    target = existing.expanduser().resolve()
    if not target.is_dir():
        raise ScaffoldDetectionError(
            f"Existing-project target does not exist or is not a directory: {target}"
        )
    pyproject_text = _read_pyproject(target)
    template, server = _resolved_template_and_server(
        template_name=template_name,
        server_name=server_name,
        yes=yes,
    )
    install = _install_or_prompt(install_dependencies, yes=yes)
    if install and pyproject_text is None:
        raise ScaffoldDetectionError(
            "Existing-project dependency installation requires pyproject.toml; "
            "rerun with --no-install to scaffold without dependency mutation."
        )
    resolution = _resolve_package_interactively(target, package_name, yes=yes)
    return InitConfig(
        mode=InitMode.EXISTING,
        target=target,
        distribution_name=None,
        import_package=resolution.module_package,
        module_root=resolution.module_root,
        template=template,
        server=server,
        install_dependencies=install,
        dry_run=dry_run,
        host_package=resolution.host_package,
        host_framework=detect_host_framework(pyproject_text),
    )


def _display_path(path: Path, *, target: Path) -> str:
    try:
        return str(path.relative_to(target))
    except ValueError:
        return str(path)


def _print_plan(plan: ScaffoldPlan) -> None:
    config = plan.config
    click.echo(f"Mode: {config.mode.value}")
    click.echo(f"Target: {config.target}")
    click.echo(f"Package: {config.import_package}")
    click.echo(f"Template: {config.template.value}")
    click.echo(f"Server: {config.server.value}")
    click.echo("Files:")
    for item in plan.files:
        click.echo(
            f"  {item.disposition.value:9} {_display_path(item.path, target=config.target)}"
        )
    if plan.dependency_action is not None:
        click.echo("Dependencies: " + " ".join(plan.dependency_action.argv))
    else:
        click.echo("Dependencies: not run by this invocation")
    click.echo("Next steps:")
    for line in plan.guidance:
        click.echo(f"  {line}")


@click.command("init")
@click.argument("project_name", required=False)
@click.option(
    "--existing",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
    help="Add an isolated Rakit admin module to an existing project.",
)
@click.option(
    "--template",
    "template_name",
    type=click.Choice(_TEMPLATE_VALUES),
    default=None,
    help="Starter bundle. Defaults to standard.",
)
@click.option(
    "--server",
    "server_name",
    type=click.Choice(_SERVER_VALUES),
    default=None,
    help="Server adapter. Defaults to uvicorn.",
)
@click.option("--package", "package_name", default=None, help="Explicit existing host package.")
@click.option("--yes", is_flag=True, help="Accept defaults without prompting.")
@click.option(
    "--install/--no-install",
    "install_dependencies",
    default=None,
    help="Install dependencies with uv after scaffolding.",
)
@click.option("--dry-run", is_flag=True, help="Print the complete plan without mutation.")
def init_command(
    project_name: str | None,
    existing: Path | None,
    template_name: str | None,
    server_name: str | None,
    package_name: str | None,
    yes: bool,
    install_dependencies: bool | None,
    dry_run: bool,
) -> None:
    """Create a Rakit starter or add Rakit safely to an existing project."""

    try:
        config = _normalize_config(
            project_name=project_name,
            existing=existing,
            template_name=template_name,
            server_name=server_name,
            package_name=package_name,
            yes=yes,
            install_dependencies=install_dependencies,
            dry_run=dry_run,
        )
        plan = build_scaffold_plan(config)
        classified = classify_plan(plan)
        if dry_run:
            _print_plan(classified)
            return

        result = apply_scaffold_plan(classified)
    except (ScaffoldDetectionError, ScaffoldPlanError, ScaffoldApplyError) as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(
        f"Scaffold complete: created={len(result.created)} satisfied={len(result.satisfied)}"
    )
    _print_plan(classified)


__all__ = ["init_command"]
