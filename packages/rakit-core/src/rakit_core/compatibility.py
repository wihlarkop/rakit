from importlib import metadata

from .errors import ErrorCode, RakitError


def validate_official_package_versions(package_names: tuple[str, ...]) -> str | None:
    installed: dict[str, str] = {}
    for name in package_names:
        try:
            installed[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue

    unique = set(installed.values())
    if len(unique) > 1:
        raise RakitError(
            code=ErrorCode.CONFIG_VERSION_MISMATCH,
            message="Official Rakit packages must use the same release version.",
            status_code=500,
            details={"installed": installed},
        )
    return next(iter(unique), None)
