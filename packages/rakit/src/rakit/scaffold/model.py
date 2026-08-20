from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class InitMode(StrEnum):
    NEW = "new"
    EXISTING = "existing"


class StarterTemplate(StrEnum):
    STANDARD = "standard"
    MINIMAL = "minimal"


class ServerAdapter(StrEnum):
    UVICORN = "uvicorn"
    GRANIAN = "granian"


class FileDisposition(StrEnum):
    CREATE = "create"
    SATISFIED = "satisfied"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class PackageResolution:
    host_package: str | None
    module_package: str
    module_root: Path


@dataclass(frozen=True, slots=True)
class InitConfig:
    mode: InitMode
    target: Path
    distribution_name: str | None
    import_package: str
    module_root: Path
    template: StarterTemplate
    server: ServerAdapter
    install_dependencies: bool
    dry_run: bool
    host_package: str | None = None
    host_framework: str | None = None


@dataclass(frozen=True, slots=True)
class PlannedFile:
    path: Path
    content: str
    disposition: FileDisposition = FileDisposition.CREATE


@dataclass(frozen=True, slots=True)
class DependencyAction:
    argv: tuple[str, ...]
    cwd: Path


@dataclass(frozen=True, slots=True)
class ScaffoldPlan:
    config: InitConfig
    files: tuple[PlannedFile, ...]
    dependency_action: DependencyAction | None
    guidance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ApplyResult:
    created: tuple[Path, ...]
    satisfied: tuple[Path, ...]
    dependency_command: tuple[str, ...] | None
