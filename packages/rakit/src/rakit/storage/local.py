from .._optional import optional_import

with optional_import("rakit_storage_local", extra="storage-local"):
    import rakit_storage_local  # noqa: F401

from rakit_storage_local import LocalStorage, LocalStoragePlugin

__all__ = ["LocalStorage", "LocalStoragePlugin"]
