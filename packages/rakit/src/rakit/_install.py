from __future__ import annotations

from enum import Enum


class InstallExtra(str, Enum):
    STANDARD = "standard"
    SQLALCHEMY = "sqlalchemy"
    AUTH_SQLALCHEMY = "auth-sqlalchemy"
    STORAGE_LOCAL = "storage-local"
    UVICORN = "uvicorn"
    GRANIAN = "granian"


_EXTRA_ORDER = {
    InstallExtra.STANDARD: 0,
    InstallExtra.SQLALCHEMY: 1,
    InstallExtra.AUTH_SQLALCHEMY: 2,
    InstallExtra.STORAGE_LOCAL: 3,
    InstallExtra.UVICORN: 4,
    InstallExtra.GRANIAN: 5,
}


def _normalize_extras(extras: tuple[InstallExtra, ...]) -> tuple[InstallExtra, ...]:
    if any(not isinstance(extra, InstallExtra) for extra in extras):
        raise TypeError("Rakit install extras must use InstallExtra values")
    return tuple(sorted(set(extras), key=_EXTRA_ORDER.__getitem__))


def rakit_requirement(*extras: InstallExtra) -> str:
    normalized = _normalize_extras(extras)
    if not normalized:
        return "rakit"
    joined = ",".join(extra.value for extra in normalized)
    return f"rakit[{joined}]"


def uv_add_command(
    *extras: InstallExtra,
    packages: tuple[str, ...] = (),
) -> tuple[str, ...]:
    return ("uv", "add", rakit_requirement(*extras), *packages)


def format_uv_add_command(
    *extras: InstallExtra,
    packages: tuple[str, ...] = (),
) -> str:
    requirement = rakit_requirement(*extras)
    suffix = "" if not packages else " " + " ".join(packages)
    return f'uv add "{requirement}"{suffix}'


__all__ = [
    "InstallExtra",
    "format_uv_add_command",
    "rakit_requirement",
    "uv_add_command",
]
