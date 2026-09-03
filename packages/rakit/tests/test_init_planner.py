from pathlib import Path

from rakit.scaffold.model import InitConfig, InitMode, ServerAdapter, StarterTemplate
from rakit.scaffold.planner import build_scaffold_plan


def _new_config(
    tmp_path: Path,
    *,
    template: StarterTemplate = StarterTemplate.STANDARD,
    server: ServerAdapter = ServerAdapter.UVICORN,
    install: bool = True,
) -> InitConfig:
    target = tmp_path / "demo-admin"
    return InitConfig(
        mode=InitMode.NEW,
        target=target,
        distribution_name="demo-admin",
        import_package="demo_admin",
        module_root=target / "src" / "demo_admin",
        template=template,
        server=server,
        install_dependencies=install,
        dry_run=False,
    )


def test_standard_uvicorn_plan_contains_modern_starter_surface(tmp_path: Path) -> None:
    plan = build_scaffold_plan(_new_config(tmp_path))
    relative = {item.path.relative_to(plan.config.target) for item in plan.files}

    assert Path(".env.example") in relative
    assert Path("var/.gitkeep") in relative
    assert Path("src/demo_admin/app.py") in relative
    assert Path("src/demo_admin/bootstrap.py") in relative
    assert Path("src/demo_admin/db.py") in relative
    assert Path("src/demo_admin/models.py") in relative
    assert Path("src/demo_admin/resources.py") in relative
    assert plan.dependency_action is not None
    assert plan.dependency_action.argv == ("uv", "sync")

    pyproject = next(item.content for item in plan.files if item.path.name == "pyproject.toml")
    resources = next(item.content for item in plan.files if item.path.name == "resources.py")
    assert '"rakit[standard,uvicorn]"' in pyproject
    assert '"aiosqlite"' in pyproject
    assert "ResourceWriteDefinition" in resources
    assert 'writable_fields=("name", "description", "enabled")' in resources


def test_minimal_granian_plan_omits_persistence_auth_and_storage(tmp_path: Path) -> None:
    plan = build_scaffold_plan(
        _new_config(
            tmp_path,
            template=StarterTemplate.MINIMAL,
            server=ServerAdapter.GRANIAN,
        )
    )
    relative = {item.path.relative_to(plan.config.target) for item in plan.files}

    assert Path("src/demo_admin/app.py") in relative
    assert Path("src/demo_admin/db.py") not in relative
    assert Path("src/demo_admin/bootstrap.py") not in relative
    assert Path(".env.example") not in relative

    pyproject = next(item.content for item in plan.files if item.path.name == "pyproject.toml")
    assert '"rakit[granian]"' in pyproject
    assert "sqlalchemy" not in pyproject
    assert "auth-sqlalchemy" not in pyproject
    assert "storage-local" not in pyproject


def test_standard_granian_uses_current_explicit_extra_names(tmp_path: Path) -> None:
    plan = build_scaffold_plan(_new_config(tmp_path, server=ServerAdapter.GRANIAN))
    pyproject = next(item.content for item in plan.files if item.path.name == "pyproject.toml")

    assert '"rakit[standard,granian]"' in pyproject
    assert '"aiosqlite"' in pyproject


def test_existing_standard_plan_is_additive_and_isolated(tmp_path: Path) -> None:
    module_root = tmp_path / "src" / "host_app" / "rakit_admin"
    config = InitConfig(
        mode=InitMode.EXISTING,
        target=tmp_path,
        distribution_name=None,
        import_package="host_app.rakit_admin",
        module_root=module_root,
        template=StarterTemplate.STANDARD,
        server=ServerAdapter.UVICORN,
        install_dependencies=False,
        dry_run=False,
        host_package="host_app",
        host_framework="fastapi",
    )

    plan = build_scaffold_plan(config)

    assert all(module_root in item.path.parents or item.path == module_root for item in plan.files)
    assert not any(item.path == tmp_path / ".env.example" for item in plan.files)
    assert not any(item.path == tmp_path / ".gitignore" for item in plan.files)
    assert plan.dependency_action is None
    assert any("No host entrypoint" in line for line in plan.guidance)
    assert any("from rakit import compose_asgi" in line for line in plan.guidance)
    assert any(
        'app = compose_asgi(app, rakit_admin, path="/admin")' in line for line in plan.guidance
    )
    db_source = next(item.content for item in plan.files if item.path.name == "db.py")
    assert '".rakit"' in db_source


def test_existing_standard_install_command_uses_bundle_and_explicit_server(
    tmp_path: Path,
) -> None:
    for server, requirement in (
        (ServerAdapter.UVICORN, "rakit[standard,uvicorn]"),
        (ServerAdapter.GRANIAN, "rakit[standard,granian]"),
    ):
        target = tmp_path / server.value
        module_root = target / "src" / "host_app" / "rakit_admin"
        config = InitConfig(
            mode=InitMode.EXISTING,
            target=target,
            distribution_name=None,
            import_package="host_app.rakit_admin",
            module_root=module_root,
            template=StarterTemplate.STANDARD,
            server=server,
            install_dependencies=True,
            dry_run=True,
            host_package="host_app",
            host_framework=None,
        )

        plan = build_scaffold_plan(config)

        assert plan.dependency_action is not None
        assert plan.dependency_action.argv == ("uv", "add", requirement, "aiosqlite")


def test_planning_is_deterministic(tmp_path: Path) -> None:
    config = _new_config(tmp_path, install=False)

    assert build_scaffold_plan(config) == build_scaffold_plan(config)
