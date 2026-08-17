"""Backend-neutral file storage contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from rakit_core.operations import OperationContext


class DeleteBehavior(StrEnum):
    """How a persisted file should behave when its owning record is deleted."""

    KEEP = "keep"
    DELETE = "delete"
    CUSTOM = "custom"


class StoredFile(BaseModel):
    """Portable descriptor for a stored object.

    ``key`` is always a relative POSIX-style object key. It is deliberately
    independent from any local filesystem path so descriptors remain portable
    across storage backends.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    storage_id: str = Field(min_length=1, max_length=128)
    key: str = Field(min_length=1, max_length=1024)
    original_name: str = Field(min_length=1, max_length=1024)
    content_type: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=0)
    checksum: str = Field(min_length=1, max_length=255)
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("storage_id")
    @classmethod
    def _validate_storage_id(cls, value: str) -> str:
        if value in {".", ".."}:
            raise ValueError("storage_id must be a portable name")
        if any(character in value for character in ("/", "\\", "\x00")):
            raise ValueError("storage_id must not contain path separators")
        if not all(character.isalnum() or character in "._-" for character in value):
            raise ValueError("storage_id contains unsupported characters")
        return value

    @field_validator("key")
    @classmethod
    def _validate_key(cls, value: str) -> str:
        if "\\" in value or "\x00" in value:
            raise ValueError("storage key must use portable POSIX separators")
        if value.startswith("/"):
            raise ValueError("storage key must be relative")
        if len(value) >= 2 and value[1] == ":" and value[0].isalpha():
            raise ValueError("storage key must not contain a drive prefix")

        parts = value.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("storage key contains an unsafe path segment")

        path = PurePosixPath(value)
        if path.is_absolute() or str(path) != value:
            raise ValueError("storage key must be a normalized relative POSIX path")
        return value

    @field_validator("original_name", "content_type", "checksum")
    @classmethod
    def _validate_text_metadata(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("file metadata must not be blank")
        if "\x00" in value or "\r" in value or "\n" in value:
            raise ValueError("file metadata contains unsupported control characters")
        return value

    @field_validator("metadata", mode="before")
    @classmethod
    def _copy_metadata(cls, value: object) -> object:
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return dict(value)
        return value


@dataclass(frozen=True, slots=True)
class TemporaryUpload:
    """One request-scoped upload stream before it becomes a stored object."""

    original_name: str
    content_type: str
    stream: Callable[[], AsyncIterator[bytes]]
    declared_size: int | None = None

    def __post_init__(self) -> None:
        if not self.original_name:
            raise ValueError("original_name must not be empty")
        if not self.content_type:
            raise ValueError("content_type must not be empty")
        if self.declared_size is not None and self.declared_size < 0:
            raise ValueError("declared_size must not be negative")


@dataclass(frozen=True, slots=True)
class FileAccess:
    """Storage-level access resolution.

    Private access is the safe default. A storage backend may expose a direct
    URL only when it explicitly declares the object public or when a future
    backend supports a bounded direct-access mechanism.
    """

    public: bool = False
    url: str | None = None
    headers: Mapping[str, str] | None = None


@runtime_checkable
class FileStorage(Protocol):
    """Replaceable storage backend contract used by Rakit file fields."""

    storage_id: str

    async def save(
        self,
        upload: TemporaryUpload,
        *,
        prefix: str | None = None,
        max_size: int | None = None,
        operation_context: OperationContext | None = None,
    ) -> StoredFile: ...

    def open(
        self,
        file: StoredFile,
        *,
        operation_context: OperationContext | None = None,
    ) -> AsyncIterator[bytes]: ...

    async def delete(
        self,
        file: StoredFile,
        *,
        operation_context: OperationContext | None = None,
    ) -> None: ...

    async def resolve_access(
        self,
        file: StoredFile,
        *,
        operation_context: OperationContext | None = None,
    ) -> FileAccess: ...


__all__ = [
    "DeleteBehavior",
    "FileAccess",
    "FileStorage",
    "StoredFile",
    "TemporaryUpload",
]
