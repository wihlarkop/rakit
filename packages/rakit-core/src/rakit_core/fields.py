"""Typed field metadata used by forms and mutation plans.

The declaration is deliberately framework-neutral: adapters may construct it
from model metadata, while applications may declare it directly for custom
resources. A sensitive field is fail-closed for every public capability.
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from typing import Any

FieldParser = Callable[[object], object]
FieldFormatter = Callable[[object], object]

_SENSITIVE_NAME_PARTS = (
    "password",
    "password_hash",
    "secret",
    "token",
    "api_key",
    "private_key",
    "authorization",
    "cookie",
)
_FILE_DELETE_BEHAVIORS = frozenset({"keep", "delete", "custom"})


@dataclass(frozen=True)
class FieldDefinition:
    field_id: str
    python_type: type[Any]
    label: str | None = None
    readable: bool = True
    writable: bool = True
    searchable: bool = True
    filterable: bool = True
    sortable: bool = True
    required: bool = False
    nullable: bool = False
    widget: str = "text"
    sensitive: bool = False
    description: str | None = None
    parser: FieldParser | None = None
    formatter: FieldFormatter | None = None
    presentation: object | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if not self.field_id or not isinstance(self.field_id, str):
            raise ValueError("Field id must be a non-empty string")
        if not isinstance(self.python_type, type):
            raise ValueError("Field python_type must be a type")
        if self.parser is not None and not callable(self.parser):
            raise ValueError("Field parser must be callable")
        if self.formatter is not None and not callable(self.formatter):
            raise ValueError("Field formatter must be callable")


@dataclass(frozen=True)
class FileField(FieldDefinition):
    """Backend-neutral policy for a private stored-file form field.

    The core declaration intentionally carries only portable policy primitives.
    Storage descriptors and backend implementations live in ``rakit-storage``;
    web/runtime adapters resolve ``storage_id`` through the service registry.
    """

    python_type: type[Any] = field(default=dict, init=False)
    searchable: bool = field(default=False, init=False)
    filterable: bool = field(default=False, init=False)
    sortable: bool = field(default=False, init=False)
    widget: str = field(default="file", init=False)
    storage_id: str = "default"
    prefix: str | None = None
    max_size: int = 10 * 1024 * 1024
    allowed_extensions: tuple[str, ...] = ()
    allowed_mime_types: tuple[str, ...] = ()
    max_filename_length: int = 255
    allow_empty: bool = False
    delete_behavior: str = "keep"

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.storage_id or self.storage_id in {".", ".."}:
            raise ValueError("File storage_id must be a portable name")
        if any(character in self.storage_id for character in ("/", "\\", "\x00")):
            raise ValueError("File storage_id must not contain path separators")
        if not all(character.isalnum() or character in "._-" for character in self.storage_id):
            raise ValueError("File storage_id contains unsupported characters")
        if self.max_size <= 0:
            raise ValueError("File max_size must be positive")
        if self.max_filename_length <= 0:
            raise ValueError("File max_filename_length must be positive")
        if self.delete_behavior not in _FILE_DELETE_BEHAVIORS:
            raise ValueError("File delete_behavior must be keep, delete, or custom")

        normalized_prefix = self._normalized_prefix(self.prefix)
        normalized_extensions = self._normalized_extensions(self.allowed_extensions)
        normalized_mime_types = self._normalized_mime_types(self.allowed_mime_types)
        object.__setattr__(self, "prefix", normalized_prefix)
        object.__setattr__(self, "allowed_extensions", normalized_extensions)
        object.__setattr__(self, "allowed_mime_types", normalized_mime_types)

    @staticmethod
    def _normalized_prefix(prefix: str | None) -> str | None:
        if prefix is None or prefix == "":
            return None
        if "\\" in prefix or "\x00" in prefix or prefix.startswith("/"):
            raise ValueError("File prefix must be a normalized relative POSIX path")
        parts = prefix.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("File prefix contains an unsafe path segment")
        path = PurePosixPath(prefix)
        if path.is_absolute() or str(path) != prefix:
            raise ValueError("File prefix must be a normalized relative POSIX path")
        return prefix

    @staticmethod
    def _normalized_extensions(extensions: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for extension in extensions:
            if not isinstance(extension, str) or not extension.startswith("."):
                raise ValueError("File extensions must start with '.'")
            candidate = extension.lower()
            if (
                candidate in {".", ".."}
                or "/" in candidate
                or "\\" in candidate
                or "\x00" in candidate
                or any(character.isspace() for character in candidate)
            ):
                raise ValueError("File extension is not portable")
            if candidate not in normalized:
                normalized.append(candidate)
        return tuple(normalized)

    @staticmethod
    def _normalized_mime_types(mime_types: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for mime_type in mime_types:
            if (
                not isinstance(mime_type, str)
                or not mime_type.strip()
                or "\x00" in mime_type
                or "\r" in mime_type
                or "\n" in mime_type
            ):
                raise ValueError("File MIME type must be a non-empty safe string")
            candidate = mime_type.strip().lower()
            if candidate not in normalized:
                normalized.append(candidate)
        return tuple(normalized)


def infer_field_security(field: FieldDefinition) -> FieldDefinition:
    """Return a fail-closed field definition for conventionally sensitive fields.

    Explicitly declaring ``sensitive=True`` is the durable policy mechanism;
    the name check is a secure default for adapter-generated fields.
    """

    normalized = field.field_id.lower()
    sensitive = field.sensitive or any(part in normalized for part in _SENSITIVE_NAME_PARTS)
    if not sensitive:
        return field
    return replace(
        field,
        sensitive=True,
        readable=False,
        writable=False,
        searchable=False,
        filterable=False,
        sortable=False,
    )
