"""Tests for the reusable FileStorage contract suite.

These tests prove the suite itself is sound: a well-behaved reference storage
adapter passes the whole suite, and an intentionally broken fake that lets the
browser filename control the object key is detected.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator

import pytest
from rakit_core.testing import StorageContractSuite
from rakit_storage import FileAccess, StoredFile, TemporaryUpload


def _prefix_for(prefix: str | None) -> str | None:
    if not prefix:
        return None
    return prefix


class MemoryStorage:
    """A simple in-memory reference implementation of the ``FileStorage`` protocol."""

    def __init__(self, storage_id: str = "memory") -> None:
        self.storage_id = storage_id
        self._objects: dict[str, bytes] = {}

    def _path_for(self, file: StoredFile) -> str:
        if file.storage_id != self.storage_id:
            raise ValueError(f"foreign storage_id {file.storage_id!r}")
        return file.key

    async def save(
        self,
        upload: TemporaryUpload,
        *,
        prefix: str | None = None,
        max_size: int | None = None,
        operation_context: object = None,
    ) -> StoredFile:
        if max_size is not None and max_size < 0:
            raise ValueError("max_size must not be negative")
        if (
            upload.declared_size is not None
            and max_size is not None
            and upload.declared_size > max_size
        ):
            raise ValueError("upload exceeds the configured size limit")
        namespace = _prefix_for(prefix)
        key = f"{namespace}/{uuid.uuid4().hex}" if namespace else uuid.uuid4().hex
        chunks: list[bytes] = []
        size = 0
        digest = hashlib.sha256()
        async for chunk in upload.stream():
            if not isinstance(chunk, bytes):
                raise TypeError("upload stream must yield bytes")
            if not chunk:
                continue
            size += len(chunk)
            if max_size is not None and size > max_size:
                raise ValueError("upload exceeds the configured size limit")
            digest.update(chunk)
            chunks.append(chunk)
        payload = b"".join(chunks)
        self._objects[key] = payload
        return StoredFile(
            storage_id=self.storage_id,
            key=key,
            original_name=upload.original_name,
            content_type=upload.content_type,
            size=size,
            checksum=f"sha256:{digest.hexdigest()}",
        )

    def open(self, file: StoredFile, *, operation_context: object = None) -> AsyncIterator[bytes]:
        key = self._path_for(file)
        payload = self._objects.get(key)

        async def iterate() -> AsyncIterator[bytes]:
            if payload is None:
                raise FileNotFoundError(key)
            yield payload

        return iterate()

    async def delete(self, file: StoredFile, *, operation_context: object = None) -> None:
        key = self._path_for(file)
        self._objects.pop(key, None)

    async def resolve_access(
        self,
        file: StoredFile,
        *,
        operation_context: object = None,
    ) -> FileAccess:
        self._path_for(file)
        return FileAccess()


class MemoryStorageContract(StorageContractSuite):
    async def make_storage(self) -> MemoryStorage:
        return MemoryStorage()


@pytest.mark.anyio
async def test_reference_storage_passes_the_entire_contract_suite() -> None:
    await MemoryStorageContract().run_all()


class BrokenStorageThatUsesBrowserFilename(MemoryStorage):
    """An adapter whose save() lets the browser filename control the key."""

    async def save(
        self,
        upload: TemporaryUpload,
        *,
        prefix: str | None = None,
        max_size: int | None = None,
        operation_context: object = None,
    ) -> StoredFile:
        namespace = _prefix_for(prefix)
        key = f"{namespace}/{upload.original_name}" if namespace else upload.original_name
        chunks: list[bytes] = []
        async for chunk in upload.stream():
            chunks.append(chunk)
        payload = b"".join(chunks)
        self._objects[key] = payload
        return StoredFile(
            storage_id=self.storage_id,
            key=key,
            original_name=upload.original_name,
            content_type=upload.content_type,
            size=len(payload),
            checksum="unused",
        )


class BrokenStorageContract(StorageContractSuite):
    async def make_storage(self) -> BrokenStorageThatUsesBrowserFilename:
        return BrokenStorageThatUsesBrowserFilename()


@pytest.mark.anyio
async def test_broken_storage_fails_generated_key_safety_contract() -> None:
    suite = BrokenStorageContract()
    with pytest.raises(AssertionError):
        await suite.assert_generated_key_safety()


@pytest.mark.anyio
async def test_broken_storage_still_round_trips_bytes() -> None:
    suite = BrokenStorageContract()
    await suite.assert_save_open_delete_round_trip()
