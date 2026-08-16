from collections.abc import AsyncIterator

import pytest
from pydantic import ValidationError

from rakit_storage import (
    DeleteBehavior,
    FileAccess,
    FileStorage,
    StoredFile,
    TemporaryUpload,
)


def _stored_file(**overrides: object) -> StoredFile:
    values: dict[str, object] = {
        "storage_id": "documents",
        "key": "documents/2026/07/object.pdf",
        "original_name": "contract.pdf",
        "content_type": "application/pdf",
        "size": 1024,
        "checksum": "sha256:abc",
    }
    values.update(overrides)
    return StoredFile.model_validate(values)


def test_stored_file_uses_portable_relative_key() -> None:
    file = _stored_file()

    assert file.key == "documents/2026/07/object.pdf"
    assert not file.key.startswith("/")
    assert "\\" not in file.key


@pytest.mark.parametrize(
    "key",
    (
        "../secret.env",
        "documents/../../secret.env",
        "/etc/passwd",
        "C:/Windows/System32/config",
        r"C:\Windows\System32\config",
        r"documents\object.pdf",
        "./documents/object.pdf",
        "documents//object.pdf",
        "",
    ),
)
def test_unsafe_or_nonportable_key_is_rejected(key: str) -> None:
    with pytest.raises(ValidationError):
        _stored_file(key=key)


@pytest.mark.parametrize("storage_id", ("", "../files", "private/docs", "docs\\private", "."))
def test_storage_id_is_a_portable_name(storage_id: str) -> None:
    with pytest.raises(ValidationError):
        _stored_file(storage_id=storage_id)


def test_stored_file_metadata_is_immutable_and_copied() -> None:
    metadata = {"tenant": "acme", "scan": "pending"}
    file = _stored_file(metadata=metadata)
    metadata["scan"] = "changed"

    assert file.metadata == {"tenant": "acme", "scan": "pending"}
    with pytest.raises(ValidationError):
        file.size = 2048  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("original_name", ""),
        ("content_type", ""),
        ("checksum", ""),
        ("size", -1),
    ),
)
def test_stored_file_rejects_invalid_content_metadata(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _stored_file(**{field: value})


def test_delete_behavior_is_explicit() -> None:
    assert {member.value for member in DeleteBehavior} == {"keep", "delete", "custom"}


def test_file_access_defaults_private() -> None:
    access = FileAccess()

    assert access.public is False
    assert access.url is None


def test_temporary_upload_carries_metadata_and_async_stream() -> None:
    async def stream() -> AsyncIterator[bytes]:
        yield b"hello"

    upload = TemporaryUpload(
        original_name="hello.txt",
        content_type="text/plain",
        stream=stream,
        declared_size=5,
    )

    assert upload.original_name == "hello.txt"
    assert upload.content_type == "text/plain"
    assert upload.declared_size == 5
    assert callable(upload.stream)


def test_file_storage_is_runtime_checkable_protocol() -> None:
    class MemoryStorage:
        storage_id = "memory"

        async def save(
            self,
            upload: TemporaryUpload,
            *,
            prefix: str | None = None,
            max_size: int | None = None,
        ) -> StoredFile:
            del upload, prefix, max_size
            return _stored_file(storage_id=self.storage_id)

        async def open(self, file: StoredFile) -> AsyncIterator[bytes]:
            del file
            if False:
                yield b""

        async def delete(self, file: StoredFile) -> None:
            del file

        async def resolve_access(self, file: StoredFile) -> FileAccess:
            del file
            return FileAccess()

    assert isinstance(MemoryStorage(), FileStorage)
