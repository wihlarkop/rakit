from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from rakit_core.actions import (
    ActionDefinition,
    ActionScope,
    ActionSuccess,
    DomainActionExecutor,
    action_permission_requirement,
)
from rakit_core.auth import Principal
from rakit_core.bulk import BulkPolicy
from rakit_core.compiler import CompiledApplication
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import (
    CompiledActionDefinition,
    ResourceDefinition,
    ResourceFieldPolicy,
    RouteDefinition,
)
from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.query import PageResult, ResourceQuery
from rakit_core.resources import ResourceService
from rakit_web.bulk_admin import build_admin_bulk_action_routes
from rakit_web.resource_routes import ResourceBinding, build_resource_routes, build_templates
from starlette.applications import Starlette


class _DataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query: ResourceQuery) -> PageResult[dict[str, object]]:
        return PageResult(
            items=({"id": 1, "name": "One"}, {"id": 2, "name": "Two"}),
            page=query.pagination.page,
            per_page=query.pagination.per_page,
            has_previous=False,
            has_next=False,
            total_count=2,
        )

    async def count(self, query: ResourceQuery) -> int:
        del query
        return 2

    async def detail(self, identity: RecordIdentity) -> object:
        return {"id": identity.values["id"], "name": "Order"}

    def identity_for(self, record: object) -> RecordIdentity:
        assert isinstance(record, dict)
        return RecordIdentity(values={"id": record["id"]})


class _MemoryStore:
    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        del token_hash, fingerprint
        return IdempotencyReservation(1, IdempotencyStatus.IN_PROGRESS)

    async def complete(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt
    ) -> None:
        del reservation, receipt

    async def release(self, reservation: IdempotencyReservation) -> None:
        del reservation

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        del reservation


class _PrincipalApp:
    def __init__(self, app: Any, principal: Principal) -> None:
        self.app = app
        self.principal = principal

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            scope.setdefault("state", {})["principal"] = self.principal
        await self.app(scope, receive, send)


def _app(principal: Principal) -> Any:
    permission = action_permission_requirement("archive", admin_id="ops")
    definition = ResourceDefinition(
        resource_id="orders",
        path="/orders",
        label="Orders",
        singular_label="Order",
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "name"),
            detail_fields=("id", "name"),
        ),
    )
    action = ActionDefinition(
        action_id="archive",
        label="Archive selected",
        scope=ActionScope.BULK,
        resource_id="orders",
        permission=permission,
        executor=DomainActionExecutor(lambda _context: ActionSuccess()),
        bulk_policy=BulkPolicy(require_concurrency_snapshot=False),
    )
    compiled_action = CompiledActionDefinition(definition=action, permission=permission)
    action_route = RouteDefinition(
        route_name="resource:orders:action:archive",
        methods=("GET", "POST"),
        path="/orders/_actions/archive",
        owner_id="orders",
    )
    compiled = CompiledApplication(
        routes=(action_route,),
        plugins=(),
        resources=(definition,),
        actions=(action,),
        compiled_actions=(compiled_action,),
        action_routes=((action_route, compiled_action),),
    )
    source = _DataSource()
    service = ResourceService(source)
    templates = build_templates(())
    token_service = TokenService.single_key(
        key_id="bulk",
        value=SecretValue("x" * 32),
        admin_id="ops",
    )

    async def allow(_request: object) -> bool:
        return True

    @asynccontextmanager
    async def operation_scope():
        raise AssertionError("list rendering must not open an operation scope")
        yield

    build_admin_bulk_action_routes(
        compiled=compiled,
        resource_services={"orders": service},
        concurrency_providers={},
        templates=templates,
        verify_csrf=allow,
        verify_submission_token=allow,
        issue_submission_token=lambda _request: "token",
        token_service=token_service,
        idempotency_store=_MemoryStore(),
        admin_id="ops",
        superuser_bypass=True,
        deadline_seconds=30,
        operation_scope=operation_scope,
        unit_of_work_factory=lambda: None,
        label="Operations",
    )
    binding = ResourceBinding(definition=definition, service=service, templates=templates)
    return _PrincipalApp(Starlette(routes=build_resource_routes(binding)), principal)


@pytest.mark.anyio
async def test_authorized_resource_list_renders_bulk_selection_controls() -> None:
    permission = action_permission_requirement("archive", admin_id="ops")
    principal = Principal(
        subject_id="operator",
        authenticated=True,
        permissions=frozenset(permission.permissions),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(principal)),
        base_url="http://test",
    ) as client:
        response = await client.get("/orders")

    assert response.status_code == 200
    assert 'data-rakit-bulk-actions="orders"' in response.text
    assert 'formaction="/orders/_actions/archive"' in response.text
    assert response.text.count('name="selected"') == 2
    assert IdentityCodec().encode(RecordIdentity(values={"id": 1})) in response.text


@pytest.mark.anyio
async def test_unauthorized_resource_list_does_not_expose_bulk_controls() -> None:
    principal = Principal(
        subject_id="reader",
        authenticated=True,
        permissions=frozenset(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(principal)),
        base_url="http://test",
    ) as client:
        response = await client.get("/orders")

    assert response.status_code == 200
    assert "data-rakit-bulk-actions" not in response.text
    assert "Archive selected" not in response.text
    assert 'name="selected"' not in response.text
