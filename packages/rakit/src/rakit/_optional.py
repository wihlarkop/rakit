from importlib import import_module
from types import ModuleType


class RakitOptionalDependencyError(ImportError):
    pass


def require_module(module_name: str, *, extra: str) -> ModuleType:
    try:
        return import_module(module_name)
    except ModuleNotFoundError as exc:
        raise RakitOptionalDependencyError(
            f"Optional Rakit support is not installed. Install it with:\n\n"
            f'    uv add "rakit[{extra}]"\n'
        ) from exc
