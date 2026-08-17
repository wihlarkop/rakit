from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from rakit_storage import StoredFile, TemporaryUpload
from rakit_storage_local import LocalStorage


def upload_from_bytes(
    name: str,
    payload: bytes,
    content_type: str = "application/octet-stream",
    *,
    declared_size: int | None = None,
) -> TemporaryUpload:
    async def stream() -> AsyncIterator[bytes]:
        midpoint = max(1, len(payload) // 2)
        yield payload[:midpoint]
        if midpoint < len(payload):
            yield payload[midpoint:]

    return TemporaryUpload(
        original_name=name,
        content_type=content_type,
        stream=stream,
        declared_size=len(payload) if declared_size is None else declared_size,
    )


def files_under(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()]


@pytest.mark.anyio
async def test_browser_filename_never_controls_path(tmp_path: Path) -> None:
    storage = LocalStorage(
        storage_id="documents",
        root=tmp_path,
        allowed_extensions={".txt"},
    )
    stored = await storage.save(
        upload_from_bytes("../../config.py", b"safe", "text/plain"),
        prefix="documents",
    )

    assert stored.original_name == "../../config.py"
    assert stored.key.startswith("documents/")
    assert ".." not in stored.key
    assert not stored.key.endswith(".py")
    assert (tmp_path / stored.key).read_bytes() == b"safe"


@pytest.mark.anyio
async def test_allowlisted_extension_is_normalized_without_reusing_filename(
    tmp_path: Path,
) -> None:
    storage = LocalStorage(
        storage_id="documents",
        root=tmp_path,
        allowed_extensions={".PDF", ".txt"},
    )
    stored = await storage.save(
        upload_from_bytes("Quarterly Report.PDF", b"pdf", "application/pdf"),
        prefix="reports",
    )

    assert stored.key.startswith("reports/")
    assert stored.key.endswith(".pdf")
    assert "Quarterly" not in stored.key


@pytest.mark.anyio
async def test_unsafe_prefix_is_rejected_without_writing(tmp_path: Path) -> None:
    storage = LocalStorage(storage_id="documents", root=tmp_path)

    with pytest.raises(ValueError, match="prefix"):
        await storage.save(upload_from_bytes("safe.txt", b"safe"), prefix="../outside")

    assert files_under(tmp_path) == []


@pytest.mark.anyio
async def test_failed_stream_leaves_no_final_or_temporary_object(tmp_path: Path) -> None:
    storage = LocalStorage(storage_id="documents", root=tmp_path)

    async def failing_stream() -> AsyncIterator[bytes]:
        yield b"partial"
        raise OSError("stream failed")

    upload = TemporaryUpload(
        original_name="payload.bin",
        content_type="application/octet-stream",
        stream=failing_stream,
    )

    with pytest.raises(OSError, match="stream failed"):
        await storage.save(upload, prefix="documents")

    assert files_under(tmp_path) == []


@pytest.mark.anyio
async def test_streaming_size_limit_cleans_partial_write(tmp_path: Path) -> None:
    storage = LocalStorage(storage_id="documents", root=tmp_path)
    upload = upload_from_bytes(
        "payload.bin",
        b"0123456789",
        declared_size=3,
    )

    with pytest.raises(ValueError, match="size limit"):
        await storage.save(upload, max_size=5)

    assert files_under(tmp_path) == []


@pytest.mark.anyio
async def test_declared_size_over_limit_fails_before_stream_is_consumed(
    tmp_path: Path,
) -> None:
    consumed = False

    async def stream() -> AsyncIterator[bytes]:
        nonlocal consumed
        consumed = True
        yield b"ignored"

    storage = LocalStorage(storage_id="documents", root=tmp_path)
    upload = TemporaryUpload(
        original_name="large.bin",
        content_type="application/octet-stream",
        stream=stream,
        declared_size=100,
    )

    with pytest.raises(ValueError, match="size limit"):
        await storage.save(upload, max_size=10)

    assert consumed is False
    assert files_under(tmp_path) == []


@pytest.mark.anyio
async def test_save_records_sha256_size_and_private_access(tmp_path: Path) -> None:
    storage = LocalStorage(storage_id="documents", root=tmp_path)
    stored = await storage.save(upload_from_bytes("hello.txt", b"hello", "text/plain"))

    assert stored.size == 5
    assert stored.checksum == (
        "sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )
    access = await storage.resolve_access(stored)
    assert access.public is False
    assert access.url is None


@pytest.mark.anyio
async def test_open_streams_saved_bytes_and_delete_removes_object(tmp_path: Path) -> None:
    storage = LocalStorage(storage_id="documents", root=tmp_path, chunk_size=3)
    stored = await storage.save(upload_from_bytes("hello.txt", b"abcdefgh"))

    chunks = [chunk async for chunk in storage.open(stored)]
    assert chunks == [b"abc", b"def", b"gh"]

    await storage.delete(stored)
    assert files_under(tmp_path) == []


@pytest.mark.anyio
async def test_storage_rejects_descriptor_owned_by_another_storage(tmp_path: Path) -> None:
    storage = LocalStorage(storage_id="documents", root=tmp_path)
    foreign = StoredFile(
        storage_id="other",
        key="objects/file.bin",
        original_name="file.bin",
        content_type="application/octet-stream",
        size=1,
        checksum="sha256:abc",
    )

    with pytest.raises(ValueError, match="storage_id"):
        _ = [chunk async for chunk in storage.open(foreign)]
    with pytest.raises(ValueError, match="storage_id"):
        await storage.delete(foreign)
    with pytest.raises(ValueError, match="storage_id"):
        await storage.resolve_access(foreign)


@pytest.mark.anyio
async def test_generated_keys_do_not_collide_for_same_browser_filename(tmp_path: Path) -> None:
    storage = LocalStorage(
        storage_id="documents",
        root=tmp_path,
        allowed_extensions={".txt"},
    )

    first = await storage.save(upload_from_bytes("same.txt", b"first"))
    second = await storage.save(upload_from_bytes("same.txt", b"second"))

    assert first.key != second.key
    assert (tmp_path / first.key).read_bytes() == b"first"
    assert (tmp_path / second.key).read_bytes() == b"second"
