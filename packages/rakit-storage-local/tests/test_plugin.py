from pathlib import Path

import pytest
from rakit_core.compiler import ApplicationBuilder
from rakit_storage import FileStorage
from rakit_storage_local import LocalStorage, LocalStoragePlugin


@pytest.mark.anyio
async def test_plugin_registers_multiple_named_local_storages(tmp_path: Path) -> None:
    documents = LocalStorage(storage_id="documents", root=tmp_path / "documents")
    avatars = LocalStorage(storage_id="avatars", root=tmp_path / "avatars")
    builder = ApplicationBuilder(admin_id="operations")

    builder.install(LocalStoragePlugin(storages=(documents, avatars)))

    async with builder.registry.application_scope() as resolver:
        assert resolver.require(FileStorage, name="documents") is documents
        assert resolver.require(FileStorage, name="avatars") is avatars


def test_plugin_rejects_duplicate_storage_ids(tmp_path: Path) -> None:
    first = LocalStorage(storage_id="documents", root=tmp_path / "one")
    second = LocalStorage(storage_id="documents", root=tmp_path / "two")

    with pytest.raises(ValueError, match="Duplicate local storage id"):
        LocalStoragePlugin(storages=(first, second))


def test_plugin_requires_at_least_one_storage() -> None:
    with pytest.raises(ValueError, match="at least one"):
        LocalStoragePlugin(storages=())
