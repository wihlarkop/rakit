from collections.abc import Iterator
from contextlib import contextmanager
from importlib import import_module
from types import ModuleType


class RakitOptionalDependencyError(ImportError):
    pass


def require_module(module_name: str, *, extra: str) -> ModuleType:
    try:
        return import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        raise RakitOptionalDependencyError(
            f"Optional Rakit support is not installed. Install it with:\n\n"
            f'    uv add "rakit[{extra}]"\n'
        ) from exc


@contextmanager
def optional_import(module_name: str, *, extra: str) -> Iterator[None]:
    """Wrap a static ``from <optional_package> import ...`` statement so a
    missing optional distribution raises a friendly, actionable
    ``RakitOptionalDependencyError`` instead of a bare ``ModuleNotFoundError``
    -- while a transitive dependency of an INSTALLED optional package that's
    itself missing still propagates unchanged (matching the same safety
    property as ``require_module``).

    Usage::

        with optional_import("rakit_server_uvicorn", extra="server-uvicorn"):
            from rakit_server_uvicorn.server import UvicornServer

    This preserves full static typing for the imported names (a real import
    statement, not a dynamic ``importlib.import_module`` call), unlike
    ``require_module``, which is for cases where you only need the module
    object itself and don't need static typing on its contents.
    """
    try:
        yield
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        raise RakitOptionalDependencyError(
            f"Optional Rakit support is not installed. Install it with:\n\n"
            f'    uv add "rakit[{extra}]"\n'
        ) from exc
