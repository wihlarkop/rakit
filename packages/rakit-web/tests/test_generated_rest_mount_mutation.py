from contextlib import AbstractAsyncContextManager

import httpx
import pytest
from rakit_core.auth import Principal
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import ResourceDefinition, ResourceFieldPolicy
from rakit_core.fields import FieldDefinition
from rakit_core.generated_api import ApiExposure, CompiledResourceApi, ResourceApiDefinition
from rakit_core.generated_operations import GeneratedCrudRequest, GeneratedMutationResult
from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.operations import OperationExecutorCapabilities
from rakit_core.query import PageResult
from rakit_core.resources import ResourceService
from rakit_core.transactions import TransactionPolicy
from rakit_web.generated_rest_runtime import GeneratedRestBinding, build_generated_rest_routes
from rakit_web.schema import PydanticSchemaAdapter
from starlette.applications import Starlette
from starlette.routing import Mount


class DataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "email")
    identity_fields = ("id",)

    async def list(self, query):
        return PageResult((), 1, 25, False, False, 0)

    async def count(self, query):
        return 0

    async def detail(self, identity):
        return {"id": identity.values["id"], "email": "mounted@example.com"}


class Executor:
    capabilities = OperationExecutorCapabilities(participates_in_uow=True)

    async def execute(self, context, request: GeneratedCrudRequest):
        return GeneratedMutationResult(
            identity=RecordIdentity(values={"id": 7}),
            record={"id": 7, "email": "mounted@example.com"},
        )


class UnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def mark_success(self):
        return None

    async def commit(self):
        return None

    async def rollback(self, cause=None):
        return None


class UnitOfWorkFactory:
    def open(self, *, policy: TransactionPolicy, event_publisher, operation_context) -> AbstractAsyncContextManager:
        return UnitOfWork()


class Store:
    production_safe = False

    async def begin(self, token_hash: str, *, fingerprint: str):
        return IdempotencyReservation(1, IdempotencyStatus.IN_PROGRESS)

    async def complete(self, reservation, receipt: OperationReceipt):
        return None

    async def release(self, reservation):
        return None

    async def fail_final(self, reservation):
        return None


def _api() -> CompiledResourceApi:
    definition = ResourceApiDefinition(
        exposure=ApiExposure.CRUD,
        read_fields=("id", "email"),
        create_fields=("email",),
        update_fields=("email",),
    )
    return CompiledResourceApi(
        resource_id="users",
        definition=definition,
        operations=definition.operations,
        read_fields=definition.read_fields,
        create_fields=definition.create_fields,
        update_fields=definition.update_fields,
        identity_fields=("id",),
        filters=(),
        field_definitions=(
            FieldDefinition("id", int, writable=False),
            FieldDefinition("email", str, required=True, nullable=False),
        ),
    )


def _mounted_app():
    async def verify_csrf(request) -> bool:
        return True

    binding = GeneratedRestBinding(
        api=_api(),
        definition=ResourceDefinition(
            resource_id="users",
            path="/users",
            label="Users",
            singular_label="User",
            field_policy=ResourceFieldPolicy(
                list_fields=("id", "email"),
                detail_fields=("id", "email"),
            ),
            api=_api().definition,
        ),
        service=ResourceService(DataSource()),
        schema_adapter=PydanticSchemaAdapter(),
        admin_id="admin",
        auth_enabled=True,
        generated_executor=Executor(),
        verify_csrf=verify_csrf,
        unit_of_work_factory=UnitOfWorkFactory(),
        idempotency_store=Store(),
    )
    principal = Principal(
        subject_id="user-1",
        authenticated=True,
        permissions=frozenset({"admin.resources.users.create"}),
    )
    inner = Starlette(routes=list(build_generated_rest_routes(binding)))

    class StateMiddleware:
        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                scope.setdefault("state", {}).update(
                    {"principal": principal, "request_id": "req-1", "session_id": "session-1"}
                )
            await inner(scope, receive, send)

    return Starlette(routes=[Mount("/admin", app=StateMiddleware())])


@pytest.mark.anyio
async def test_generated_create_location_includes_admin_mount_prefix() -> None:
    transport = httpx.ASGITransport(app=_mounted_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.post(
            "/admin/api/users",
            json={"email": "mounted@example.com"},
            headers={"Idempotency-Key": "mounted-create"},
        )

    expected = IdentityCodec().encode(RecordIdentity(values={"id": 7}))
    assert response.status_code == 201
    assert response.headers["location"] == f"/admin/api/users/{expected}"
