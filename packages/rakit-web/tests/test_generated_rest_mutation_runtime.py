from contextlib import AbstractAsyncContextManager

import httpx
import pytest
from rakit_core.auth import Principal
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import ResourceDefinition, ResourceFieldPolicy
from rakit_core.fields import FieldDefinition
from rakit_core.generated_api import ApiExposure, CompiledResourceApi, ResourceApiDefinition
from rakit_core.generated_operations import GeneratedCrudRequest, GeneratedMutationResult
from rakit_core.idempotency import (
    IdempotencyReservation,
    IdempotencyStatus,
    OperationReceipt,
)
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.operations import OperationExecutorCapabilities
from rakit_core.query import PageResult
from rakit_core.resources import ResourceService
from rakit_core.transactions import TransactionPolicy
from rakit_web.generated_rest_runtime import GeneratedRestBinding, build_generated_rest_routes
from rakit_web.schema import PydanticSchemaAdapter
from starlette.applications import Starlette

FIELDS = (
    FieldDefinition("id", int, writable=False),
    FieldDefinition("email", str, required=True, nullable=False),
)


class DataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "email")
    identity_fields = ("id",)

    async def list(self, query):
        return PageResult((), 1, 25, False, False, 0)

    async def count(self, query):
        return 0

    async def detail(self, identity):
        return {"id": identity.values["id"], "email": "existing@example.com"}


class Executor:
    capabilities = OperationExecutorCapabilities(participates_in_uow=True)

    def __init__(self) -> None:
        self.calls: list[GeneratedCrudRequest] = []
        self.operation_ids: list[str] = []

    async def execute(self, context, request: GeneratedCrudRequest):
        self.calls.append(request)
        self.operation_ids.append(context.operation_id)
        if request.operation.value == "create":
            assert request.input is not None
            return GeneratedMutationResult(
                RecordIdentity(values={"id": 7}),
                {"id": 7, "email": request.input.values["email"]},
            )
        if request.operation.value == "update_partial":
            assert request.identity is not None and request.input is not None
            return GeneratedMutationResult(
                request.identity,
                {"id": request.identity.values["id"], "email": request.input.values["email"]},
            )
        assert request.identity is not None
        return GeneratedMutationResult(request.identity, None)


class UnitOfWork:
    def __init__(self, policy: TransactionPolicy) -> None:
        self.policy = policy
        self.succeeded = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def mark_success(self) -> None:
        self.succeeded = True

    async def commit(self) -> None:
        return None

    async def rollback(self, cause=None) -> None:
        return None


class UnitOfWorkFactory:
    def open(self, *, policy, event_publisher, operation_context) -> AbstractAsyncContextManager:
        return UnitOfWork(policy)


class MemoryIdempotencyStore:
    production_safe = False

    def __init__(self) -> None:
        self._next = 1
        self._entries: dict[str, tuple[str, IdempotencyReservation]] = {}
        self.completed_receipts: list[OperationReceipt] = []

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        existing = self._entries.get(token_hash)
        if existing is not None:
            existing_fingerprint, reservation = existing
            if existing_fingerprint != fingerprint:
                raise ValueError("fingerprint mismatch")
            if reservation.status is IdempotencyStatus.COMPLETED:
                return reservation
            return IdempotencyReservation(
                reservation_id=reservation.reservation_id,
                status=reservation.status,
                completed_receipt=reservation.completed_receipt,
                claimed=False,
                claim_generation=reservation.claim_generation,
            )
        reservation = IdempotencyReservation(
            reservation_id=self._next,
            status=IdempotencyStatus.IN_PROGRESS,
        )
        self._next += 1
        self._entries[token_hash] = (fingerprint, reservation)
        return reservation

    async def complete(self, reservation, receipt: OperationReceipt) -> None:
        self.completed_receipts.append(receipt)
        for key, (fingerprint, existing) in tuple(self._entries.items()):
            if existing.reservation_id == reservation.reservation_id:
                self._entries[key] = (
                    fingerprint,
                    IdempotencyReservation(
                        reservation_id=reservation.reservation_id,
                        status=IdempotencyStatus.COMPLETED,
                        completed_receipt=receipt,
                    ),
                )
                return
        raise AssertionError("reservation missing")

    async def release(self, reservation) -> None:
        for key, (_, existing) in tuple(self._entries.items()):
            if existing.reservation_id == reservation.reservation_id:
                del self._entries[key]

    async def fail_final(self, reservation) -> None:
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
        field_definitions=FIELDS,
    )


def _definition() -> ResourceDefinition:
    return ResourceDefinition(
        resource_id="users",
        path="/users",
        label="Users",
        singular_label="User",
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "email"),
            detail_fields=("id", "email"),
        ),
        api=_api().definition,
    )


def _principal(*permissions: str, subject_id: str = "user-1") -> Principal:
    return Principal(
        subject_id=subject_id,
        authenticated=True,
        permissions=frozenset(permissions),
    )


def _app(
    executor: Executor,
    store: MemoryIdempotencyStore,
    *,
    csrf_ok: bool = True,
    principal: Principal | None = None,
):
    async def verify_csrf(request) -> bool:
        return csrf_ok

    binding = GeneratedRestBinding(
        api=_api(),
        definition=_definition(),
        service=ResourceService(DataSource()),
        schema_adapter=PydanticSchemaAdapter(),
        admin_id="admin",
        auth_enabled=True,
        generated_executor=executor,
        verify_csrf=verify_csrf,
        unit_of_work_factory=UnitOfWorkFactory(),
        idempotency_store=store,
    )
    app = Starlette(routes=list(build_generated_rest_routes(binding)))
    actor = principal or _principal(
        "admin.resources.users.read",
        "admin.resources.users.create",
        "admin.resources.users.update",
        "admin.resources.users.delete",
    )

    class StateMiddleware:
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                scope.setdefault("state", {}).update(
                    {"principal": actor, "request_id": "req-1", "session_id": "session-1"}
                )
            await self.inner(scope, receive, send)

    return StateMiddleware(app)


def _all_permissions_principal(subject_id: str) -> Principal:
    return _principal(
        "admin.resources.users.read",
        "admin.resources.users.create",
        "admin.resources.users.update",
        "admin.resources.users.delete",
        subject_id=subject_id,
    )


@pytest.mark.anyio
async def test_create_returns_201_location_and_replays_same_idempotency_key() -> None:
    executor = Executor()
    store = MemoryIdempotencyStore()
    transport = httpx.ASGITransport(app=_app(executor, store))
    headers = {"Idempotency-Key": "create-1"}
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        first = await client.post("/api/users", json={"email": "new@example.com"}, headers=headers)
        replay = await client.post("/api/users", json={"email": "new@example.com"}, headers=headers)

    expected_identity = IdentityCodec().encode(RecordIdentity(values={"id": 7}))
    assert first.status_code == 201
    assert first.headers["location"] == f"/api/users/{expected_identity}"
    assert first.json() == {"data": {"id": 7, "email": "new@example.com"}}
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert replay.headers["location"] == first.headers["location"]
    assert len(executor.calls) == 1
    assert store.completed_receipts[0].operation_id == executor.operation_ids[0]


@pytest.mark.anyio
async def test_same_idempotency_key_with_different_payload_returns_409() -> None:
    executor = Executor()
    store = MemoryIdempotencyStore()
    transport = httpx.ASGITransport(app=_app(executor, store))
    headers = {"Idempotency-Key": "create-1"}
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        await client.post("/api/users", json={"email": "one@example.com"}, headers=headers)
        conflict = await client.post(
            "/api/users", json={"email": "two@example.com"}, headers=headers
        )

    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "resource.conflict"
    assert len(executor.calls) == 1


@pytest.mark.anyio
async def test_idempotency_key_is_isolated_between_authenticated_principals() -> None:
    executor = Executor()
    store = MemoryIdempotencyStore()
    headers = {"Idempotency-Key": "shared-key"}
    first_transport = httpx.ASGITransport(
        app=_app(executor, store, principal=_all_permissions_principal("user-a"))
    )
    second_transport = httpx.ASGITransport(
        app=_app(executor, store, principal=_all_permissions_principal("user-b"))
    )

    async with httpx.AsyncClient(transport=first_transport, base_url="http://localhost") as client:
        first = await client.post("/api/users", json={"email": "same@example.com"}, headers=headers)
    async with httpx.AsyncClient(transport=second_transport, base_url="http://localhost") as client:
        second = await client.post(
            "/api/users", json={"email": "same@example.com"}, headers=headers
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert len(executor.calls) == 2


@pytest.mark.anyio
async def test_patch_and_delete_use_exact_permissions_and_status_contract() -> None:
    executor = Executor()
    store = MemoryIdempotencyStore()
    transport = httpx.ASGITransport(app=_app(executor, store))
    identity = IdentityCodec().encode(RecordIdentity(values={"id": 7}))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        patched = await client.patch(
            f"/api/users/{identity}",
            json={"email": "next@example.com"},
            headers={"Idempotency-Key": "patch-1"},
        )
        deleted = await client.delete(
            f"/api/users/{identity}",
            headers={"Idempotency-Key": "delete-1"},
        )

    assert patched.status_code == 200
    assert patched.json() == {"data": {"id": 7, "email": "next@example.com"}}
    assert deleted.status_code == 204
    assert deleted.content == b""


@pytest.mark.anyio
async def test_empty_patch_is_rejected_before_executor_runs() -> None:
    executor = Executor()
    store = MemoryIdempotencyStore()
    transport = httpx.ASGITransport(app=_app(executor, store))
    identity = IdentityCodec().encode(RecordIdentity(values={"id": 7}))

    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.patch(
            f"/api/users/{identity}",
            json={},
            headers={"Idempotency-Key": "patch-empty"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["details"]["reason"] == "generated_api_patch_empty"
    assert executor.calls == []


@pytest.mark.anyio
async def test_mutations_require_csrf_and_idempotency_key() -> None:
    executor = Executor()
    store = MemoryIdempotencyStore()

    csrf_transport = httpx.ASGITransport(app=_app(executor, store, csrf_ok=False))
    async with httpx.AsyncClient(transport=csrf_transport, base_url="http://localhost") as client:
        csrf = await client.post(
            "/api/users",
            json={"email": "new@example.com"},
            headers={"Idempotency-Key": "create-1"},
        )
    assert csrf.status_code == 403
    assert csrf.json()["error"]["code"] == "auth.forbidden"

    key_transport = httpx.ASGITransport(app=_app(executor, store))
    async with httpx.AsyncClient(transport=key_transport, base_url="http://localhost") as client:
        missing_key = await client.post("/api/users", json={"email": "new@example.com"})
    assert missing_key.status_code == 400
    assert (
        missing_key.json()["error"]["details"]["reason"] == "generated_api_idempotency_key_required"
    )


@pytest.mark.anyio
async def test_mutation_requires_exact_operation_permission() -> None:
    executor = Executor()
    store = MemoryIdempotencyStore()
    transport = httpx.ASGITransport(
        app=_app(executor, store, principal=_principal("admin.resources.users.read"))
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.post(
            "/api/users",
            json={"email": "new@example.com"},
            headers={"Idempotency-Key": "create-1"},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.forbidden"


@pytest.mark.anyio
async def test_mutation_rejects_non_json_and_malformed_or_non_object_json() -> None:
    executor = Executor()
    store = MemoryIdempotencyStore()
    transport = httpx.ASGITransport(app=_app(executor, store))
    headers = {"Idempotency-Key": "key"}
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        unsupported = await client.post(
            "/api/users", content=b"email=x", headers={**headers, "Content-Type": "text/plain"}
        )
        malformed = await client.post(
            "/api/users",
            content=b"{",
            headers={**headers, "Content-Type": "application/json"},
        )
        non_object = await client.post("/api/users", json=["x"], headers=headers)

    assert unsupported.status_code == 415
    assert malformed.status_code == 400
    assert non_object.status_code == 400
