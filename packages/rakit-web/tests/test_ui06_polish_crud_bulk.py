from collections.abc import Mapping
from pathlib import Path

import httpx
import pytest
from rakit_core.auth import Principal
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import ResourceDefinition, ResourceFieldPolicy
from rakit_core.forms import FormSchema
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.mutations import MutationAuthorization, MutationOperation
from rakit_core.permissions import PermissionRequirement
from rakit_core.query import PagePagination, PageResult, ResourceQuery
from rakit_core.resources import ResourceService
from rakit_web.bulk_delete import BuiltInBulkDeleteBinding, build_builtin_bulk_delete_routes
from rakit_web.form_routes import WriteResourceBinding
from rakit_web.resource_routes import ResourceBinding, ResourceCrudPaths, build_templates
from rakit_web.security.authentication import build_requirement_resolver
from starlette.applications import Starlette
from starlette.requests import Request


class _DataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query: ResourceQuery) -> PageResult[dict[str, object]]:
        pagination = query.pagination
        if not isinstance(pagination, PagePagination):
            raise ValueError("test datasource supports page pagination only")
        return PageResult(
            items=({"id": 1, "name": "One"},),
            page=pagination.page,
            per_page=pagination.per_page,
            has_previous=False,
            has_next=False,
            total_count=1,
        )

    async def count(self, query: ResourceQuery) -> int:
        del query
        return 1

    async def detail(self, identity: RecordIdentity) -> dict[str, object]:
        return {"id": identity.values["id"], "name": "One"}

    def identity_for(self, record: object) -> RecordIdentity:
        if not isinstance(record, Mapping):
            raise TypeError("record must be a mapping")
        value = record.get("id")
        if not isinstance(value, int | str) or isinstance(value, bool):
            raise TypeError("record id must be an identity scalar")
        return RecordIdentity(values={"id": value})


class _WriteService:
    async def create(
        self,
        submitted: Mapping[str, object],
        *,
        authorization: MutationAuthorization | None = None,
    ) -> object:
        del submitted, authorization
        return {"id": 1}

    async def get(self, identity: RecordIdentity) -> object | None:
        return {"id": identity.values["id"], "name": "One"}

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
        del submitted, concurrency_token, authorization
        return {"id": identity.values["id"]}

    async def issue_delete_token(self, identity: RecordIdentity) -> str:
        return f"delete:{identity.values['id']}"

    async def delete(
        self,
        confirmation_token: str,
        *,
        identity: RecordIdentity,
        authorization: MutationAuthorization | None = None,
    ) -> None:
        del confirmation_token, identity, authorization


def _resource_definition() -> ResourceDefinition:
    return ResourceDefinition(
        resource_id="orders",
        path="/orders",
        label="Orders",
        singular_label="Order",
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "name"),
            detail_fields=("id", "name"),
        ),
    )


def _request(principal: Principal) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/orders",
            "root_path": "",
            "scheme": "http",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
            "state": {"principal": principal},
        }
    )


def _source_text(relative: str) -> str:
    return (Path(__file__).parents[1] / "src" / "rakit_web" / relative).read_text()


def test_ui06_polish_theme_popover_select_and_select_all_contracts() -> None:
    base = _source_text("templates/base.html")
    sidebar = _source_text("templates/components/admin_navigation.html")
    actions = _source_text("templates/components/actions.html")
    table = _source_text("templates/resources/_table.html")
    theme_js = _source_text("static/theme.js")
    ui_js = _source_text("static/rakit-ui.js")
    css = _source_text("assets/rakit.css")

    assert 'theme_menu_placement = "down"' in base
    assert 'theme_menu_placement = "up"' in sidebar
    assert "focus({ preventScroll: true })" in theme_js

    assert 'class="rakit-popover right-0 left-auto min-w-56"' in actions
    assert 'class="rakit-popover min-w-56"' in table
    assert "rakitOpenDetailPopovers" in ui_js

    assert "appearance-none" in css
    assert "calc(100% - 1rem)" in css
    assert "data-rakit-select-page" in table
    assert "data-rakit-select-row" in table
    assert 'name="selected"' in table
    assert "data-rakit-bulk-dialog" in table
    assert "rakitSyncBulkSelection" in ui_js
    assert "rakitOpenBulkReview" in ui_js


def test_bulk_delete_route_requires_exact_delete_permission() -> None:
    resolve = build_requirement_resolver(
        admin_id="ops",
        resource_paths={"/orders": "orders"},
        writable_resources=frozenset({"orders"}),
    )

    requirement = resolve("/orders/_bulk/delete-selected", "GET")

    assert requirement == PermissionRequirement.all_of("ops.resources.orders.delete")


def test_resource_crud_presentation_is_gated_per_operation() -> None:
    binding = ResourceBinding(
        definition=_resource_definition(),
        service=ResourceService(_DataSource()),
        templates=build_templates(()),
        crud_paths=ResourceCrudPaths(
            create_path="/orders/new",
            update_path="/orders/{identity}/edit",
            delete_path="/orders/{identity}/delete",
        ),
        admin_id="ops",
        auth_enabled=True,
    )
    principal = Principal(
        subject_id="operator",
        authenticated=True,
        permissions=frozenset(
            {
                "ops.resources.orders.read",
                "ops.resources.orders.update",
                "ops.resources.orders.delete",
            }
        ),
    )
    request = _request(principal)

    assert binding.can_mutate(request, "create") is False
    assert binding.can_mutate(request, "update") is True
    assert binding.can_mutate(request, "delete") is True


async def _allow(request: Request) -> bool:
    del request
    return True


async def _authorize_delete(
    request: Request,
    operation: MutationOperation,
    identity: RecordIdentity | None,
) -> MutationAuthorization | None:
    del request
    requirement = PermissionRequirement.all_of(f"ops.resources.orders.{operation}")
    return MutationAuthorization.for_requirement(
        admin_id="ops",
        resource_id="orders",
        operation=operation,
        principal_id="operator",
        requirement=requirement,
        target_identity=identity,
    )


def _bulk_delete_app() -> Starlette:
    templates = build_templates(())
    write = WriteResourceBinding(
        path="/orders",
        label="Orders",
        form_schema=FormSchema(fields=()),
        mutation_service=_WriteService(),
        templates=templates,
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda request: "submission-token",
        resource_id="orders",
        mutation_authorizer=_authorize_delete,
    )
    token_service = TokenService.single_key(
        key_id="bulk-delete",
        value=SecretValue("x" * 32),
        admin_id="ops",
    )
    binding = BuiltInBulkDeleteBinding(
        write=write,
        identity_fields=("id",),
        templates=templates,
        token_service=token_service,
        label="Operations",
    )
    return Starlette(routes=build_builtin_bulk_delete_routes(binding))


@pytest.mark.anyio
async def test_builtin_bulk_delete_empty_selection_has_styled_full_page_feedback() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_bulk_delete_app()),
        base_url="http://test",
    ) as client:
        response = await client.get("/orders/_bulk/delete-selected")

    assert response.status_code == 400
    assert "Bulk action needs attention" in response.text
    assert "Select at least one resource" in response.text
    assert "rakit-alert" in response.text
    assert "<!doctype html>" in response.text


@pytest.mark.anyio
async def test_builtin_bulk_delete_dialog_review_reuses_server_confirmation_transport() -> None:
    encoded = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_bulk_delete_app()),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/orders/_bulk/delete-selected",
            params={"selected": encoded},
            headers={"X-Rakit-Dialog": "bulk"},
        )

    assert response.status_code == 200
    assert "Delete selected orders" in response.text
    assert 'name="selected"' in response.text
    assert f'value="{encoded}"' in response.text
    assert 'name="delete_token" value="delete:1"' in response.text
    assert 'name="confirmation_token"' in response.text
    assert 'name="submission_token"' in response.text
    assert "<!doctype html>" not in response.text
