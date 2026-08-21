from .._install import InstallExtra
from .._optional import OptionalDependency, optional_import

with optional_import(
    "rakit_storage_local",
    dependency=OptionalDependency(
        extra=InstallExtra.STORAGE_LOCAL,
        label="Local storage",
    ),
):
    import rakit_storage_local  # noqa: F401

from rakit_storage_local import LocalStorage, LocalStoragePlugin

__all__ = ["LocalStorage", "LocalStoragePlugin"]
