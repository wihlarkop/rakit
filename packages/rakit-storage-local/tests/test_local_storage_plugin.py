from pathlib import Path

import pytest
from rakit_core.compiler import ApplicationBuilder
from rakit_storage import FileStorage
from rakit_storage_local import LocalStorage, LocalStoragePlugin
from rakit_storage_local.discovery import STORAGE_LOCAL_INTEGRATION


@pytest.mark.anyio
async def test_plugin_registers_multiple_named_local_storages(tmp_path: Path) -> None:
    documents = LocalStorage(storage_id="documents", root=tmp_path / "documents")
    avatars = LocalStorage(storage_id="avatars", root=tmp_path / "avatars")
    builder = ApplicationBuilder(admin_id="operations")

    builder.install(LocalStoragePlugin(storages=(documents, avatars)))

    async with builder.registry.application_scope() as resolver:
        assert resolver.require(FileStorage, name="documents") is documents
        assert resolver.require(FileStorage, name="avatars") is avatars
    assert tuple(item.integration_id for item in builder.configured_integrations) == (
        "storage.local",
    )


def test_local_storage_discovery_descriptor_is_stable() -> None:
    assert STORAGE_LOCAL_INTEGRATION.integration_id == "storage.local"
    assert STORAGE_LOCAL_INTEGRATION.category == "storage"
    assert STORAGE_LOCAL_INTEGRATION.display_name == "Local storage"
    assert STORAGE_LOCAL_INTEGRATION.advertised_capabilities.names == ()


def test_plugin_rejects_duplicate_storage_ids(tmp_path: Path) -> None:
    first = LocalStorage(storage_id="documents", root=tmp_path / "one")
    second = LocalStorage(storage_id="documents", root=tmp_path / "two")

    with pytest.raises(ValueError, match="Duplicate local storage id"):
        LocalStoragePlugin(storages=(first, second))


def test_plugin_requires_at_least_one_storage() -> None:
    with pytest.raises(ValueError, match="at least one"):
        LocalStoragePlugin(storages=())
