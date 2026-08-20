"""Runnable private local-storage example.

Run with::

    uv run python -m examples.storage.main

The example deliberately exercises the backend contract directly so it stays
independent from authentication and persistence examples.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from rakit.core import ApplicationBuilder
from rakit.storage import FileStorage, StoredFile, TemporaryUpload
from rakit.storage.local import LocalStorage, LocalStoragePlugin


async def _bytes_stream(payload: bytes) -> AsyncIterator[bytes]:
    midpoint = max(1, len(payload) // 2)
    yield payload[:midpoint]
    if midpoint < len(payload):
        yield payload[midpoint:]


def upload(name: str, payload: bytes, content_type: str) -> TemporaryUpload:
    return TemporaryUpload(
        original_name=name,
        content_type=content_type,
        declared_size=len(payload),
        stream=lambda: _bytes_stream(payload),
    )


async def run_demo(root: Path) -> tuple[StoredFile, bytes]:
    """Store, read, resolve private access, and remove one sample document."""

    documents = LocalStorage(
        storage_id="documents",
        root=root / "documents",
        allowed_extensions={".txt", ".pdf"},
    )
    avatars = LocalStorage(
        storage_id="avatars",
        root=root / "avatars",
        allowed_extensions={".png", ".jpg"},
    )
    builder = ApplicationBuilder(admin_id="storage-demo")
    builder.install(LocalStoragePlugin(storages=(documents, avatars)))

    payload = b"Rakit private storage example\n"
    async with builder.registry.application_scope() as services:
        storage = services.require(FileStorage, name="documents")
        stored = await storage.save(
            upload("notes.txt", payload, "text/plain"),
            prefix="demo",
            max_size=1024,
        )
        access = await storage.resolve_access(stored)
        assert access.public is False
        assert access.url is None
        loaded = b"".join([chunk async for chunk in storage.open(stored)])
        await storage.delete(stored)

    return stored, loaded


async def main() -> None:
    root = Path(".rakit-example-storage")
    stored, loaded = await run_demo(root)
    print(f"stored key: {stored.key}")
    print(f"checksum: {stored.checksum}")
    print(f"read back: {loaded.decode().strip()}")
    print("object deleted after the demo")


if __name__ == "__main__":
    asyncio.run(main())
