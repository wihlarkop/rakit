from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from hashlib import sha256

import httpx
import pytest
from rakit_core.di import ServiceRegistry, ServiceScope
from rakit_core.fields import FileField
from rakit_core.forms import FormSchema
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import MutationAuthorization, MutationOperation
from rakit_storage import FileAccess, FileStorage, StoredFile, TemporaryUpload
from rakit_web.form_routes import WriteResourceBinding, build_write_routes
from rakit_web.resource_routes import build_templates
from starlette.applications import Starlette


class MemoryFileStorage:
    storage_id = "documents"

    def __init__(self) -> None:
        self.saved: list[StoredFile] = []
        self.deleted: list[StoredFile] = []

    async def save(
        self,
        upload: TemporaryUpload,
        *,
        prefix: str | None = None,
        max_size: int | None = None,
        operation_context=None,
    ) -> StoredFile:
        payload = b"".join([chunk async for chunk in upload.stream()])
        if max_size is not None and len(payload) > max_size:
            raise ValueError("upload exceeds the configured size limit")
        key_prefix = f"{prefix}/" if prefix else ""
        stored = StoredFile(
            storage_id=self.storage_id,
            key=f"{key_prefix}object-{len(self.saved) + 1}",
            original_name=upload.original_name,
            content_type=upload.content_type,
            size=len(payload),
            checksum=f"sha256:{sha256(payload).hexdigest()}",
        )
        self.saved.append(stored)
        return stored

    def open(self, file: StoredFile, *, operation_context=None) -> AsyncIterator[bytes]:
        async def stream() -> AsyncIterator[bytes]:
            yield file.key.encode()

        return stream()

    async def delete(self, file: StoredFile, *, operation_context=None) -> None:
        self.deleted.append(file)

    async def resolve_access(self, file: StoredFile, *, operation_context=None) -> FileAccess:
        return FileAccess()


class FileMutationService:
    def __init__(self, *, fail_create: bool = False) -> None:
        self.fail_create = fail_create
        self.created: Mapping[str, object] | None = None

    async def create(
        self,
        submitted: Mapping[str, object],
        *,
        authorization: MutationAuthorization | None = None,
    ) -> object:
        if self.fail_create:
            raise ValueError("database failed")
        self.created = dict(submitted)
        return self.created


async def allow(_request: object) -> bool:
    return True


async def allow_mutation(
    _request: object,
    operation: MutationOperation,
    _identity: RecordIdentity | None,
) -> MutationAuthorization:
    return MutationAuthorization(
        admin_id="admin",
        resource_id="documents",
        operation=operation,
        principal_id="tester",
        permissions=(f"admin.resources.documents.{operation}",),
    )


def file_binding(
    storage: MemoryFileStorage,
    service: FileMutationService,
    *,
    allowed_mime_types: tuple[str, ...] = ("application/pdf",),
) -> WriteResourceBinding:
    registry = ServiceRegistry()
    registry.add_value(
        FileStorage,
        storage,
        scope=ServiceScope.APPLICATION,
        name=storage.storage_id,
    )

    @asynccontextmanager
    async def operation_scope():
        async with registry.application_scope() as app_services:
            async with app_services.operation_scope() as services:
                yield services

    return WriteResourceBinding(
        path="/documents",
        label="Document",
        form_schema=FormSchema(
            fields=(
                FileField(
                    field_id="attachment",
                    storage_id="documents",
                    prefix="attachments",
                    required=True,
                    max_size=1024,
                    allowed_extensions=(".pdf",),
                    allowed_mime_types=allowed_mime_types,
                ),
            )
        ),
        mutation_service=service,
        templates=build_templates(()),
        authorize=allow,
        verify_csrf=allow,
        verify_submission_token=allow,
        issue_submission_token=lambda _request: "submission",
        mutation_authorizer=allow_mutation,
        operation_scope=operation_scope,
    )


@pytest.mark.anyio
async def test_file_field_form_uses_multipart_file_control() -> None:
    binding = file_binding(MemoryFileStorage(), FileMutationService())
    app = Starlette(routes=build_write_routes(binding))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        response = await client.get("/documents/new")

    assert response.status_code == 200
    assert 'enctype="multipart/form-data"' in response.text
    assert 'type="file"' in response.text
    assert 'name="attachment"' in response.text
    assert 'accept=".pdf,application/pdf"' in response.text


@pytest.mark.anyio
async def test_invalid_mime_returns_422_without_storage_or_mutation() -> None:
    storage = MemoryFileStorage()
    service = FileMutationService()
    binding = file_binding(storage, service)
    app = Starlette(routes=build_write_routes(binding))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        response = await client.post(
            "/documents/new",
            data={"csrf_token": "x", "submission_token": "submission"},
            files={"attachment": ("report.pdf", b"not really pdf", "text/plain")},
        )

    assert response.status_code == 422
    assert "file type is not allowed" in response.text.lower()
    assert storage.saved == []
    assert service.created is None


@pytest.mark.anyio
async def test_valid_upload_is_stored_before_mutation_as_portable_descriptor() -> None:
    storage = MemoryFileStorage()
    service = FileMutationService()
    binding = file_binding(storage, service)
    app = Starlette(routes=build_write_routes(binding))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
        follow_redirects=False,
    ) as client:
        response = await client.post(
            "/documents/new",
            data={"csrf_token": "x", "submission_token": "submission"},
            files={"attachment": ("report.pdf", b"pdf-content", "application/pdf")},
        )

    assert response.status_code == 303
    assert len(storage.saved) == 1
    assert service.created is not None
    descriptor = StoredFile.model_validate(service.created["attachment"])
    assert descriptor == storage.saved[0]
    assert descriptor.key.startswith("attachments/")


@pytest.mark.anyio
async def test_failed_mutation_compensates_newly_stored_upload() -> None:
    storage = MemoryFileStorage()
    service = FileMutationService(fail_create=True)
    binding = file_binding(storage, service)
    app = Starlette(routes=build_write_routes(binding))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        response = await client.post(
            "/documents/new",
            data={"csrf_token": "x", "submission_token": "submission"},
            files={"attachment": ("report.pdf", b"pdf-content", "application/pdf")},
        )

    assert response.status_code == 400
    assert len(storage.saved) == 1
    assert storage.deleted == storage.saved
