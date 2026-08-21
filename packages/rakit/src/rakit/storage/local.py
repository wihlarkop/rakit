from .._install import InstallExtra
from .._optional import OptionalDependency, optional_import

_DEPENDENCY = OptionalDependency(
    extra=InstallExtra.STORAGE_LOCAL,
    label="Local storage",
)

with optional_import("rakit_storage_local", dependency=_DEPENDENCY):
    import rakit_storage_local  # noqa: F401

from rakit_storage_local import LocalStorage, LocalStoragePlugin

__all__ = ["LocalStorage", "LocalStoragePlugin"]
