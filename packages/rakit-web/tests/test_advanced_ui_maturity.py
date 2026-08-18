"""UI-06A mature action presentation and bulk-operation regressions."""

import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import cast
from urllib.parse import urlencode

import httpx
import pytest
from rakit import (
    ActionIntent,
    ActionPresentation,
    Admin,
    FilterPanelPresentation,
    PageWebPresentation,
    ResourceWebPresentation,
)
from rakit_core.actions import (
    ActionAvailabilityDecision,
    ActionAvailabilityResolver,
    ActionContext,
    ActionDefinition,
    ActionPreview,
    ActionScope,
    ActionSuccess,
    DomainActionExecutor,
    action_permission_requirement,
)
from rakit_core.admin_types import ResourceAdmin
from rakit_core.auth import Principal
from rakit_core.bulk import BulkPolicy
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
from rakit_core.di import ServiceResolver
from rakit_core.errors import RakitError
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_core.query import PagePagination, PageResult, ResourceQuery
from rakit_core.resources import ResourceService
from rakit_web.action_presentation import (
    action_web_presentation,
    bind_action_web_presentation,
)
from rakit_web.action_routes import ActionBinding, build_action_routes
from rakit_web.action_views import resolve_action_views
from rakit_web.bulk_admin import build_admin_bulk_action_routes
from rakit_web.bulk_review import build_mature_bulk_action_routes
from rakit_web.bulk_routes import BulkActionBinding
from rakit_web.resource_routes import ResourceBinding, build_resource_routes, build_templates
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send


class _DataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query: ResourceQuery) -> PageResult[dict[str, object]]:
        pagination = query.pagination
        if not isinstance(pagination, PagePagination):
            raise ValueError("test datasource supports page pagination only")
        return PageResult(
            items=({"id": 1, "name": "One"}, {"id": 2, "name": "Two"}),
            page=pagination.page,
            per_page=pagination.per_page,
            has_previous=False,
            has_next=False,
            total_count=2,
        )

    async def count(self, query: ResourceQuery) -> int:
        del query
        return 2

    async def detail(self, identity: RecordIdentity) -> dict[str, object] | None:
        record_id = cast(int, identity.values["id"])
        if record_id not in {1, 2}:
            return None
        return {"id": record_id, "name": f"Order {record_id}", "version": 1}

    def identity_for(self, record: object) -> RecordIdentity:
        values = cast(dict[str, object], record)
        record_id = values["id"]
        assert isinstance(record_id, int | str) and not isinstance(record_id, bool)
        return RecordIdentity(values={"id": record_id})


def _executor() -> DomainActionExecutor:
    return DomainActionExecutor(lambda _context: ActionSuccess())


def _resource_action(action_id: str, scope: ActionScope) -> ActionDefinition:
    return ActionDefinition(
        action_id=action_id,
        label=action_id.replace("_", " ").title(),
        scope=scope,
        resource_id="orders",
        executor=_executor(),
        bulk_policy=(
            BulkPolicy(require_concurrency_snapshot=False) if scope is ActionScope.BULK else None
        ),
    )


class _OrdersAdmin(ResourceAdmin):
    resource_id = "orders"
    path = "/orders"
    label = "Orders"
    singular_label = "Order"
    list_fields = ("id", "name")
    detail_fields = ("id", "name")
    data_source = _DataSource()
    actions = (
        _resource_action("export", ActionScope.RESOURCE),
        _resource_action("inspect", ActionScope.RECORD),
        _resource_action("archive", ActionScope.RECORD),
    )


def test_public_action_presentation_validation_is_atomic_and_scope_aware() -> None:
    admin = Admin(admin_id="ops", title="Operations", debug=True)
    with pytest.raises(RakitError) as unknown:
        admin.register(
            _OrdersAdmin,
            web=ResourceWebPresentation(
                actions={"missing": ActionPresentation(intent=ActionIntent.PRIMARY)}
            ),
        )
    assert unknown.value.details["reason"] == "invalid_web_action_presentation"
    assert admin.builder.resources == ()
    assert admin.builder.actions == ()

    with pytest.raises(TypeError):
        ResourceWebPresentation(
            actions=cast(
                Mapping[str, ActionPresentation],
                {"export": object()},
            )
        )

    admin = Admin(admin_id="ops", title="Operations", debug=True)
    with pytest.raises(RakitError):
        admin.register(
            _OrdersAdmin,
            web=ResourceWebPresentation(
                actions={
                    "inspect": ActionPresentation(intent=ActionIntent.PRIMARY),
                    "archive": ActionPresentation(intent=ActionIntent.PRIMARY),
                }
            ),
        )
    assert admin.builder.resources == ()

    admin = Admin(admin_id="ops", title="Operations", debug=True)
    admin.register(
        _OrdersAdmin,
        web=ResourceWebPresentation(
            actions={
                "export": ActionPresentation(intent=ActionIntent.PRIMARY),
                "inspect": ActionPresentation(intent=ActionIntent.PRIMARY),
            }
        ),
    )
    compiled = admin.compile()
    presentations = {
        str(item.definition.action_id): action_web_presentation(item.definition).intent
        for item in compiled.compiled_actions
    }
    assert presentations["export"] is ActionIntent.PRIMARY
    assert presentations["inspect"] is ActionIntent.PRIMARY
    assert presentations["archive"] is ActionIntent.DEFAULT


def test_page_presentation_validation_and_legacy_registration_remain_compatible() -> None:
    first = ActionDefinition(
        action_id="refresh",
        label="Refresh",
        scope=ActionScope.PAGE,
        page_id="report",
        executor=_executor(),
    )
    second = ActionDefinition(
        action_id="rebuild",
        label="Rebuild",
        scope=ActionScope.PAGE,
        page_id="report",
        executor=_executor(),
    )
    page = PageDefinition(page_id="report", path="/reports", label="Report")

    admin = Admin(admin_id="ops", title="Operations", debug=True)
    with pytest.raises(RakitError):
        admin.register_page(
            page,
            actions=(first, second),
            web=PageWebPresentation(
                actions={
                    "refresh": ActionPresentation(intent=ActionIntent.PRIMARY),
                    "rebuild": ActionPresentation(intent=ActionIntent.PRIMARY),
                }
            ),
        )
    assert admin.builder.pages == ()
    assert admin.builder.actions == ()

    legacy = Admin(admin_id="ops", title="Operations", debug=True)
    legacy.register_page(page, actions=(first, second))
    assert legacy.compile().pages == (page,)

    filters_only = Admin(admin_id="ops", title="Operations", debug=True)
    filters_only.register(
        _OrdersAdmin,
        web=ResourceWebPresentation(filters=FilterPanelPresentation()),
    )
    assert len(filters_only.compile().resources) == 1


def _request(permissions: frozenset[str]) -> Request:
    scope = cast(
        Scope,
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/admin/current",
            "raw_path": b"/admin/current",
            "query_string": b"",
            "headers": [],
            "client": ("test", 1234),
            "server": ("test", 80),
            "root_path": "/admin",
            "state": {
                "principal": Principal(
                    subject_id="operator",
                    authenticated=True,
                    permissions=permissions,
                )
            },
        },
    )
    return Request(scope)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scope", "owner_id", "route_prefix", "identity"),
    (
        (ActionScope.RESOURCE, "orders", "/orders", None),
        (
            ActionScope.RECORD,
            "orders",
            "/orders/{identity}",
            RecordIdentity(values={"id": 1}),
        ),
        (ActionScope.PAGE, "report", "/reports", None),
    ),
)
async def test_context_action_views_hide_disable_and_authorize_entry_points(
    scope: ActionScope,
    owner_id: str,
    route_prefix: str,
    identity: RecordIdentity | None,
) -> None:
    permissions: set[str] = set()
    pairs: list[tuple[RouteDefinition, CompiledActionDefinition]] = []

    def make_action(
        action_id: str,
        availability: ActionAvailabilityResolver | None = None,
        *,
        authorized: bool = True,
    ) -> None:
        permission = action_permission_requirement(action_id, admin_id="ops")
        if authorized:
            permissions.update(permission.permissions)
        action = ActionDefinition(
            action_id=action_id,
            label=action_id.replace("_", " ").title(),
            scope=scope,
            permission=permission,
            resource_id=owner_id if scope is not ActionScope.PAGE else None,
            page_id=owner_id if scope is ActionScope.PAGE else None,
            availability=availability,
            executor=_executor(),
        )
        if action_id == "available":
            bind_action_web_presentation(
                action,
                ActionPresentation(intent=ActionIntent.PRIMARY),
            )
        route = RouteDefinition(
            route_name=f"test:{scope.value}:{action_id}",
            methods=("GET", "POST"),
            path=f"{route_prefix}/_actions/{action_id}",
            owner_id=owner_id,
        )
        pairs.append((route, CompiledActionDefinition(definition=action, permission=permission)))

    make_action("available")
    make_action(
        "disabled",
        lambda _context: ActionAvailabilityDecision.disabled("Temporarily unavailable"),
    )
    make_action("hidden", lambda _context: ActionAvailabilityDecision.hidden())

    def must_not_run(_context: ActionContext) -> ActionAvailabilityDecision:
        raise AssertionError("unauthorized availability must not be evaluated")

    make_action("unauthorized", must_not_run, authorized=False)
    views = await resolve_action_views(
        request=_request(frozenset(permissions)),
        routes=tuple(pairs),
        admin_id="ops",
        owner_id=owner_id,
        scope=scope,
        superuser_bypass=False,
        identity=identity,
        record={"id": 1, "status": "pending"} if identity is not None else None,
    )

    by_id = {view.action_id: view for view in views}
    assert set(by_id) == {"available", "disabled"}
    assert by_id["available"].intent is ActionIntent.PRIMARY
    assert by_id["available"].url.startswith("/admin/")
    assert "{identity}" not in by_id["available"].url
    assert by_id["disabled"].reason == "Temporarily unavailable"
    assert by_id["disabled"].availability.value == "disabled"


class _MemoryIdempotencyStore:
    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        del token_hash, fingerprint
        return IdempotencyReservation(1, IdempotencyStatus.IN_PROGRESS)

    async def complete(
        self,
        reservation: IdempotencyReservation,
        receipt: OperationReceipt,
    ) -> None:
        del reservation, receipt

    async def release(self, reservation: IdempotencyReservation) -> None:
        del reservation

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        del reservation


class _BulkHarness:
    def __init__(
        self,
        *,
        needs_confirmation: bool = False,
        require_snapshot: bool = False,
    ) -> None:
        self.codec = IdentityCodec()
        self.records = {
            1: {"id": 1, "name": "One", "version": 1},
            2: {"id": 2, "name": "Two", "version": 1},
        }
        self.states = {1: "available", 2: "available"}
        self.calls: list[int] = []
        self.token_service = TokenService.single_key(
            key_id="bulk",
            value=SecretValue("x" * 32),
            admin_id="ops",
        )
        permission = action_permission_requirement("archive", admin_id="ops")

        def availability(context: ActionContext) -> ActionAvailabilityDecision:
            assert context.identity is not None
            record_id = cast(int, context.identity.values["id"])
            state = self.states[record_id]
            if state == "hidden":
                return ActionAvailabilityDecision.hidden()
            if state == "disabled":
                return ActionAvailabilityDecision.disabled("Order is locked")
            return ActionAvailabilityDecision.available()

        def execute(context: ActionContext) -> ActionSuccess[None]:
            assert context.identity is not None
            self.calls.append(cast(int, context.identity.values["id"]))
            return ActionSuccess(message="Archived")

        self.action = ActionDefinition(
            action_id="archive",
            label="Archive selected",
            scope=ActionScope.BULK,
            resource_id="orders",
            permission=permission,
            availability=availability,
            preview=(
                lambda _context: ActionPreview(
                    title="Archive selected",
                    description="Review selected records.",
                    impact="Selected records will be archived.",
                )
                if needs_confirmation
                else None
            ),
            executor=DomainActionExecutor(execute),
            needs_preview=needs_confirmation,
            needs_confirmation=needs_confirmation,
            bulk_policy=BulkPolicy(require_concurrency_snapshot=require_snapshot),
        )
        bind_action_web_presentation(
            self.action,
            ActionPresentation(intent=ActionIntent.DANGER),
        )
        self.compiled = CompiledActionDefinition(
            definition=self.action,
            permission=permission,
        )
        self.route = RouteDefinition(
            route_name="resource:orders:action:archive",
            methods=("GET", "POST"),
            path="/orders/_actions/archive",
            owner_id="orders",
        )

    async def authorize(
        self,
        _request: Request,
        compiled: CompiledActionDefinition,
        identity: RecordIdentity | None,
    ) -> OperationAuthorization:
        return OperationAuthorization.for_requirement(
            admin_id="ops",
            resource_id="orders",
            operation="action:archive",
            principal_id="operator",
            requirement=compiled.permission,
            target_identity=identity,
        )

    async def load_record(self, identity: RecordIdentity) -> object | None:
        return self.records.get(cast(int, identity.values["id"]))

    def encoded(self, *record_ids: int) -> list[str]:
        return [
            self.codec.encode(RecordIdentity(values={"id": record_id})) for record_id in record_ids
        ]

    def app(self) -> Starlette:
        async def allow(_request: Request) -> bool:
            return True

        policy = self.action.bulk_policy
        assert policy is not None
        if policy.require_concurrency_snapshot:
            concurrency = ConcurrencyTokenService(self.token_service)
            record_version = lambda record: cast(dict[str, object], record)["version"]
        else:
            concurrency = None
            record_version = None
        binding = BulkActionBinding(
            routes=((self.route, self.compiled),),
            templates=build_templates(()),
            codec=self.codec,
            verify_csrf=allow,
            verify_submission_token=allow,
            issue_submission_token=lambda _request: "issued-token",
            authorize_action=self.authorize,
            load_record=self.load_record,
            token_service=self.token_service,
            idempotency_store=_MemoryIdempotencyStore(),
            concurrency=concurrency,
            concurrency_resource_id=("orders" if policy.require_concurrency_snapshot else None),
            record_version=record_version,
        )
        return Starlette(routes=build_mature_bulk_action_routes(binding))


@pytest.mark.anyio
async def test_bulk_get_is_selection_aware_and_post_rechecks_fresh_state() -> None:
    harness = _BulkHarness()
    selected = harness.encoded(1)
    query = urlencode([("selected", selected[0])])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app()),
        base_url="http://test",
    ) as client:
        available = await client.get(f"/orders/_actions/archive?{query}")
        assert available.status_code == 200
        assert "Execute bulk action" in available.text

        harness.states[1] = "disabled"
        disabled = await client.get(f"/orders/_actions/archive?{query}")
        assert disabled.status_code == 200
        assert "Order is locked" in disabled.text
        assert "Execute bulk action" not in disabled.text
        assert "<form" not in disabled.text

        harness.states[1] = "hidden"
        hidden = await client.get(f"/orders/_actions/archive?{query}")
        assert hidden.status_code == 404
        assert "Archive selected" not in hidden.text

        harness.states[1] = "available"
        reopened = await client.get(f"/orders/_actions/archive?{query}")
        assert reopened.status_code == 200
        harness.states[1] = "disabled"
        post = await client.post(
            "/orders/_actions/archive",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", "issued-token"),
                    ("selected", selected[0]),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert post.status_code == 409
    assert harness.calls == []


@pytest.mark.anyio
async def test_bulk_review_preserves_safety_tokens_and_danger_intent() -> None:
    harness = _BulkHarness(needs_confirmation=True, require_snapshot=True)
    selected = harness.encoded(1)
    query = urlencode([("selected", selected[0])])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app()),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/orders/_actions/archive?{query}")

    assert response.status_code == 200
    for field_name in (
        "csrf_token",
        "submission_token",
        "selected",
        "concurrency_token",
        "confirmation_token",
    ):
        assert f'name="{field_name}"' in response.text
    assert "rakit-button-danger" in response.text
    assert "text-rakit-" in response.text


class _PrincipalApp:
    def __init__(self, app: ASGIApp, permissions: frozenset[str]) -> None:
        self.app = app
        self.principal = Principal(
            subject_id="operator",
            authenticated=True,
            permissions=permissions,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            scope.setdefault("state", {})["principal"] = self.principal
        await self.app(scope, receive, send)


def _bulk_list_app() -> ASGIApp:
    source = _DataSource()
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
    permission = action_permission_requirement("archive", admin_id="ops")
    action = ActionDefinition(
        action_id="archive",
        label="Archive selected",
        scope=ActionScope.BULK,
        resource_id="orders",
        permission=permission,
        executor=_executor(),
        bulk_policy=BulkPolicy(require_concurrency_snapshot=False),
    )
    bind_action_web_presentation(
        action,
        ActionPresentation(intent=ActionIntent.PRIMARY),
    )
    builder = ApplicationBuilder(admin_id="ops")
    builder.add_resource(definition, source)
    builder.add_action(action)
    compiled = compile_application(builder)
    service = ResourceService(source)
    templates = build_templates(())
    token_service = TokenService.single_key(
        key_id="bulk-list",
        value=SecretValue("x" * 32),
        admin_id="ops",
    )

    async def allow(_request: Request) -> bool:
        return True

    @asynccontextmanager
    async def operation_scope() -> AsyncIterator[ServiceResolver]:
        raise AssertionError("list rendering must not open an operation scope")
        yield  # pragma: no cover

    build_admin_bulk_action_routes(
        compiled=compiled,
        resource_services={"orders": service},
        concurrency_providers={},
        templates=templates,
        verify_csrf=allow,
        verify_submission_token=allow,
        issue_submission_token=lambda _request: "token",
        token_service=token_service,
        idempotency_store=_MemoryIdempotencyStore(),
        admin_id="ops",
        superuser_bypass=False,
        deadline_seconds=30,
        operation_scope=operation_scope,
        unit_of_work_factory=lambda: None,
        label="Operations",
    )
    app = Starlette(
        routes=build_resource_routes(
            ResourceBinding(definition=definition, service=service, templates=templates)
        )
    )
    return _PrincipalApp(app, frozenset(permission.permissions))


@pytest.mark.anyio
async def test_bulk_list_launchers_are_real_no_js_submit_controls() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_bulk_list_app()),
        base_url="http://test",
    ) as client:
        response = await client.get("/orders")

    assert response.status_code == 200
    button = re.search(
        r'<button[^>]+formaction="/orders/_actions/archive"[^>]*>',
        response.text,
    )
    assert button is not None
    assert "disabled" not in button.group(0)
    assert response.text.count('name="selected"') == 2


def _action_app(
    action: ActionDefinition,
    presentation: ActionPresentation | None = None,
) -> Starlette:
    permission = action_permission_requirement(str(action.action_id), admin_id="ops")
    definition = action.model_copy(update={"permission": permission})
    if presentation is not None:
        bind_action_web_presentation(definition, presentation)
    compiled = CompiledActionDefinition(definition=definition, permission=permission)
    route = RouteDefinition(
        route_name=f"resource:orders:action:{definition.action_id}",
        methods=("GET", "POST"),
        path=f"/orders/_actions/{definition.action_id}",
        owner_id="orders",
    )
    token_service = TokenService.single_key(
        key_id="action-ui",
        value=SecretValue("x" * 32),
        admin_id="ops",
    )

    async def allow(_request: Request) -> bool:
        return True

    async def authorize(
        _request: Request,
        compiled_action: CompiledActionDefinition,
        identity: RecordIdentity | None,
    ) -> OperationAuthorization:
        return OperationAuthorization.for_requirement(
            admin_id="ops",
            resource_id="orders",
            operation=f"action:{compiled_action.definition.action_id}",
            principal_id="operator",
            requirement=compiled_action.permission,
            target_identity=identity,
        )

    binding = ActionBinding(
        routes=((route, compiled),),
        templates=build_templates(()),
        codec=IdentityCodec(),
        verify_csrf=allow,
        verify_submission_token=allow,
        issue_submission_token=lambda _request: "submission",
        authorize_action=authorize,
        token_service=token_service,
    )
    return Starlette(routes=build_action_routes(binding))


@pytest.mark.anyio
async def test_action_form_and_confirmation_render_semantic_intent_aware_html() -> None:
    form_action = ActionDefinition(
        action_id="note",
        label="Add note",
        scope=ActionScope.RESOURCE,
        resource_id="orders",
        input_schema=FormSchema(
            fields=(
                FieldDefinition(
                    field_id="note",
                    python_type=str,
                    label="Note",
                    required=True,
                ),
            )
        ),
        executor=_executor(),
        needs_form=True,
    )
    safe_confirm = ActionDefinition(
        action_id="sync",
        label="Sync orders",
        scope=ActionScope.RESOURCE,
        resource_id="orders",
        preview=lambda _context: ActionPreview(
            title="Sync orders",
            description="Review the synchronization.",
            impact="One synchronization will run.",
        ),
        executor=_executor(),
        needs_preview=True,
        needs_confirmation=True,
    )
    danger_confirm = safe_confirm.model_copy(update={"action_id": "purge", "label": "Purge orders"})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_action_app(form_action)),
        base_url="http://test",
    ) as client:
        form_response = await client.get("/orders/_actions/note")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_action_app(safe_confirm)),
        base_url="http://test",
    ) as client:
        safe_response = await client.get("/orders/_actions/sync")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=_action_app(
                danger_confirm,
                ActionPresentation(intent=ActionIntent.DANGER),
            )
        ),
        base_url="http://test",
    ) as client:
        danger_response = await client.get("/orders/_actions/purge")

    assert form_response.status_code == 200
    assert "text-rakit-" in form_response.text
    assert 'name="csrf_token"' in form_response.text
    assert 'name="submission_token"' in form_response.text
    assert safe_response.status_code == 200
    assert "rakit-button-danger" not in safe_response.text
    assert 'name="confirmation_token"' in safe_response.text
    assert danger_response.status_code == 200
    assert "rakit-button-danger" in danger_response.text

    templates = build_templates(())
    for template_name in (
        "actions/_form.html",
        "actions/_confirm.html",
        "actions/bulk.html",
    ):
        source, _, _ = templates.env.loader.get_source(templates.env, template_name)
        assert "text-slate-" not in source
        assert "bg-slate-" not in source
