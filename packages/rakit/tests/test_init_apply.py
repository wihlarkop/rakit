import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from rakit.scaffold.apply import DependencyInstallError, MissingUvError, apply_scaffold_plan
from rakit.scaffold.model import (
    FileDisposition,
    InitConfig,
    InitMode,
    ServerAdapter,
    StarterTemplate,
)
from rakit.scaffold.planner import (
    ScaffoldConflictError,
    ScaffoldPlanError,
    build_scaffold_plan,
    classify_plan,
)


def _config(tmp_path: Path, *, install: bool = False) -> InitConfig:
    target = tmp_path / "demo-admin"
    return InitConfig(
        mode=InitMode.NEW,
        target=target,
        distribution_name="demo-admin",
        import_package="demo_admin",
        module_root=target / "src" / "demo_admin",
        template=StarterTemplate.MINIMAL,
        server=ServerAdapter.UVICORN,
        install_dependencies=install,
        dry_run=False,
    )


def test_classify_and_apply_support_identical_rerun(tmp_path: Path) -> None:
    plan = build_scaffold_plan(_config(tmp_path))
    initial = classify_plan(plan)
    assert {item.disposition for item in initial.files} == {FileDisposition.CREATE}

    result = apply_scaffold_plan(initial)
    assert result.created

    rerun = classify_plan(build_scaffold_plan(_config(tmp_path)))
    assert {item.disposition for item in rerun.files} == {FileDisposition.SATISFIED}
    rerun_result = apply_scaffold_plan(rerun)
    assert rerun_result.created == ()
    assert len(rerun_result.satisfied) == len(rerun.files)


def test_conflicting_generated_file_fails_before_other_writes(tmp_path: Path) -> None:
    config = _config(tmp_path)
    apply_scaffold_plan(classify_plan(build_scaffold_plan(config)))
    pyproject = config.target / "pyproject.toml"
    original_pyproject = pyproject.read_text(encoding="utf-8")
    readme = config.target / "README.md"
    readme.write_text("user-owned replacement\n", encoding="utf-8")

    with pytest.raises(ScaffoldConflictError):
        apply_scaffold_plan(build_scaffold_plan(config))

    assert pyproject.read_text(encoding="utf-8") == original_pyproject
    assert readme.read_text(encoding="utf-8") == "user-owned replacement\n"


def test_new_project_rejects_unmanaged_extra_content(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.target.mkdir()
    (config.target / "user.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(ScaffoldPlanError, match="not owned"):
        classify_plan(build_scaffold_plan(config))

    assert (config.target / "user.txt").read_text(encoding="utf-8") == "keep me"
    assert not (config.target / "pyproject.toml").exists()


def test_missing_uv_is_rejected_before_filesystem_mutation(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path, install=True)
    apply_module = importlib.import_module("rakit.scaffold.apply")
    monkeypatch.setattr(apply_module.shutil, "which", lambda _name: None)

    with pytest.raises(MissingUvError, match="--no-install"):
        apply_scaffold_plan(build_scaffold_plan(config))

    assert not config.target.exists()


def test_dependency_failure_keeps_successfully_created_scaffold(
    tmp_path: Path, monkeypatch
) -> None:
    config = _config(tmp_path, install=True)
    apply_module = importlib.import_module("rakit.scaffold.apply")
    monkeypatch.setattr(apply_module.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(
        apply_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=7),
    )

    with pytest.raises(DependencyInstallError, match="Retry with: uv sync"):
        apply_scaffold_plan(build_scaffold_plan(config))

    assert (config.target / "pyproject.toml").is_file()
    assert (config.target / "src" / "demo_admin" / "app.py").is_file()
