from .detection import (
    PackageResolutionRequired,
    ScaffoldDetectionError,
    detect_host_framework,
    normalize_distribution_name,
    resolve_existing_package,
    validate_package_name,
)
from .model import (
    ApplyResult,
    DependencyAction,
    FileDisposition,
    InitConfig,
    InitMode,
    PackageResolution,
    PlannedFile,
    ScaffoldPlan,
    ServerAdapter,
    StarterTemplate,
)
from .render import (
    dependency_action_for,
    dependency_command_for,
    guidance_for,
    render_scaffold_files,
)

__all__ = [
    "ApplyResult",
    "DependencyAction",
    "FileDisposition",
    "InitConfig",
    "InitMode",
    "PackageResolution",
    "PackageResolutionRequired",
    "PlannedFile",
    "ScaffoldDetectionError",
    "ScaffoldPlan",
    "ServerAdapter",
    "StarterTemplate",
    "dependency_action_for",
    "dependency_command_for",
    "detect_host_framework",
    "guidance_for",
    "normalize_distribution_name",
    "render_scaffold_files",
    "resolve_existing_package",
    "validate_package_name",
]
