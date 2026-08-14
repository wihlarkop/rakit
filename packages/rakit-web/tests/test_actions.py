"""Plan 05 Task 4 unified actions: web translation and security contract tests."""

import re
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import pytest
from rakit_core.actions import (
    ActionAvailabilityDecision,
    ActionContext,
    ActionDefinition,
    ActionPreview,
    ActionRedirect,
    ActionRejected,
    ActionScope,
    ActionSet,
    ActionSuccess,
    DomainActionExecutor,
    PreparedMutationExecutor,
    action_permission_requirement,
)
from rakit_core.auth import Principal
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.concurrency import ConcurrencyTokenService
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import (
    CompiledActionDefinition,
    PageDefinition,
    ResourceDefinition,
    ResourceFieldPolicy,
    RouteDefinition,
)
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_core.idempotency import (
    IdempotencyReservation,
    IdempotencyStatus,
    OperationReceipt,
)
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_core.permissions import PermissionRequirement
from rakit_core.query import PageResult, ResourceQuery
from rakit_web.action_routes import ActionBinding, build_action_routes
from rakit_web.resource_routes import build_templates
from starlette.applications import Starlette
from starlette.requests import Request


class _CompileDataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query: ResourceQuery) -> PageResult:  # pragma: no cover
        raise AssertionError

    async def count(self, query: ResourceQuery) -> int:  # pragma: no cover
        raise AssertionError

    async def detail(self, identity: RecordIdentity) -> object:  # pragma: no cover
        raise AssertionError


def _compiled_action_routes() -> tuple[tuple[RouteDefinition, CompiledActionDefinition], ...]:
    """Compile a small app and return the compiler-owned action route pairs."""
    builder = ApplicationBuilder(admin_id="ops")
    builder.add_resource(
        ResourceDefinition(
            resource_id="orders",
            path="/orders",
            label="Orders",
            singular_label="Order",
            field_policy=ResourceFieldPolicy(list_fields=("id",), detail_fields=("id",)),
        ),
        _CompileDataSource(),
    )
    builder.add_page(PageDefinition(page_id="report", path="/reports", label="Report"))
    builder.add_action(
        ActionDefinition(
            action_id="export",
            label="Export orders",
            scope=ActionScope.RESOURCE,
            resource_id="orders",
            permission=action_permission_requirement("export", admin_id="ops"),
            executor=DomainActionExecutor(lambda _context: ActionSuccess()),
        )
    )
    builder.add_action(
        ActionDefinition(
            action_id="approve",
            label="Approve order",
            scope=ActionScope.RECORD,
            resource_id="orders",
            executor=DomainActionExecutor(lambda _context: ActionSuccess()),
        )
    )
    builder.add_action(
        ActionDefinition(
            action_id="refresh",
            label="Refresh indexes",
            scope=ActionScope.PAGE,
            page_id="report",
            permission=action_permission_requirement("refresh", admin_id="ops"),
            executor=DomainActionExecutor(lambda _context: ActionSuccess()),
        )
    )
    return compile_application(builder).action_routes


class MemoryIdempotencyStore:
    def __init__(self) -> None:
        self.claims: dict[str, tuple[str, OperationReceipt | None]] = {}
        self._tokens: dict[int, str] = {}
        self._next = 1

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        existing = self.claims.get(token_hash)
        if existing is not None:
            existing_fingerprint, receipt = existing
            if existing_fingerprint != fingerprint:
                raise ValueError("fingerprint mismatch")
            return IdempotencyReservation(
                reservation_id=1,
                status=(
                    IdempotencyStatus.COMPLETED
                    if receipt is not None
                    else IdempotencyStatus.IN_PROGRESS
                ),
                completed_receipt=receipt,
                claimed=False,
            )
        reservation = IdempotencyReservation(self._next, IdempotencyStatus.IN_PROGRESS)
        self._next += 1
        self._tokens[reservation.reservation_id] = token_hash
        self.claims[token_hash] = (fingerprint, None)
        return reservation

    async def complete(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt
    ) -> None:
        key = self._tokens[reservation.reservation_id]
        fingerprint, _ = self.claims[key]
        self.claims[key] = (fingerprint, receipt)

    async def release(self, reservation: IdempotencyReservation) -> None:
        key = self._tokens.get(reservation.reservation_id)
        if key is not None:
            self.claims.pop(key, None)

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        return None


@dataclass
class OrderRecord:
    id: int
    status: str
    version: int = 1
    archive_reason: str | None = None
    purged: bool = False


class OrderStore:
    def __init__(self) -> None:
        self.visible: dict[int, OrderRecord] = {
            1: OrderRecord(id=1, status="pending"),
            2: OrderRecord(id=2, status="pending"),
        }
        self.hidden: dict[int, OrderRecord] = {
            3: OrderRecord(id=3, status="pending"),
        }

    def get_visible(self, identity: RecordIdentity) -> OrderRecord | None:
        return self.visible.get(cast(int, identity.values.get("id")))

    def record(self, record_id: int) -> OrderRecord:
        return self.visible[record_id]


class RecordingService:
    def __init__(self, store: OrderStore, concurrency: ConcurrencyTokenService) -> None:
        self.store = store
        self.concurrency = concurrency
        self.update_calls = 0

    async def update(
        self,
        identity: RecordIdentity,
        submitted: dict[str, object],
        *,
        concurrency_token: str | None,
        authorization: OperationAuthorization | None,
    ) -> OrderRecord:
        self.update_calls += 1
        record = self.store.get_visible(identity)
        if record is None:
            raise RakitError(
                code=ErrorCode.RESOURCE_NOT_FOUND,
                message="Resource was not found",
                status_code=404,
            )
        self.concurrency.verify(concurrency_token or "", "orders", identity, record.version)
        if "status" in submitted:
            record.status = str(submitted["status"])
        record.version += 1
        return record


class ActionHarness:
    def __init__(self) -> None:
        self.store = OrderStore()
        self.token_service = TokenService.single_key(
            key_id="actions", value=SecretValue("x" * 32), admin_id="ops"
        )
        self.concurrency = ConcurrencyTokenService(self.token_service)
        self.idempotency = MemoryIdempotencyStore()
        self.service = RecordingService(self.store, self.concurrency)
        self.archive_calls = 0
        self.purge_calls = 0
        self.rebuild_calls = 0
        self.export_calls = 0

    def approve_availability(self, context: ActionContext) -> ActionAvailabilityDecision:
        record = cast(OrderRecord, context.record)
        if record.status == "pending":
            return ActionAvailabilityDecision.available()
        return ActionAvailabilityDecision.disabled("Order is not pending")

    def purge_availability(self, context: ActionContext) -> ActionAvailabilityDecision:
        record = cast(OrderRecord, context.record)
        if record.purged:
            return ActionAvailabilityDecision.disabled("Order is already purged")
        return ActionAvailabilityDecision.available()

    def approve_executor(self) -> PreparedMutationExecutor:
        def prepare(_context: ActionContext) -> dict[str, object]:
            return {"status": "approved"}

        async def commit(plan: object, context: ActionContext) -> ActionSuccess:
            await self.service.update(
                cast(RecordIdentity, context.identity),
                cast(dict[str, object], plan),
                concurrency_token=context.concurrency_token,
                authorization=context.authorization,
            )
            return ActionSuccess(message="Order approved")

        return PreparedMutationExecutor(prepare, commit)

    def archive_executor(self) -> DomainActionExecutor:
        def handler(context: ActionContext) -> ActionSuccess:
            self.archive_calls += 1
            record = cast(OrderRecord, context.record)
            assert context.values is not None
            record.archive_reason = str(context.values["reason"])
            return ActionSuccess(message="Order archived")

        return DomainActionExecutor(handler)

    def purge_preview(self, context: ActionContext) -> ActionPreview:
        return ActionPreview(
            title="Purge order?",
            description="The order will be permanently purged.",
            impact="1 order record removed.",
        )

    def purge_executor(self) -> DomainActionExecutor:
        def handler(context: ActionContext) -> ActionSuccess:
            self.purge_calls += 1
            cast(OrderRecord, context.record).purged = True
            return ActionSuccess(message="Order purged")

        return DomainActionExecutor(handler)

    def definitions(self) -> ActionSet:
        return ActionSet(
            actions=(
                ActionDefinition(
                    action_id="approve",
                    label="Approve order",
                    scope=ActionScope.RECORD,
                    resource_id="orders",
                    permission=action_permission_requirement("approve", admin_id="ops"),
                    description="Approve this order for fulfilment.",
                    availability=self.approve_availability,
                    executor=self.approve_executor(),
                    requires_concurrency=True,
                ),
                ActionDefinition(
                    action_id="archive",
                    label="Archive order",
                    scope=ActionScope.RECORD,
                    resource_id="orders",
                    permission=action_permission_requirement("archive", admin_id="ops"),
                    description="Archive this order with a reason.",
                    input_schema=FormSchema(
                        fields=(
                            FieldDefinition(
                                field_id="reason", python_type=str, required=True, label="Reason"
                            ),
                        )
                    ),
                    executor=self.archive_executor(),
                    needs_form=True,
                ),
                ActionDefinition(
                    action_id="purge",
                    label="Purge order",
                    scope=ActionScope.RECORD,
                    resource_id="orders",
                    permission=action_permission_requirement("purge", admin_id="ops"),
                    description="Permanently purge this order.",
                    availability=self.purge_availability,
                    preview=self.purge_preview,
                    executor=self.purge_executor(),
                    needs_preview=True,
                    needs_confirmation=True,
                    requires_concurrency=True,
                ),
                ActionDefinition(
                    action_id="rebuild",
                    label="Rebuild indexes",
                    scope=ActionScope.PAGE,
                    page_id="admin",
                    permission=action_permission_requirement("rebuild", admin_id="ops"),
                    description="Rebuild the admin index cache.",
                    executor=DomainActionExecutor(self._rebuild_handler),
                ),
                ActionDefinition(
                    action_id="export",
                    label="Export orders",
                    scope=ActionScope.RESOURCE,
                    resource_id="orders",
                    permission=action_permission_requirement("export", admin_id="ops"),
                    description="Export all visible orders.",
                    availability=self.export_availability,
                    executor=DomainActionExecutor(self._export_handler),
                ),
                ActionDefinition(
                    action_id="audit",
                    label="Audit log",
                    scope=ActionScope.RESOURCE,
                    resource_id="orders",
                    permission=action_permission_requirement("audit", admin_id="ops"),
                    description="Inspect the audit trail.",
                    availability=lambda context: ActionAvailabilityDecision.hidden(),
                    executor=DomainActionExecutor(
                        lambda _context: ActionSuccess(message="Audit trail shown")
                    ),
                ),
            )
        )

    def _rebuild_handler(self, _context: ActionContext) -> ActionSuccess:
        self.rebuild_calls += 1
        return ActionSuccess(message="Indexes rebuilt")

    def _export_handler(self, _context: ActionContext) -> ActionRedirect:
        self.export_calls += 1
        return ActionRedirect(location="/orders")

    def export_availability(self, context: ActionContext) -> ActionAvailabilityDecision:
        if context.principal is not None and context.principal.subject_id == "reader":
            return ActionAvailabilityDecision.hidden()
        return ActionAvailabilityDecision.available()

    async def authorize(
        self,
        request: Request,
        compiled_action: CompiledActionDefinition,
        identity: RecordIdentity | None,
    ) -> OperationAuthorization | None:
        action = compiled_action.definition
        active = cast(Principal, request.scope.get("state", {}).get("principal"))
        if active is None or not compiled_action.permission.matches(active):
            return None
        assert active.subject_id is not None
        return OperationAuthorization.for_requirement(
            admin_id="ops",
            resource_id="orders"
            if action.scope in (ActionScope.RECORD, ActionScope.RESOURCE)
            else "admin",
            operation=("update" if action.action_id == "approve" else f"action:{action.action_id}"),
            principal_id=active.subject_id,
            requirement=compiled_action.permission,
            target_identity=identity,
        )

    async def load_record(self, identity: RecordIdentity) -> object | None:
        return self.store.get_visible(identity)

    def build(self, *, subject: str = "tester") -> Any:
        codec = IdentityCodec()

        async def allow(_request: object) -> bool:
            return True

        bindings = []
        for scope, directory, owner in (
            (ActionScope.RECORD, "/orders/{identity}/_actions", "orders"),
            (ActionScope.RESOURCE, "/orders/_actions", "orders"),
            (ActionScope.PAGE, "/admin/_actions", "admin"),
        ):
            actions = tuple(
                action for action in self.definitions().actions if action.scope is scope
            )
            kind = "resource" if scope in (ActionScope.RECORD, ActionScope.RESOURCE) else "page"
            routes = tuple(
                (
                    RouteDefinition(
                        route_name=f"{kind}:{owner}:action:{action.action_id}",
                        methods=("GET", "POST"),
                        path=f"{directory}/{action.action_id}",
                        owner_id=owner,
                    ),
                    CompiledActionDefinition(
                        definition=action,
                        permission=(
                            action.permission
                            if action.permission is not None
                            else action_permission_requirement(action.action_id, admin_id="ops")
                        ),
                    ),
                )
                for action in actions
            )
            bindings.append(
                ActionBinding(
                    routes=routes,
                    templates=build_templates(()),
                    codec=codec,
                    verify_csrf=allow,
                    verify_submission_token=allow,
                    issue_submission_token=lambda _request: uuid4().hex,
                    authorize_action=self.authorize,
                    load_record=self.load_record,
                    record_version=lambda record: cast(OrderRecord, record).version,
                    concurrency=self.concurrency,
                    concurrency_resource_id="orders",
                    token_service=self.token_service,
                    idempotency_store=self.idempotency,
                )
            )
        routes = [route for binding in bindings for route in build_action_routes(binding)]
        return _PrincipalMiddleware(Starlette(routes=routes), subject=subject)


class _PrincipalMiddleware:
    def __init__(self, app: Any, *, subject: str = "tester") -> None:
        self.app = app
        self.subject = subject

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            permissions = (
                frozenset()
                if self.subject == "reader"
                else frozenset(
                    {
                        "ops.actions.approve.execute",
                        "ops.actions.archive.execute",
                        "ops.actions.purge.execute",
                        "ops.actions.rebuild.execute",
                        "ops.actions.export.execute",
                        "ops.actions.audit.execute",
                    }
                )
            )
            scope.setdefault("state", {})["principal"] = Principal(
                subject_id=self.subject, authenticated=True, permissions=permissions
            )
        await self.app(scope, receive, send)


class _ReaderApp(_PrincipalMiddleware):
    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            scope.setdefault("state", {})["principal"] = Principal(
                subject_id="reader", authenticated=True, permissions=frozenset()
            )
        await self.app(scope, receive, send)


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _form_values(page_text: str) -> dict[str, str]:
    return dict(re.findall(r'name="([^"]+)" value="([^"]*)"', page_text))


def _payload(*extra: tuple[str, str], **tokens: str) -> str:
    return urlencode([("csrf_token", "csrf"), *extra])


@pytest.fixture
def harness() -> ActionHarness:
    return ActionHarness()


async def _open_action(client: httpx.AsyncClient, url: str) -> dict[str, str]:
    page = await client.get(url)
    assert page.status_code == 200
    return _form_values(page.text)


@pytest.mark.anyio
async def test_available_action_renders_and_executes(
    harness: ActionHarness,
) -> None:
    app = harness.build()
    parent = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    async with _client(app) as client:
        tokens = await _open_action(client, f"/orders/{parent}/_actions/approve")
        assert 'name="submission_token"' in str(tokens.keys()) or "submission_token" in tokens
        assert "concurrency_token" in tokens
        approved = await client.post(
            f"/orders/{parent}/_actions/approve",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", tokens["submission_token"]),
                    ("concurrency_token", tokens["concurrency_token"]),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert approved.status_code == 303
    assert harness.store.record(1).status == "approved"
    assert harness.service.update_calls == 1


@pytest.mark.anyio
async def test_availability_rechecked_on_post_after_external_change(
    harness: ActionHarness,
) -> None:
    app = harness.build()
    parent = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    async with _client(app) as client:
        tokens = await _open_action(client, f"/orders/{parent}/_actions/approve")
        harness.store.record(1).status = "cancelled"
        harness.store.record(1).version += 1
        rejected = await client.post(
            f"/orders/{parent}/_actions/approve",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", tokens["submission_token"]),
                    ("concurrency_token", tokens["concurrency_token"]),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert rejected.status_code == 409
    assert "no longer available" in rejected.text
    assert harness.store.record(1).status == "cancelled"
    assert harness.service.update_calls == 0


@pytest.mark.anyio
async def test_disabled_action_renders_non_executable_and_rejects_post(
    harness: ActionHarness,
) -> None:
    app = harness.build()
    parent = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    harness.store.record(1).status = "cancelled"
    async with _client(app) as client:
        page = await client.get(f"/orders/{parent}/_actions/approve")
        assert page.status_code == 200
        assert "currently unavailable" in page.text
        assert "Order is not pending" in page.text
        assert 'type="submit"' not in page.text

        rejected = await client.post(
            f"/orders/{parent}/_actions/approve",
            content=urlencode([("csrf_token", "csrf"), ("submission_token", "x")]),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert rejected.status_code == 409
    assert harness.service.update_calls == 0


@pytest.mark.anyio
async def test_hidden_action_is_omitted_and_direct_access_fails_closed(
    harness: ActionHarness,
) -> None:
    app = harness.build()
    async with _client(app) as client:
        page = await client.get("/orders/_actions/audit")
        assert page.status_code == 404
        rejected = await client.post(
            "/orders/_actions/audit",
            content=urlencode([("csrf_token", "csrf"), ("submission_token", "x")]),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert rejected.status_code == 409


@pytest.mark.anyio
async def test_authorization_is_independent_from_availability(
    harness: ActionHarness,
) -> None:
    app = harness.build(subject="reader")
    parent = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    async with _client(app) as client:
        page = await client.get(f"/orders/{parent}/_actions/approve")
        assert page.status_code == 403
        rejected = await client.post(
            f"/orders/{parent}/_actions/approve",
            content=urlencode([("csrf_token", "csrf"), ("submission_token", "x")]),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert rejected.status_code == 403
    assert harness.service.update_calls == 0


@pytest.mark.anyio
async def test_off_scope_record_is_rejected_without_handler(
    harness: ActionHarness,
) -> None:
    app = harness.build()
    hidden_parent = IdentityCodec().encode(RecordIdentity(values={"id": 3}))
    async with _client(app) as client:
        page = await client.get(f"/orders/{hidden_parent}/_actions/approve")
        assert page.status_code == 404
        rejected = await client.post(
            f"/orders/{hidden_parent}/_actions/approve",
            content=urlencode([("csrf_token", "csrf"), ("submission_token", "x")]),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert rejected.status_code == 404
    assert harness.service.update_calls == 0


@pytest.mark.anyio
async def test_typed_input_valid_invalid_unknown_and_preserved(
    harness: ActionHarness,
) -> None:
    app = harness.build()
    parent = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    async with _client(app) as client:
        tokens = await _open_action(client, f"/orders/{parent}/_actions/archive")

        invalid = await client.post(
            f"/orders/{parent}/_actions/archive",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", tokens["submission_token"]),
                    ("reason", ""),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert invalid.status_code == 422
        assert "This field is required" in invalid.text
        assert 'aria-invalid="true"' in invalid.text
        assert harness.archive_calls == 0

        unknown = await client.post(
            f"/orders/{parent}/_actions/archive",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", tokens["submission_token"]),
                    ("reason", "ok"),
                    ("secret", "x"),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert unknown.status_code == 400
        assert harness.archive_calls == 0

        saved = await client.post(
            f"/orders/{parent}/_actions/archive",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", tokens["submission_token"]),
                    ("reason", "done"),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
    assert saved.status_code == 303
    assert harness.archive_calls == 1
    assert harness.store.record(1).archive_reason == "done"


@pytest.mark.anyio
async def test_preview_and_confirmation_are_non_persisting_and_required(
    harness: ActionHarness,
) -> None:
    app = harness.build()
    parent = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    async with _client(app) as client:
        tokens = await _open_action(client, f"/orders/{parent}/_actions/purge")
        assert "Purge order?" in (await client.get(f"/orders/{parent}/_actions/purge")).text
        page = await client.get(f"/orders/{parent}/_actions/purge")
        assert "1 order record removed." in page.text
        assert "confirmation_token" in tokens
        assert "concurrency_token" in tokens
        assert harness.purge_calls == 0
        assert harness.store.record(1).purged is False

        missing = await client.post(
            f"/orders/{parent}/_actions/purge",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", tokens["submission_token"]),
                    ("concurrency_token", tokens["concurrency_token"]),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert missing.status_code == 409
        forged = await client.post(
            f"/orders/{parent}/_actions/purge",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", tokens["submission_token"]),
                    ("concurrency_token", tokens["concurrency_token"]),
                    ("confirmation_token", "forged"),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert forged.status_code == 409
        assert harness.purge_calls == 0

        confirmed = await client.post(
            f"/orders/{parent}/_actions/purge",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", tokens["submission_token"]),
                    ("concurrency_token", tokens["concurrency_token"]),
                    ("confirmation_token", tokens["confirmation_token"]),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
    assert confirmed.status_code == 303
    assert harness.purge_calls == 1
    assert harness.store.record(1).purged is True


@pytest.mark.anyio
async def test_confirmation_does_not_bypass_post_rechecks(
    harness: ActionHarness,
) -> None:
    app = harness.build()
    parent = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    async with _client(app) as client:
        tokens = await _open_action(client, f"/orders/{parent}/_actions/purge")
        harness.store.record(1).purged = True
        harness.store.record(1).version += 1
        rejected = await client.post(
            f"/orders/{parent}/_actions/purge",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", tokens["submission_token"]),
                    ("concurrency_token", tokens["concurrency_token"]),
                    ("confirmation_token", tokens["confirmation_token"]),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
    assert rejected.status_code == 409
    assert harness.purge_calls == 0


@pytest.mark.anyio
async def test_stale_concurrency_is_rejected_before_execution(
    harness: ActionHarness,
) -> None:
    app = harness.build()
    parent = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    async with _client(app) as client:
        tokens = await _open_action(client, f"/orders/{parent}/_actions/approve")
        harness.store.record(1).version += 1
        rejected = await client.post(
            f"/orders/{parent}/_actions/approve",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", tokens["submission_token"]),
                    ("concurrency_token", tokens["concurrency_token"]),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
    assert rejected.status_code == 409
    assert harness.service.update_calls == 0
    assert harness.store.record(1).status == "pending"


@pytest.mark.anyio
async def test_idempotent_replay_and_payload_mismatch(
    harness: ActionHarness,
) -> None:
    app = harness.build()
    parent = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    async with _client(app) as client:
        tokens = await _open_action(client, f"/orders/{parent}/_actions/approve")
        shared = "same-submission-token"
        payload = [
            ("csrf_token", "csrf"),
            ("submission_token", shared),
            ("concurrency_token", tokens["concurrency_token"]),
        ]
        first = await client.post(
            f"/orders/{parent}/_actions/approve",
            content=urlencode(payload),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        second = await client.post(
            f"/orders/{parent}/_actions/approve",
            content=urlencode(payload),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
    assert first.status_code == 303
    assert second.status_code == 303
    assert harness.service.update_calls == 1
    assert harness.store.record(1).status == "approved"
    assert harness.store.record(1).version == 2


@pytest.mark.anyio
async def test_same_submission_token_with_different_payload_is_rejected(
    harness: ActionHarness,
) -> None:
    app = harness.build()
    parent = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    async with _client(app) as client:
        shared = "shared-token"
        first = await client.post(
            f"/orders/{parent}/_actions/archive",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", shared),
                    ("reason", "one"),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        mismatch = await client.post(
            f"/orders/{parent}/_actions/archive",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", shared),
                    ("reason", "two"),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
    assert first.status_code == 303
    assert mismatch.status_code == 409
    assert harness.archive_calls == 1
    assert harness.store.record(1).archive_reason == "one"


@pytest.mark.anyio
async def test_page_and_resource_scope_actions_execute(
    harness: ActionHarness,
) -> None:
    app = harness.build()
    async with _client(app) as client:
        rebuild_tokens = await _open_action(client, "/admin/_actions/rebuild")
        page = await client.get("/admin/_actions/rebuild")
        assert page.status_code == 200
        rebuilt = await client.post(
            "/admin/_actions/rebuild",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", rebuild_tokens["submission_token"]),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        export_tokens = await _open_action(client, "/orders/_actions/export")
        exported = await client.post(
            "/orders/_actions/export",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", export_tokens["submission_token"]),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
    assert rebuilt.status_code == 303
    assert harness.rebuild_calls == 1
    assert exported.status_code == 303
    assert exported.headers["location"] == "/orders"
    assert harness.export_calls == 1


@pytest.mark.anyio
async def test_htmx_flow_uses_same_pipeline_with_fragment_results(
    harness: ActionHarness,
) -> None:
    app = harness.build()
    parent = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    async with _client(app) as client:
        tokens = await _open_action(client, f"/orders/{parent}/_actions/approve")
        approved = await client.post(
            f"/orders/{parent}/_actions/approve",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", tokens["submission_token"]),
                    ("concurrency_token", tokens["concurrency_token"]),
                ]
            ),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "HX-Request": "true",
            },
            follow_redirects=False,
        )
    assert approved.status_code == 204
    assert harness.store.record(1).status == "approved"


@pytest.mark.anyio
async def test_execution_rejection_does_not_mutate_state(
    harness: ActionHarness,
) -> None:
    async def async_true(_request: object) -> bool:
        return True

    rejecting = ActionDefinition(
        action_id="fail",
        label="Fail action",
        scope=ActionScope.RECORD,
        resource_id="orders",
        permission=action_permission_requirement("approve", admin_id="ops"),
        executor=DomainActionExecutor(
            lambda _context: ActionRejected(
                errors={},
                message="Rejected by policy",
            )
        ),
    )
    binding = ActionBinding(
        routes=(
            (
                RouteDefinition(
                    route_name="resource:orders:action:fail",
                    methods=("GET", "POST"),
                    path="/orders/{identity}/_actions/fail",
                    owner_id="orders",
                ),
                CompiledActionDefinition(
                    definition=rejecting,
                    permission=cast(PermissionRequirement, rejecting.permission),
                ),
            ),
        ),
        templates=build_templates(()),
        codec=IdentityCodec(),
        verify_csrf=async_true,
        verify_submission_token=async_true,
        issue_submission_token=lambda _request: uuid4().hex,
        authorize_action=harness.authorize,
        load_record=harness.load_record,
        record_version=lambda record: cast(OrderRecord, record).version,
        concurrency=harness.concurrency,
        concurrency_resource_id="orders",
        token_service=harness.token_service,
        idempotency_store=harness.idempotency,
    )
    app = _PrincipalMiddleware(Starlette(routes=build_action_routes(binding)))
    parent = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    async with _client(app) as client:
        page = await client.get(f"/orders/{parent}/_actions/fail")
        tokens = _form_values(page.text)
        rejected = await client.post(
            f"/orders/{parent}/_actions/fail",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", tokens["submission_token"]),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
    assert rejected.status_code == 409
    assert harness.store.record(1).status == "pending"


@pytest.mark.anyio
async def test_bulk_scope_is_definition_only_and_binding_fails_closed(
    harness: ActionHarness,
) -> None:
    action = ActionDefinition(
        action_id="bulk_archive",
        label="Bulk archive",
        scope=ActionScope.BULK,
        resource_id="orders",
        permission=action_permission_requirement("bulk_archive", admin_id="ops"),
        executor=DomainActionExecutor(
            lambda _context: ActionRejected(
                errors={}, message="Bulk execution is not available yet."
            )
        ),
    )
    assert ActionSet(actions=(action,)).get("bulk_archive") is action

    async def async_true(_request: object) -> bool:
        return True

    with pytest.raises(ValueError, match="Task 5"):
        ActionBinding(
            routes=(
                (
                    RouteDefinition(
                        route_name="resource:orders:action:bulk_archive",
                        methods=("GET", "POST"),
                        path="/orders/_actions/bulk_archive",
                        owner_id="orders",
                    ),
                    CompiledActionDefinition(
                        definition=action,
                        permission=cast(PermissionRequirement, action.permission),
                    ),
                ),
            ),
            templates=build_templates(()),
            codec=IdentityCodec(),
            verify_csrf=async_true,
            verify_submission_token=async_true,
            issue_submission_token=lambda _request: "x",
            authorize_action=harness.authorize,
        )


@pytest.mark.anyio
async def test_duplicate_action_ids_are_rejected() -> None:
    permission = action_permission_requirement("dup", admin_id="ops")

    def executor() -> DomainActionExecutor:
        return DomainActionExecutor(lambda _context: ActionSuccess())

    with pytest.raises(ValueError, match="Duplicate action ids"):
        ActionSet(
            actions=(
                ActionDefinition(
                    action_id="dup",
                    label="One",
                    scope=ActionScope.PAGE,
                    page_id="admin",
                    permission=permission,
                    executor=executor(),
                ),
                ActionDefinition(
                    action_id="dup",
                    label="Two",
                    scope=ActionScope.PAGE,
                    page_id="admin",
                    permission=permission,
                    executor=executor(),
                ),
            )
        )


@pytest.mark.anyio
async def test_action_routes_materialize_exactly_the_compiler_contract(
    harness: ActionHarness,
) -> None:
    async def async_true(_request: object) -> bool:
        return True

    pairs = _compiled_action_routes()
    binding = ActionBinding(
        routes=pairs,
        templates=build_templates(()),
        codec=IdentityCodec(),
        verify_csrf=async_true,
        verify_submission_token=async_true,
        issue_submission_token=lambda _request: uuid4().hex,
        authorize_action=harness.authorize,
        load_record=harness.load_record,
        record_version=lambda record: cast(OrderRecord, record).version,
        concurrency=harness.concurrency,
        concurrency_resource_id="orders",
        token_service=harness.token_service,
        idempotency_store=harness.idempotency,
    )

    materialized = build_action_routes(binding)

    assert len(materialized) == len(pairs)
    assert {route.path for route in materialized} == {
        "/orders/_actions/export",
        "/orders/{identity}/_actions/approve",
        "/reports/_actions/refresh",
    }
    assert {(route.path, route.name) for route in materialized} == {
        (route.path, route.route_name) for route, _ in pairs
    }
    assert all({"GET", "POST"} <= set(route.methods or ()) for route in materialized)


@pytest.mark.anyio
async def test_web_boundary_uses_the_exact_compiled_permission(
    harness: ActionHarness,
) -> None:
    recorded: list[CompiledActionDefinition] = []

    async def recording_authorize(
        request: Request,
        compiled_action: CompiledActionDefinition,
        identity: RecordIdentity | None,
    ) -> OperationAuthorization | None:
        recorded.append(compiled_action)
        return await harness.authorize(request, compiled_action, identity)

    async def async_true(_request: object) -> bool:
        return True

    binding = ActionBinding(
        routes=_compiled_action_routes(),
        templates=build_templates(()),
        codec=IdentityCodec(),
        verify_csrf=async_true,
        verify_submission_token=async_true,
        issue_submission_token=lambda _request: uuid4().hex,
        authorize_action=recording_authorize,
        load_record=harness.load_record,
        record_version=lambda record: cast(OrderRecord, record).version,
        concurrency=harness.concurrency,
        concurrency_resource_id="orders",
        token_service=harness.token_service,
        idempotency_store=harness.idempotency,
    )
    app = _PrincipalMiddleware(Starlette(routes=build_action_routes(binding)))
    parent = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    async with _client(app) as client:
        export = await client.get("/orders/_actions/export")
        assert export.status_code == 200
        approve = await client.get(f"/orders/{parent}/_actions/approve")
        assert approve.status_code == 200

    assert {compiled.definition.action_id for compiled in recorded} == {"export", "approve"}
    by_id = {compiled.definition.action_id: compiled for compiled in recorded}
    assert by_id["export"].permission == PermissionRequirement.all_of("ops.actions.export.execute")
    assert by_id["approve"].permission == PermissionRequirement.all_of(
        "ops.actions.approve.execute"
    )


@pytest.mark.anyio
async def test_get_never_executes_a_non_mutating_action(
    harness: ActionHarness,
) -> None:
    app = harness.build()
    parent = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    async with _client(app) as client:
        first = await client.get(f"/orders/{parent}/_actions/archive")
        assert first.status_code == 200
        second = await client.get(f"/orders/{parent}/_actions/archive")
        assert second.status_code == 200
        assert harness.archive_calls == 0

        tokens = await _open_action(client, f"/orders/{parent}/_actions/archive")
        executed = await client.post(
            f"/orders/{parent}/_actions/archive",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", tokens["submission_token"]),
                    ("reason", "Duplicate"),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
    assert executed.status_code == 303
    assert harness.archive_calls == 1
