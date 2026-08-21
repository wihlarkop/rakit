from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .plugin import LocalStoragePlugin as LocalStoragePlugin
    from .storage import LocalStorage as LocalStorage

__version__ = "0.1.0a1"

__all__ = ["LocalStorage", "LocalStoragePlugin", "__version__"]


def __getattr__(name: str) -> object:
    if name == "LocalStorage":
        from .storage import LocalStorage

        return LocalStorage
    if name == "LocalStoragePlugin":
        from .plugin import LocalStoragePlugin

        return LocalStoragePlugin
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
