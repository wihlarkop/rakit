from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import import_module
from types import ModuleType

from ._install import InstallExtra, format_uv_add_command


class RakitOptionalDependencyError(ImportError):
    pass


@dataclass(frozen=True, slots=True)
class OptionalDependency:
    extra: InstallExtra
    label: str


def _missing_message(dependency: OptionalDependency) -> str:
    return (
        f"{dependency.label} support is not installed.\n\n"
        "Install it with:\n"
        f"    {format_uv_add_command(dependency.extra)}\n"
    )


def require_module(module_name: str, *, dependency: OptionalDependency) -> ModuleType:
    try:
        return import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        raise RakitOptionalDependencyError(_missing_message(dependency)) from exc


@contextmanager
def optional_import(
    module_name: str,
    *,
    dependency: OptionalDependency,
) -> Iterator[None]:
    """Guard a statically typed import of an optional Rakit implementation.

    A missing top-level implementation package becomes an actionable
    ``RakitOptionalDependencyError``. Missing transitive dependencies from an
    installed implementation propagate unchanged so a broken adapter is not
    misdiagnosed as an uninstalled Rakit extra.
    """
    try:
        yield
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        raise RakitOptionalDependencyError(_missing_message(dependency)) from exc


__all__ = [
    "OptionalDependency",
    "RakitOptionalDependencyError",
    "optional_import",
    "require_module",
]
