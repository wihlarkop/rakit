"""File-field transport validation and best-effort storage lifecycle helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

import structlog
from pydantic import ValidationError
from rakit_core.di import ServiceResolver
from rakit_core.fields import FileField
from rakit_core.forms import FormIssue, FormSchema
from rakit_storage import FileStorage, StoredFile, TemporaryUpload
from starlette.datastructures import UploadFile

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PreparedUpload:
    field: FileField
    stored: StoredFile
    previous: StoredFile | None = None


@dataclass(frozen=True, slots=True)
class FilePreparation:
    values: dict[str, object]
    uploads: tuple[PreparedUpload, ...]
    issues: tuple[FormIssue, ...]


def file_fields(schema: FormSchema) -> tuple[FileField, ...]:
    return tuple(field for field in schema.fields if isinstance(field, FileField))


def has_file_fields(schema: FormSchema) -> bool:
    return bool(file_fields(schema))


def file_accept(field: FileField) -> str:
    return ",".join((*field.allowed_extensions, *field.allowed_mime_types))


def stored_file_from_value(value: object) -> StoredFile | None:
    if isinstance(value, StoredFile):
        return value
    if not isinstance(value, Mapping):
        return None
    try:
        return StoredFile.model_validate(dict(value))
    except ValidationError:
        return None


def record_value(record: object, field_id: str) -> object:
    if isinstance(record, Mapping):
        return record.get(field_id)
    return getattr(record, field_id, None)


def record_stored_file(record: object, field: FileField) -> StoredFile | None:
    return stored_file_from_value(record_value(record, field.field_id))


def submission_for_display(submitted: Mapping[str, object]) -> dict[str, object]:
    return {
        field_id: "" if isinstance(value, UploadFile) else value
        for field_id, value in submitted.items()
    }


def _upload_issue(field: FileField, upload: UploadFile) -> FormIssue | None:
    filename = upload.filename or ""
    if not filename:
        return None
    if len(filename) > field.max_filename_length:
        return FormIssue(field.field_id, "File name is too long.")

    extension = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    if field.allowed_extensions and extension not in field.allowed_extensions:
        return FormIssue(field.field_id, "File extension is not allowed.")

    content_type = (upload.content_type or "application/octet-stream").lower()
    if field.allowed_mime_types and content_type not in field.allowed_mime_types:
        return FormIssue(field.field_id, "File type is not allowed.")

    if upload.size is not None and upload.size > field.max_size:
        return FormIssue(field.field_id, "File exceeds the maximum allowed size.")
    if upload.size == 0 and not field.allow_empty:
        return FormIssue(field.field_id, "Empty files are not allowed.")
    return None


def _temporary_upload(upload: UploadFile) -> TemporaryUpload:
    async def stream():
        while True:
            chunk = await upload.read(64 * 1024)
            if not chunk:
                break
            yield chunk

    return TemporaryUpload(
        original_name=upload.filename or "upload",
        content_type=upload.content_type or "application/octet-stream",
        declared_size=upload.size,
        stream=stream,
    )


async def prepare_file_submission(
    schema: FormSchema,
    submitted: Mapping[str, object],
    *,
    services: ServiceResolver,
    previous_record: object | None = None,
) -> FilePreparation:
    """Validate/store submitted files and return portable descriptors for parsing.

    The returned ``uploads`` remain the caller's responsibility until the
    database mutation succeeds. If later validation/mutation fails, callers
    compensate them through :func:`compensate_uploads`.
    """

    values = dict(submitted)
    prepared: list[PreparedUpload] = []
    issues: list[FormIssue] = []

    for field in file_fields(schema):
        raw = values.pop(field.field_id, None)
        previous = (
            record_stored_file(previous_record, field) if previous_record is not None else None
        )

        if raw is None or raw == "":
            if previous is not None:
                values[field.field_id] = previous.model_dump(mode="python")
            continue
        if not isinstance(raw, UploadFile):
            issues.append(FormIssue(field.field_id, "A file upload is required."))
            continue
        if not raw.filename:
            await raw.close()
            if previous is not None:
                values[field.field_id] = previous.model_dump(mode="python")
            continue

        issue = _upload_issue(field, raw)
        if issue is not None:
            issues.append(issue)
            await raw.close()
            continue

        storage = services.require(FileStorage, name=field.storage_id)
        try:
            stored = await storage.save(
                _temporary_upload(raw),
                prefix=field.prefix,
                max_size=field.max_size,
            )
        except ValueError:
            issues.append(FormIssue(field.field_id, "File exceeds the maximum allowed size."))
            await raw.close()
            continue
        finally:
            if not raw.file.closed:
                await raw.close()

        if stored.storage_id != field.storage_id:
            await storage.delete(stored)
            issues.append(FormIssue(field.field_id, "File storage configuration is invalid."))
            continue
        if stored.size == 0 and not field.allow_empty:
            await storage.delete(stored)
            issues.append(FormIssue(field.field_id, "Empty files are not allowed."))
            continue

        values[field.field_id] = stored.model_dump(mode="python")
        prepared.append(PreparedUpload(field=field, stored=stored, previous=previous))

    return FilePreparation(values=values, uploads=tuple(prepared), issues=tuple(issues))


async def compensate_uploads(
    uploads: tuple[PreparedUpload, ...],
    *,
    services: ServiceResolver,
) -> None:
    """Best-effort removal of newly stored objects after a failed mutation."""

    for upload in reversed(uploads):
        try:
            storage = services.require(FileStorage, name=upload.stored.storage_id)
            await storage.delete(upload.stored)
        except Exception as exc:  # compensation must not hide the primary failure
            logger.warning(
                "storage.compensation.failed",
                storage_id=upload.stored.storage_id,
                key=upload.stored.key,
                error_type=type(exc).__name__,
            )


async def cleanup_replaced_uploads(
    uploads: tuple[PreparedUpload, ...],
    *,
    services: ServiceResolver,
) -> None:
    """Best-effort removal of superseded objects after durable mutation success."""

    for upload in uploads:
        previous = upload.previous
        if previous is None or previous == upload.stored:
            continue
        try:
            storage = services.require(FileStorage, name=previous.storage_id)
            await storage.delete(previous)
        except Exception as exc:
            logger.warning(
                "storage.replacement_cleanup.failed",
                storage_id=previous.storage_id,
                key=previous.key,
                error_type=type(exc).__name__,
            )


async def cleanup_deleted_record_files(
    schema: FormSchema,
    record: object,
    *,
    services: ServiceResolver,
) -> None:
    """Apply automatic record-delete policy only after database deletion succeeds."""

    for field in file_fields(schema):
        if field.delete_behavior != "delete":
            continue
        stored = record_stored_file(record, field)
        if stored is None:
            continue
        try:
            storage = services.require(FileStorage, name=stored.storage_id)
            await storage.delete(stored)
        except Exception as exc:
            logger.warning(
                "storage.record_cleanup.failed",
                storage_id=stored.storage_id,
                key=stored.key,
                error_type=type(exc).__name__,
            )


__all__ = [
    "FilePreparation",
    "PreparedUpload",
    "cleanup_deleted_record_files",
    "cleanup_replaced_uploads",
    "compensate_uploads",
    "file_accept",
    "file_fields",
    "has_file_fields",
    "prepare_file_submission",
    "record_stored_file",
    "stored_file_from_value",
    "submission_for_display",
]
