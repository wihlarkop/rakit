from __future__ import annotations

import keyword
import re
import tomllib
from pathlib import Path
from typing import Any

from .model import PackageResolution

_DISTRIBUTION_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_IGNORED_PACKAGE_DIRS = frozenset(
    {
        ".git",
        ".github",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "build",
        "dist",
        "docs",
        "examples",
        "node_modules",
        "scripts",
        "tests",
        "venv",
    }
)


class ScaffoldDetectionError(ValueError):
    """Expected user-facing failure while detecting scaffold placement."""


class PackageResolutionRequired(ScaffoldDetectionError):
    def __init__(self, *, candidates: tuple[str, ...] = ()) -> None:
        self.candidates = candidates
        if candidates:
            detail = ", ".join(candidates)
            message = f"Multiple package candidates found ({detail}); specify --package."
        else:
            message = "Could not resolve a safe host package; specify --package."
        super().__init__(message)


def _is_valid_import_name(value: str) -> bool:
    return value.isidentifier() and not keyword.iskeyword(value)


def normalize_distribution_name(name: str) -> tuple[str, str]:
    if not name or name != name.strip():
        raise ScaffoldDetectionError("Project name must be a non-empty value without outer spaces.")
    if "/" in name or "\\" in name or name in {".", ".."}:
        raise ScaffoldDetectionError("Project name must not contain path separators or traversal.")
    if not _DISTRIBUTION_RE.fullmatch(name):
        raise ScaffoldDetectionError(
            "Project name may contain letters, numbers, underscores, and hyphens and must start with a letter."
        )

    import_package = name.replace("-", "_")
    if not _is_valid_import_name(import_package):
        raise ScaffoldDetectionError(
            f"Project name {name!r} does not normalize to a safe Python import package."
        )
    return name, import_package


def validate_package_name(name: str) -> str:
    if not name or name != name.strip() or "." in name or "/" in name or "\\" in name:
        raise ScaffoldDetectionError("Package name must be one top-level Python package identifier.")
    if not _is_valid_import_name(name):
        raise ScaffoldDetectionError(f"Package name {name!r} is not a valid Python identifier.")
    return name


def _candidate_packages(directory: Path) -> tuple[str, ...]:
    if not directory.is_dir():
        return ()
    candidates: list[str] = []
    for child in directory.iterdir():
        if not child.is_dir() or child.name in _IGNORED_PACKAGE_DIRS or child.name.startswith("."):
            continue
        if not _is_valid_import_name(child.name):
            continue
        if (child / "__init__.py").is_file():
            candidates.append(child.name)
    return tuple(sorted(candidates))


def _resolution(root: Path, package: str, *, source_root: Path) -> PackageResolution:
    module_root = source_root / package / "rakit_admin"
    return PackageResolution(
        host_package=package,
        module_package=f"{package}.rakit_admin",
        module_root=module_root,
    )


def resolve_existing_package(
    root: Path,
    explicit_package: str | None,
    *,
    interactive: bool,
) -> PackageResolution:
    root = root.resolve()
    if not root.is_dir():
        raise ScaffoldDetectionError(f"Existing-project target does not exist or is not a directory: {root}")

    src_root = root / "src"
    src_candidates = _candidate_packages(src_root)
    flat_candidates = _candidate_packages(root)

    if explicit_package is not None:
        package = validate_package_name(explicit_package)
        if package in src_candidates:
            return _resolution(root, package, source_root=src_root)
        if package in flat_candidates:
            return _resolution(root, package, source_root=root)
        raise ScaffoldDetectionError(
            f"Package {package!r} was not found as a conventional src/ or flat package under {root}."
        )

    if len(src_candidates) == 1:
        return _resolution(root, src_candidates[0], source_root=src_root)
    if len(src_candidates) > 1:
        raise PackageResolutionRequired(candidates=src_candidates)

    if len(flat_candidates) == 1:
        return _resolution(root, flat_candidates[0], source_root=root)
    if len(flat_candidates) > 1:
        raise PackageResolutionRequired(candidates=flat_candidates)

    clearly_flat = (root / "pyproject.toml").is_file() or any(root.glob("*.py"))
    if clearly_flat:
        return PackageResolution(
            host_package=None,
            module_package="rakit_admin",
            module_root=root / "rakit_admin",
        )

    if interactive:
        raise PackageResolutionRequired()
    raise PackageResolutionRequired()


def _collect_dependencies(document: dict[str, Any]) -> tuple[str, ...]:
    dependencies: list[str] = []

    project = document.get("project")
    if isinstance(project, dict):
        direct = project.get("dependencies")
        if isinstance(direct, list):
            dependencies.extend(item for item in direct if isinstance(item, str))
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for values in optional.values():
                if isinstance(values, list):
                    dependencies.extend(item for item in values if isinstance(item, str))

    dependency_groups = document.get("dependency-groups")
    if isinstance(dependency_groups, dict):
        for values in dependency_groups.values():
            if isinstance(values, list):
                dependencies.extend(item for item in values if isinstance(item, str))

    return tuple(dependencies)


def _dependency_name(requirement: str) -> str:
    marker_free = requirement.split(";", 1)[0].strip()
    for separator in ("[", "<", ">", "=", "!", "~", " "):
        marker_free = marker_free.split(separator, 1)[0]
    return marker_free.strip().replace("_", "-").casefold()


def detect_host_framework(pyproject_text: str | None) -> str | None:
    if not pyproject_text:
        return None
    try:
        document = tomllib.loads(pyproject_text)
    except tomllib.TOMLDecodeError:
        return None

    names = {_dependency_name(item) for item in _collect_dependencies(document)}
    if "fastapi" in names:
        return "fastapi"
    if "starlette" in names:
        return "starlette"
    return None
