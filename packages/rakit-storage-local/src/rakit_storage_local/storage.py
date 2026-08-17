"""Secure private local-filesystem storage backend."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import uuid
from collections.abc import AsyncIterator, Iterable
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from rakit_core.operations import OperationContext
from rakit_storage import FileAccess, StoredFile, TemporaryUpload

_SAFE_EXTENSION = re.compile(r"^\.[a-z0-9][a-z0-9._+-]{0,31}$")


def _open_binary_exclusive(path: Path) -> BinaryIO:
    return path.open("xb")


def _open_binary_read(path: Path) -> BinaryIO:
    return path.open("rb")


def _write_bytes(handle: BinaryIO, chunk: bytes) -> int:
    return handle.write(chunk)


def _read_bytes(handle: BinaryIO, size: int) -> bytes:
    return handle.read(size)


def _flush_and_sync(handle: BinaryIO) -> None:
    handle.flush()
    os.fsync(handle.fileno())


class LocalStorage:
    """Private local filesystem storage with generated, portable object keys.

    Browser-provided filenames are retained only as metadata. Files are first
    streamed to a generated temporary object under the configured root, then
    flushed, fsynced, and atomically replaced into their generated final key.
    """

    def __init__(
        self,
        *,
        storage_id: str,
        root: str | Path,
        allowed_extensions: Iterable[str] = (),
        chunk_size: int = 64 * 1024,
    ) -> None:
        self.storage_id = self._validate_storage_id(storage_id)
        self.root = Path(root).expanduser().resolve(strict=False)
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self.chunk_size = chunk_size
        self.allowed_extensions = self._normalize_allowed_extensions(allowed_extensions)
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise ValueError("local storage root must be a directory")

    @staticmethod
    def _validate_storage_id(storage_id: str) -> str:
        if not storage_id or storage_id in {".", ".."}:
            raise ValueError("storage_id must be a portable name")
        if any(character in storage_id for character in ("/", "\\", "\x00")):
            raise ValueError("storage_id must not contain path separators")
        if not all(character.isalnum() or character in "._-" for character in storage_id):
            raise ValueError("storage_id contains unsupported characters")
        return storage_id

    @staticmethod
    def _normalize_allowed_extensions(extensions: Iterable[str]) -> frozenset[str]:
        normalized: set[str] = set()
        for extension in extensions:
            candidate = extension.lower()
            if not candidate.startswith("."):
                candidate = f".{candidate}"
            if not _SAFE_EXTENSION.fullmatch(candidate):
                raise ValueError(f"unsupported allowed extension: {extension!r}")
            normalized.add(candidate)
        return frozenset(normalized)

    @staticmethod
    def _validate_prefix(prefix: str | None) -> str | None:
        if prefix is None or prefix == "":
            return None
        if "\\" in prefix or "\x00" in prefix or prefix.startswith("/"):
            raise ValueError("prefix must be a normalized relative POSIX path")
        parts = prefix.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("prefix contains an unsafe path segment")
        path = PurePosixPath(prefix)
        if path.is_absolute() or str(path) != prefix:
            raise ValueError("prefix must be a normalized relative POSIX path")
        return prefix

    def _extension_for(self, original_name: str) -> str:
        suffix = PurePosixPath(original_name.replace("\\", "/")).suffix.lower()
        return suffix if suffix in self.allowed_extensions else ""

    def _generated_key(self, *, prefix: str | None, extension: str) -> str:
        object_name = f"{uuid.uuid4().hex}{extension}"
        return f"{prefix}/{object_name}" if prefix else object_name

    def _resolved_key_path(self, key: str) -> Path:
        relative = PurePosixPath(key)
        candidate = (self.root / Path(*relative.parts)).resolve(strict=False)
        if not candidate.is_relative_to(self.root):
            raise ValueError("storage key resolves outside the configured root")
        return candidate

    def _path_for(self, file: StoredFile) -> Path:
        if file.storage_id != self.storage_id:
            raise ValueError(
                f"StoredFile storage_id {file.storage_id!r} does not belong to {self.storage_id!r}"
            )
        return self._resolved_key_path(file.key)

    @staticmethod
    def _checkpoint(operation_context: OperationContext | None) -> None:
        if operation_context is not None:
            operation_context.checkpoint()

    async def save(
        self,
        upload: TemporaryUpload,
        *,
        prefix: str | None = None,
        max_size: int | None = None,
        operation_context: OperationContext | None = None,
    ) -> StoredFile:
        """Stream an upload into a generated private object atomically."""
        normalized_prefix = self._validate_prefix(prefix)
        if max_size is not None and max_size < 0:
            raise ValueError("max_size must not be negative")
        if (
            max_size is not None
            and upload.declared_size is not None
            and upload.declared_size > max_size
        ):
            raise ValueError("upload exceeds the configured size limit")

        self._checkpoint(operation_context)
        extension = self._extension_for(upload.original_name)
        key = self._generated_key(prefix=normalized_prefix, extension=extension)
        final_path = self._resolved_key_path(key)
        temp_path = self._resolved_key_path(f".rakit-upload-{uuid.uuid4().hex}.tmp")

        await asyncio.to_thread(final_path.parent.mkdir, parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        handle: BinaryIO | None = None
        try:
            handle = await asyncio.to_thread(_open_binary_exclusive, temp_path)
            async for chunk in upload.stream():
                self._checkpoint(operation_context)
                if not isinstance(chunk, bytes):
                    raise TypeError("upload stream must yield bytes")
                if not chunk:
                    continue
                size += len(chunk)
                if max_size is not None and size > max_size:
                    raise ValueError("upload exceeds the configured size limit")
                digest.update(chunk)
                await asyncio.to_thread(_write_bytes, handle, chunk)

            self._checkpoint(operation_context)
            await asyncio.to_thread(_flush_and_sync, handle)
            await asyncio.to_thread(handle.close)
            handle = None
            await asyncio.to_thread(os.replace, temp_path, final_path)
        except BaseException:
            if handle is not None:
                await asyncio.to_thread(handle.close)
            await asyncio.to_thread(temp_path.unlink, missing_ok=True)
            raise

        return StoredFile(
            storage_id=self.storage_id,
            key=key,
            original_name=upload.original_name,
            content_type=upload.content_type,
            size=size,
            checksum=f"sha256:{digest.hexdigest()}",
        )

    def open(
        self,
        file: StoredFile,
        *,
        operation_context: OperationContext | None = None,
    ) -> AsyncIterator[bytes]:
        """Open a private object as a bounded asynchronous byte stream."""
        path = self._path_for(file)

        async def stream() -> AsyncIterator[bytes]:
            self._checkpoint(operation_context)
            handle = await asyncio.to_thread(_open_binary_read, path)
            try:
                while True:
                    self._checkpoint(operation_context)
                    chunk = await asyncio.to_thread(_read_bytes, handle, self.chunk_size)
                    if not chunk:
                        break
                    yield chunk
            finally:
                await asyncio.to_thread(handle.close)

        return stream()

    async def delete(
        self,
        file: StoredFile,
        *,
        operation_context: OperationContext | None = None,
    ) -> None:
        """Delete an owned object idempotently."""
        self._checkpoint(operation_context)
        path = self._path_for(file)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    async def resolve_access(
        self,
        file: StoredFile,
        *,
        operation_context: OperationContext | None = None,
    ) -> FileAccess:
        """Local storage is private by default and exposes no direct URL."""
        self._checkpoint(operation_context)
        self._path_for(file)
        return FileAccess()


__all__ = ["LocalStorage"]
