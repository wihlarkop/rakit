from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .model import FileDisposition, InitConfig, InitMode, PlannedFile, ScaffoldPlan
from .render import dependency_action_for, guidance_for, render_scaffold_files


class ScaffoldPlanError(ValueError):
    """Expected user-facing failure while planning scaffold changes."""


class ScaffoldConflictError(ScaffoldPlanError):
    def __init__(self, paths: tuple[Path, ...]) -> None:
        self.paths = paths
        joined = ", ".join(str(path) for path in paths)
        super().__init__(f"Generated path conflicts with existing content: {joined}")


def build_scaffold_plan(config: InitConfig) -> ScaffoldPlan:
    return ScaffoldPlan(
        config=config,
        files=render_scaffold_files(config),
        dependency_action=dependency_action_for(config),
        guidance=guidance_for(config),
    )


def _planned_paths(plan: ScaffoldPlan) -> frozenset[Path]:
    return frozenset(item.path.resolve(strict=False) for item in plan.files)


def _planned_directory_paths(plan: ScaffoldPlan) -> frozenset[Path]:
    directories: set[Path] = set()
    target = plan.config.target.resolve(strict=False)
    for item in plan.files:
        parent = item.path.resolve(strict=False).parent
        while parent == target or target in parent.parents:
            directories.add(parent)
            if parent == target:
                break
            parent = parent.parent
    return frozenset(directories)


def _ensure_new_target_contains_only_planned_content(plan: ScaffoldPlan) -> None:
    target = plan.config.target.resolve(strict=False)
    if not target.exists():
        return
    if not target.is_dir():
        raise ScaffoldPlanError(f"New-project target is not a directory: {target}")

    planned_files = _planned_paths(plan)
    planned_directories = _planned_directory_paths(plan)
    unmanaged: list[Path] = []
    for path in target.rglob("*"):
        if path.is_symlink():
            unmanaged.append(path)
            continue
        resolved = path.resolve(strict=False)
        if path.is_dir() and resolved in planned_directories:
            continue
        if path.is_file() and resolved in planned_files:
            continue
        unmanaged.append(path)

    if unmanaged:
        preview = ", ".join(str(path.relative_to(target)) for path in unmanaged[:5])
        if len(unmanaged) > 5:
            preview += ", ..."
        raise ScaffoldPlanError(
            "New-project target contains content not owned by this scaffold: " + preview
        )


def _has_incompatible_parent(path: Path, *, target: Path) -> bool:
    parent = path.parent
    stop = target.parent
    while parent != stop:
        if parent.is_symlink():
            return True
        if parent.exists() and not parent.is_dir():
            return True
        if parent == target:
            break
        parent = parent.parent
    return False


def _classify_file(item: PlannedFile, *, target: Path) -> PlannedFile:
    path = item.path
    if _has_incompatible_parent(path, target=target):
        return replace(item, disposition=FileDisposition.CONFLICT)
    if path.is_symlink():
        return replace(item, disposition=FileDisposition.CONFLICT)
    if not path.exists():
        return replace(item, disposition=FileDisposition.CREATE)
    if not path.is_file():
        return replace(item, disposition=FileDisposition.CONFLICT)
    try:
        equivalent = path.read_bytes() == item.content.encode("utf-8")
    except OSError:
        return replace(item, disposition=FileDisposition.CONFLICT)
    disposition = FileDisposition.SATISFIED if equivalent else FileDisposition.CONFLICT
    return replace(item, disposition=disposition)


def classify_plan(plan: ScaffoldPlan) -> ScaffoldPlan:
    if plan.config.mode is InitMode.NEW:
        _ensure_new_target_contains_only_planned_content(plan)

    target = plan.config.target.resolve(strict=False)
    files = tuple(_classify_file(item, target=target) for item in plan.files)
    classified = replace(plan, files=files)
    conflicts = tuple(item.path for item in files if item.disposition is FileDisposition.CONFLICT)
    if conflicts:
        raise ScaffoldConflictError(conflicts)
    return classified


__all__ = [
    "ScaffoldConflictError",
    "ScaffoldPlanError",
    "build_scaffold_plan",
    "classify_plan",
]
