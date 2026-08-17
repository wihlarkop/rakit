from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from hashlib import sha256

import httpx
import pytest
from rakit_core.di import ServiceRegistry, ServiceScope
from rakit_core.events import EventBus, EventPublisher
from rakit_core.fields import FileField
from rakit_core.forms import FormSchema
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import MutationAuthorization, MutationOperation
from rakit_storage import FileAccess, FileStorage, StoredFile, TemporaryUpload
from rakit_web.form_routes import WriteResourceBinding, build_write_routes
from rakit_web.resource_routes import build_templates
from starlette.applications import Starlette
from starlette.requests import Request


class MemoryFileStorage:
    storage_id = "documents"

    def __init__(self) -> None:
        self.saved: list[StoredFile] = []
        self.deleted: list[StoredFile] = []
        self.opened: list[StoredFile] = []
        self.payloads: dict[str, bytes] = {}

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
        self.payloads[stored.key] = payload
        return stored

    def open(self, file: StoredFile, *, operation_context=None) -> AsyncIterator[bytes]:
        async def stream() -> AsyncIterator[bytes]:
            self.opened.append(file)
            payload = self.payloads[file.key]
            midpoint = max(1, len(payload) // 2)
            yield payload[:midpoint]
            if midpoint < len(payload):
                yield payload[midpoint:]

        return stream()

    async def delete(self, file: StoredFile, *, operation_context=None) -> None:
        self.deleted.append(file)
        self.payloads.pop(file.key, None)

    async def resolve_access(self, file: StoredFile, *, operation_context=None) -> FileAccess:
        return FileAccess()

    def seed(self, file: StoredFile, payload: bytes) -> None:
        self.payloads[file.key] = payload


class FileMutationService:
    def __init__(
        self,
        *,
        record: Mapping[str, object] | None = None,
        fail_create: bool = False,
        fail_update: bool = False,
        fail_delete: bool = False,
    ) -> None:
        self.record = dict(record) if record is not None else None
        self.fail_create = fail_create
        self.fail_update = fail_update
        self.fail_delete = fail_delete
        self.created: Mapping[str, object] | None = None
        self.updated: Mapping[str, object] | None = None
        self.deleted = False

    async def create(
        self,
        submitted: Mapping[str, object],
        *,
        authorization: MutationAuthorization | None = None,
    ) -> object:
        if self.fail_create:
            raise ValueError("database failed")
        self.created = dict(submitted)
        self.record = dict(submitted)
        return self.created

    async def get(self, identity: RecordIdentity) -> object | None:
        del identity
        return self.record

    def issue_update_token(self, record: object) -> str:
        del record
        return "update-token"

    async def update(
        self,
        identity: RecordIdentity,
        submitted: Mapping[str, object],
        *,
        concurrency_token: str | None,
        authorization: MutationAuthorization | None = None,
    ) -> object:
        del identity, concurrency_token, authorization
        if self.fail_update:
            raise ValueError("database failed")
        self.updated = dict(submitted)
        self.record = dict(submitted)
        return self.updated

    async def issue_delete_token(self, identity: RecordIdentity) -> str:
        del identity
        return "delete-token"

    async def delete(
        self,
        confirmation_token: str,
        *,
        identity: RecordIdentity,
        authorization: MutationAuthorization | None = None,
    ) -> None:
        del confirmation_token, identity, authorization
        if self.fail_delete:
            raise ValueError("database failed")
        self.deleted = True
        self.record = None


async def allow(_request: object) -> bool:
    return True


async def deny(_request: object) -> bool:
    return False


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


def stored_descriptor(
    *,
    key: str = "attachments/existing.pdf",
    name: str = "existing.pdf",
    payload: bytes = b"existing-pdf",
) -> StoredFile:
    return StoredFile(
        storage_id="documents",
        key=key,
        original_name=name,
        content_type="application/pdf",
        size=len(payload),
        checksum=f"sha256:{sha256(payload).hexdigest()}",
    )


def file_binding(
    storage: MemoryFileStorage,
    service: FileMutationService,
    *,
    allowed_mime_types: tuple[str, ...] = ("application/pdf",),
    delete_behavior: str = "keep",
    authorize: Callable[[Request], Awaitable[bool]] = allow,
) -> WriteResourceBinding:
    registry = ServiceRegistry()
    registry.add_value(
        FileStorage,
        storage,
        scope=ServiceScope.APPLICATION,
        name=storage.storage_id,
    )
    registry.add_value(EventBus, EventBus(), scope=ServiceScope.APPLICATION)
    registry.add_factory(
        EventPublisher,
        lambda resolver: EventPublisher(resolver.require(EventBus)),
        scope=ServiceScope.OPERATION,
    )

    @asynccontextmanager
    async def operation_scope():
        async with (
            registry.application_scope() as app_services,
            app_services.operation_scope() as services,
        ):
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
                    delete_behavior=delete_behavior,
                ),
            )
        ),
        mutation_service=service,
        templates=build_templates(()),
        authorize=authorize,
        verify_csrf=allow,
        verify_submission_token=allow,
        issue_submission_token=lambda _request: "submission",
        mutation_authorizer=allow_mutation,
        operation_scope=operation_scope,
    )


def record_path(binding: WriteResourceBinding) -> str:
    encoded = binding.codec.encode(RecordIdentity(values={"id": "doc-1"}))
    return f"/documents/{encoded}"


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


@pytest.mark.anyio
async def test_update_without_new_upload_preserves_existing_descriptor() -> None:
    existing = stored_descriptor()
    storage = MemoryFileStorage()
    storage.seed(existing, b"existing-pdf")
    service = FileMutationService(record={"attachment": existing.model_dump(mode="python")})
    binding = file_binding(storage, service)
    app = Starlette(routes=build_write_routes(binding))
    path = record_path(binding)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.post(
            f"{path}/edit",
            data={
                "csrf_token": "x",
                "submission_token": "submission",
                "concurrency_token": "update-token",
            },
        )

    assert response.status_code == 303
    assert storage.saved == []
    assert storage.deleted == []
    assert service.updated is not None
    assert StoredFile.model_validate(service.updated["attachment"]) == existing


@pytest.mark.anyio
async def test_successful_replacement_deletes_old_file_only_after_update() -> None:
    existing = stored_descriptor()
    storage = MemoryFileStorage()
    storage.seed(existing, b"existing-pdf")
    service = FileMutationService(record={"attachment": existing.model_dump(mode="python")})
    binding = file_binding(storage, service)
    app = Starlette(routes=build_write_routes(binding))
    path = record_path(binding)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.post(
            f"{path}/edit",
            data={
                "csrf_token": "x",
                "submission_token": "submission",
                "concurrency_token": "update-token",
            },
            files={"attachment": ("replacement.pdf", b"replacement", "application/pdf")},
        )

    assert response.status_code == 303
    assert len(storage.saved) == 1
    assert service.updated is not None
    assert StoredFile.model_validate(service.updated["attachment"]) == storage.saved[0]
    assert storage.deleted == [existing]


@pytest.mark.anyio
async def test_failed_replacement_deletes_new_file_but_keeps_existing() -> None:
    existing = stored_descriptor()
    storage = MemoryFileStorage()
    storage.seed(existing, b"existing-pdf")
    service = FileMutationService(
        record={"attachment": existing.model_dump(mode="python")}, fail_update=True
    )
    binding = file_binding(storage, service)
    app = Starlette(routes=build_write_routes(binding))
    path = record_path(binding)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.post(
            f"{path}/edit",
            data={
                "csrf_token": "x",
                "submission_token": "submission",
                "concurrency_token": "update-token",
            },
            files={"attachment": ("replacement.pdf", b"replacement", "application/pdf")},
        )

    assert response.status_code == 400
    assert len(storage.saved) == 1
    assert storage.deleted == storage.saved
    assert existing.key in storage.payloads


@pytest.mark.anyio
async def test_record_delete_policy_runs_only_after_successful_database_delete() -> None:
    existing = stored_descriptor()
    storage = MemoryFileStorage()
    storage.seed(existing, b"existing-pdf")
    service = FileMutationService(record={"attachment": existing.model_dump(mode="python")})
    binding = file_binding(storage, service, delete_behavior="delete")
    app = Starlette(routes=build_write_routes(binding))
    path = record_path(binding)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.post(
            f"{path}/delete",
            data={
                "csrf_token": "x",
                "submission_token": "submission",
                "delete_token": "delete-token",
            },
        )

    assert response.status_code == 303
    assert service.deleted is True
    assert storage.deleted == [existing]


@pytest.mark.anyio
async def test_failed_database_delete_never_removes_file() -> None:
    existing = stored_descriptor()
    storage = MemoryFileStorage()
    storage.seed(existing, b"existing-pdf")
    service = FileMutationService(
        record={"attachment": existing.model_dump(mode="python")}, fail_delete=True
    )
    binding = file_binding(storage, service, delete_behavior="delete")
    app = Starlette(routes=build_write_routes(binding))
    path = record_path(binding)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.post(
            f"{path}/delete",
            data={
                "csrf_token": "x",
                "submission_token": "submission",
                "delete_token": "delete-token",
            },
        )

    assert response.status_code == 400
    assert storage.deleted == []
    assert existing.key in storage.payloads


@pytest.mark.anyio
async def test_private_download_rechecks_authorization_before_opening_storage() -> None:
    existing = stored_descriptor()
    storage = MemoryFileStorage()
    storage.seed(existing, b"private-pdf")
    service = FileMutationService(record={"attachment": existing.model_dump(mode="python")})
    binding = file_binding(storage, service, authorize=deny)
    app = Starlette(routes=build_write_routes(binding))
    path = record_path(binding)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.get(f"{path}/_files/attachment")

    assert response.status_code == 403
    assert storage.opened == []


@pytest.mark.anyio
async def test_private_download_streams_owned_file_with_safe_headers() -> None:
    payload = b"private-pdf"
    existing = stored_descriptor(name="Quarterly Report.pdf", payload=payload)
    storage = MemoryFileStorage()
    storage.seed(existing, payload)
    service = FileMutationService(record={"attachment": existing.model_dump(mode="python")})
    binding = file_binding(storage, service)
    app = Starlette(routes=build_write_routes(binding))
    path = record_path(binding)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.get(f"{path}/_files/attachment")

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-length"] == str(len(payload))
    assert "Quarterly%20Report.pdf" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "private, no-store"
    assert storage.opened == [existing]
