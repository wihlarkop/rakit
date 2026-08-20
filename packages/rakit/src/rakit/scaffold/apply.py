from __future__ import annotations

import shutil
import subprocess
from contextlib import suppress
from pathlib import Path

from .model import ApplyResult, FileDisposition, ScaffoldPlan
from .planner import ScaffoldConflictError, classify_plan


class ScaffoldApplyError(RuntimeError):
    """Expected user-facing failure while applying a scaffold plan."""


class MissingUvError(ScaffoldApplyError):
    pass


class DependencyInstallError(ScaffoldApplyError):
    def __init__(self, argv: tuple[str, ...], returncode: int) -> None:
        self.argv = argv
        self.returncode = returncode
        retry = " ".join(argv)
        super().__init__(
            f"Scaffold files were created, but dependency installation failed with exit code "
            f"{returncode}. Retry with: {retry}"
        )


def _ensure_parent_directories(path: Path, created_directories: list[Path]) -> None:
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent

    if not current.is_dir():
        raise ScaffoldApplyError(f"Cannot create directory beneath non-directory path: {current}")

    for directory in reversed(missing):
        directory.mkdir()
        created_directories.append(directory)


def _cleanup_created_paths(created_files: list[Path], created_directories: list[Path]) -> None:
    for path in reversed(created_files):
        with suppress(OSError):
            path.unlink(missing_ok=True)

    for directory in reversed(created_directories):
        with suppress(OSError):
            directory.rmdir()


def _preflight_uv(plan: ScaffoldPlan) -> None:
    if plan.config.dry_run or plan.dependency_action is None:
        return
    if shutil.which("uv") is None:
        raise MissingUvError(
            "Dependency installation was requested but `uv` is not available. "
            "Install uv or rerun with --no-install."
        )


def apply_scaffold_plan(plan: ScaffoldPlan) -> ApplyResult:
    if plan.config.dry_run:
        raise ScaffoldApplyError("Dry-run plans must not be applied.")

    classified = classify_plan(plan)
    _preflight_uv(classified)

    created_files: list[Path] = []
    created_directories: list[Path] = []
    satisfied: list[Path] = []

    try:
        for item in classified.files:
            if item.disposition is FileDisposition.SATISFIED:
                satisfied.append(item.path)
                continue
            if item.disposition is FileDisposition.CONFLICT:
                raise ScaffoldConflictError((item.path,))

            _ensure_parent_directories(item.path.parent, created_directories)
            with item.path.open("x", encoding="utf-8", newline="") as handle:
                handle.write(item.content)
            created_files.append(item.path)
    except Exception:
        _cleanup_created_paths(created_files, created_directories)
        raise

    dependency_command: tuple[str, ...] | None = None
    action = classified.dependency_action
    if action is not None:
        completed = subprocess.run(action.argv, cwd=action.cwd, check=False)
        dependency_command = action.argv
        if completed.returncode != 0:
            raise DependencyInstallError(action.argv, completed.returncode)

    return ApplyResult(
        created=tuple(created_files),
        satisfied=tuple(satisfied),
        dependency_command=dependency_command,
    )


__all__ = [
    "DependencyInstallError",
    "MissingUvError",
    "ScaffoldApplyError",
    "apply_scaffold_plan",
]
