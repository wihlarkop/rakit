"""Rakit plugin for named local storage backends."""

from collections.abc import Iterable

from rakit_core.compiler import ApplicationBuilder
from rakit_core.di import ServiceScope
from rakit_storage import FileStorage

from .storage import LocalStorage


class LocalStoragePlugin:
    """Register one or more local backends as named ``FileStorage`` services."""

    plugin_id = "storage-local"

    def __init__(self, *, storages: Iterable[LocalStorage]) -> None:
        configured = tuple(storages)
        if not configured:
            raise ValueError("LocalStoragePlugin requires at least one storage")
        storage_ids = tuple(storage.storage_id for storage in configured)
        if len(set(storage_ids)) != len(storage_ids):
            raise ValueError("Duplicate local storage id")
        self._storages = configured

    @property
    def storages(self) -> tuple[LocalStorage, ...]:
        return self._storages

    def configure(self, builder: ApplicationBuilder) -> None:
        for storage in self._storages:
            builder.registry.add_value(
                FileStorage,
                storage,
                scope=ServiceScope.APPLICATION,
                name=storage.storage_id,
            )


__all__ = ["LocalStoragePlugin"]
