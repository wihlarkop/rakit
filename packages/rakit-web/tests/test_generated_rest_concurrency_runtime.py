from contextlib import AbstractAsyncContextManager

import httpx
import pytest
from rakit_core.auth import Principal
from rakit_core.concurrency import ConcurrencyTokenService
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
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


class VersionProvider:
    def version_for(self, record: object):
        assert isinstance(record, dict)
        return record["version"]

    def predicate_values_for(self, record: object):
        assert isinstance(record, dict)
        return {"version": record["version"]}

    def next_values_for(self, record: object):
        assert isinstance(record, dict)
        return {"version": record["version"] + 1}


class DataSource:
    capabilities = type("Capabilities", (), {"read": True})()
    fields = ("id", "email", "version")
    identity_fields = ("id",)

    async def list(self, query):
        return PageResult((), 1, 25, False, False, 0)

    async def count(self, query):
        return 0

    async def detail(self, identity):
        return {"id": identity.values["id"], "email": "current@example.com", "version": 1}


class Executor:
    capabilities = OperationExecutorCapabilities(
        participates_in_uow=True,
        atomic_concurrency=True,
    )

    def __init__(self) -> None:
        self.requests: list[GeneratedCrudRequest] = []

    async def execute(self, context, request: GeneratedCrudRequest):
        self.requests.append(request)
        assert request.identity is not None
        return GeneratedMutationResult(
            request.identity,
            {"id": request.identity.values["id"], "email": "next@example.com", "version": 2},
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
    def open(
        self, *, policy: TransactionPolicy, event_publisher, operation_context
    ) -> AbstractAsyncContextManager:
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


def _tokens() -> ConcurrencyTokenService:
    return ConcurrencyTokenService(
        TokenService.single_key(
            key_id="primary",
            value=SecretValue("x" * 32),
            admin_id="admin",
        )
    )


def _api() -> CompiledResourceApi:
    definition = ResourceApiDefinition(
        exposure=ApiExposure.CRUD,
        read_fields=("id", "email", "version"),
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
            FieldDefinition("version", int, writable=False),
        ),
    )


def _app(executor: Executor):
    provider = VersionProvider()
    tokens = _tokens()

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
                list_fields=("id", "email", "version"),
                detail_fields=("id", "email", "version"),
            ),
            api=_api().definition,
        ),
        service=ResourceService(DataSource()),
        schema_adapter=PydanticSchemaAdapter(),
        admin_id="admin",
        auth_enabled=True,
        generated_executor=executor,
        verify_csrf=verify_csrf,
        unit_of_work_factory=UnitOfWorkFactory(),
        idempotency_store=Store(),
        concurrency_provider=provider,
        concurrency_tokens=tokens,
    )
    inner = Starlette(routes=list(build_generated_rest_routes(binding)))
    principal = Principal(
        subject_id="user-1",
        authenticated=True,
        permissions=frozenset(
            {
                "admin.resources.users.read",
                "admin.resources.users.update",
                "admin.resources.users.delete",
            }
        ),
    )

    class State:
        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                scope.setdefault("state", {}).update(
                    {"principal": principal, "request_id": "req-1", "session_id": "session-1"}
                )
            await inner(scope, receive, send)

    return State()


@pytest.mark.anyio
async def test_detail_returns_strong_etag_and_patch_requires_matching_header_shape() -> None:
    executor = Executor()
    transport = httpx.ASGITransport(app=_app(executor))
    identity = IdentityCodec().encode(RecordIdentity(values={"id": 7}))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        detail = await client.get(f"/api/users/{identity}")
        missing = await client.patch(
            f"/api/users/{identity}",
            json={"email": "next@example.com"},
            headers={"Idempotency-Key": "patch-missing"},
        )
        weak = await client.patch(
            f"/api/users/{identity}",
            json={"email": "next@example.com"},
            headers={"Idempotency-Key": "patch-weak", "If-Match": 'W/"weak"'},
        )
        updated = await client.patch(
            f"/api/users/{identity}",
            json={"email": "next@example.com"},
            headers={"Idempotency-Key": "patch-ok", "If-Match": detail.headers["etag"]},
        )

    assert detail.status_code == 200
    assert detail.headers["etag"].startswith('"') and detail.headers["etag"].endswith('"')
    assert missing.status_code == 428
    assert missing.json()["error"]["details"]["reason"] == "generated_api_if_match_required"
    assert weak.status_code == 400
    assert weak.json()["error"]["details"]["reason"] == "generated_api_if_match_invalid"
    assert updated.status_code == 200
    assert (
        updated.headers["etag"].startswith('"')
        and updated.headers["etag"] != detail.headers["etag"]
    )
    assert executor.requests[-1].concurrency_token == detail.headers["etag"][1:-1]


@pytest.mark.anyio
async def test_delete_requires_if_match_when_concurrency_is_configured() -> None:
    executor = Executor()
    transport = httpx.ASGITransport(app=_app(executor))
    identity = IdentityCodec().encode(RecordIdentity(values={"id": 7}))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        missing = await client.delete(
            f"/api/users/{identity}",
            headers={"Idempotency-Key": "delete-missing"},
        )

    assert missing.status_code == 428
    assert missing.json()["error"]["details"]["reason"] == "generated_api_if_match_required"
