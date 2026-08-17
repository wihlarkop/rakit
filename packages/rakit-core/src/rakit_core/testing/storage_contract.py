"""Reusable, backend-neutral contract suite for third-party ``FileStorage`` adapters.

The suite drives storage exclusively through the public protocol in
:mod:`rakit_storage.contracts` (``save`` / ``open`` / ``delete`` /
``resolve_access``). It never imports adapter implementation classes.

An adapter author subclasses :class:`StorageContractSuite`, implements
:meth:`StorageContractSuite.make_storage`, and runs the suite from a normal
pytest test::

    class MyContract(StorageContractSuite):
        async def make_storage(self) -> FileStorage:
            return MyStorage()

    @pytest.mark.anyio
    async def test_contract() -> None:
        await MyContract().run_all()

``pytest`` is only required when the suite is actually used from tests; the
package imports cleanly without it.
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import PurePosixPath
from typing import Any, cast

from rakit_storage import FileAccess, FileStorage, StoredFile, TemporaryUpload

from rakit_core.errors import RakitError

with suppress(ImportError):  # pragma: no cover - exercised only without pytest installed
    import pytest as _pytest

_pytest_available = "_pytest" in globals()

__all__ = ["StorageContractSuite"]

_SHA256_PREFIX = "sha256:"
_DRIVE_PREFIX = re.compile(r"^[a-zA-Z]:")


def _skip(message: str) -> None:
    if _pytest_available:
        cast(Any, _pytest).skip(message)
    raise RuntimeError(f"{message} (install pytest to run Rakit contract suites)")


def _upload(
    name: str, payload: bytes, *, content_type: str = "application/octet-stream"
) -> TemporaryUpload:
    async def stream() -> AsyncIterator[bytes]:
        yield payload

    return TemporaryUpload(
        original_name=name,
        content_type=content_type,
        stream=stream,
        declared_size=len(payload),
    )


def _failing_upload(name: str, prefix_bytes: bytes) -> TemporaryUpload:
    """An upload whose stream yields some bytes and then raises."""

    async def stream() -> AsyncIterator[bytes]:
        yield prefix_bytes
        raise OSError("simulated stream failure")

    return TemporaryUpload(
        original_name=name,
        content_type="application/octet-stream",
        stream=stream,
        declared_size=len(prefix_bytes) + 1,
    )


def _is_relative_posix_key(value: str) -> bool:
    if not value or value.startswith("/") or "\\" in value or "\x00" in value:
        return False
    if _DRIVE_PREFIX.match(value):
        return False
    if any(part in {"", ".", ".."} for part in value.split("/")):
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and str(path) == value


class StorageContractSuite(ABC):
    """Backend-neutral assertion suite for a ``FileStorage`` adapter.

    Required hook
    -------------
    ``async make_storage()``
        Return a fresh, isolated ``FileStorage`` backend. Called once per
        suite instance and cached. A fresh backend (for example a new
        temporary directory) keeps assertions independent.
    """

    _storage: FileStorage | None = None

    @abstractmethod
    async def make_storage(self) -> FileStorage:
        """Return a fresh, isolated ``FileStorage`` backend."""

    async def storage(self) -> FileStorage:
        if self._storage is None:
            self._storage = await self.make_storage()
        return self._storage

    async def save(
        self,
        payload: bytes,
        *,
        name: str = "contract.txt",
        prefix: str | None = None,
        max_size: int | None = None,
        content_type: str = "text/plain",
    ) -> StoredFile:
        storage = await self.storage()
        return await storage.save(
            _upload(name, payload, content_type=content_type),
            prefix=prefix,
            max_size=max_size,
        )

    async def assert_save_open_delete_round_trip(self) -> None:
        """Saved bytes stream back identically and delete removes the object."""
        storage = await self.storage()
        payload = b"contract round trip payload"
        stored = await self.save(payload)
        assert isinstance(stored, StoredFile)
        assert stored.storage_id == storage.storage_id

        chunks = [chunk async for chunk in storage.open(stored)]
        assert b"".join(chunks) == payload, "open must stream back exactly the saved bytes"

        result = await storage.delete(stored)
        assert result is None
        await storage.delete(stored)  # delete is idempotent

        deleted_chunks: list[bytes] = []
        deleted_error: Exception | None = None
        try:
            async for chunk in storage.open(stored):
                deleted_chunks.append(chunk)
        except Exception as exc:
            deleted_error = exc
        assert deleted_error is not None or not deleted_chunks, (
            "open must fail (or yield nothing) after delete"
        )

    async def assert_generated_key_safety(self) -> None:
        """Keys are backend-generated, portable, and never controlled by the browser filename."""
        try:
            stored = await self.save(b"payload", name="../../outside/config.py", prefix="documents")
        except Exception as exc:
            raise AssertionError(
                "storage must never produce a StoredFile with an unsafe key"
            ) from exc
        assert _is_relative_posix_key(stored.key), f"unsafe generated key: {stored.key!r}"
        assert stored.key.startswith("documents/"), "prefix must be honored"
        assert "outside" not in stored.key
        assert not stored.key.endswith(".py"), "the browser filename must never control the key"

        plain = await self.save(b"payload", name="report.txt")
        assert _is_relative_posix_key(plain.key), f"unsafe generated key: {plain.key!r}"
        assert "report" not in plain.key, "the browser filename must not appear in the key"

    async def assert_size_and_checksum(self) -> None:
        """Reported size and checksum describe the exact stored bytes."""
        payload = b"checksum payload bytes"
        stored = await self.save(payload)
        assert stored.size == len(payload)
        assert stored.checksum.strip(), "checksum must not be blank"
        if stored.checksum.startswith(_SHA256_PREFIX):
            digest = stored.checksum[len(_SHA256_PREFIX) :]
            assert digest == hashlib.sha256(payload).hexdigest(), (
                "sha256 checksum must match the stored bytes"
            )

    async def assert_collision_avoidance(self) -> None:
        """Two saves with the same browser filename must not collide."""
        payload_a = b"first version"
        payload_b = b"second version"
        first = await self.save(payload_a, name="same.txt")
        second = await self.save(payload_b, name="same.txt")
        assert first.key != second.key, "same-filename saves must produce distinct keys"
        chunks_a = [chunk async for chunk in (await self.storage()).open(first)]
        chunks_b = [chunk async for chunk in (await self.storage()).open(second)]
        assert b"".join(chunks_a) == payload_a
        assert b"".join(chunks_b) == payload_b

    async def assert_cleanup_semantics(self) -> None:
        """Failed uploads leave no partial object and size limits fail before the stream."""
        storage = await self.storage()
        try:
            await storage.save(
                _failing_upload("partial.bin", b"partial"),
                prefix="demo",
            )
        except OSError:
            pass
        else:
            raise AssertionError("a failing upload stream must propagate its failure")

        recovered = await self.save(b"clean", name="partial.bin", prefix="demo")
        chunks = [chunk async for chunk in storage.open(recovered)]
        assert b"".join(chunks) == b"clean", (
            "a later save must not be corrupted by a previous failed upload"
        )

        consumed = False
        payload = b"x" * 16

        async def watched_stream() -> AsyncIterator[bytes]:
            nonlocal consumed
            consumed = True
            yield payload

        oversize = TemporaryUpload(
            original_name="oversize.txt",
            content_type="text/plain",
            stream=watched_stream,
            declared_size=100,
        )
        try:
            await storage.save(oversize, max_size=10)
        except ValueError:
            pass
        else:
            raise AssertionError("a declared size above max_size must be rejected")
        assert consumed is False, "max_size must reject before the stream is consumed"

    async def assert_access_private_by_default(self) -> None:
        """Access resolution defaults to private with no direct URL."""
        storage = await self.storage()
        stored = await self.save(b"private payload")
        access = await storage.resolve_access(stored)
        assert isinstance(access, FileAccess)
        assert access.public is False, "storage must be private by default"

    async def assert_access_rejects_foreign_descriptors(self) -> None:
        """A descriptor owned by another storage id must be rejected."""
        storage = await self.storage()
        foreign = StoredFile(
            storage_id="another-storage",
            key="safe/key.txt",
            original_name="file.txt",
            content_type="text/plain",
            size=1,
            checksum="unused",
        )
        for operation in (
            lambda: storage.open(foreign),
            lambda: storage.delete(foreign),
            lambda: storage.resolve_access(foreign),
        ):
            try:
                result = operation()
                if hasattr(result, "__aiter__"):
                    async for _ in result:
                        break
                else:
                    await result
            except (ValueError, RakitError):
                continue
            except Exception:
                continue
            raise AssertionError("a foreign storage descriptor must be rejected")

    @property
    def all_assertions(self) -> tuple[str, ...]:
        return (
            "assert_save_open_delete_round_trip",
            "assert_generated_key_safety",
            "assert_size_and_checksum",
            "assert_collision_avoidance",
            "assert_cleanup_semantics",
            "assert_access_private_by_default",
            "assert_access_rejects_foreign_descriptors",
        )

    async def run_all(self) -> None:
        """Run every storage contract assertion."""
        for name in self.all_assertions:
            await getattr(self, name)()
