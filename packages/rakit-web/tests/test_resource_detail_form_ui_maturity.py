from collections.abc import Mapping

import httpx
import pytest
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import ResourceDefinition, ResourceFieldPolicy
from rakit_core.fields import FieldDefinition, FileField
from rakit_core.forms import FormSchema
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.mutations import MutationAuthorization, MutationOperation
from rakit_core.query import PagePagination, PageResult, ResourceQuery
from rakit_core.resources import ResourceService
from rakit_web.form_routes import WriteResourceBinding, build_write_routes
from rakit_web.resource_routes import (
    ResourceBinding,
    ResourceCrudPaths,
    build_resource_routes,
    build_templates,
)
from starlette.applications import Starlette
from starlette.routing import Mount


class _ResourceDataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name", "optional", "zero", "flag")
    identity_fields = ("id",)

    def __init__(self) -> None:
        self.record: dict[str, object] = {
            "id": 1,
            "name": "Visible record",
            "optional": None,
            "zero": 0,
            "flag": False,
        }

    async def list(self, query: ResourceQuery) -> PageResult[dict[str, object]]:
        pagination = query.pagination
        if not isinstance(pagination, PagePagination):
            raise ValueError("_ResourceDataSource supports page-number pagination only")
        return PageResult(
            items=(self.record,),
            page=pagination.page,
            per_page=pagination.per_page,
            has_previous=False,
            has_next=False,
            total_count=1,
        )

    async def count(self, query: ResourceQuery) -> int:
        del query
        return 1

    async def detail(self, identity: RecordIdentity) -> dict[str, object] | None:
        return self.record if identity.values == {"id": 1} else None

    def identity_for(self, record: object) -> RecordIdentity:
        del record
        return RecordIdentity(values={"id": 1})


def _resource_app(*, crud_paths: ResourceCrudPaths | None) -> tuple[Starlette, str]:
    definition = ResourceDefinition(
        resource_id="records",
        path="/records",
        label="Records",
        singular_label="Record",
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "name", "optional"),
            detail_fields=("id", "name", "optional", "zero", "flag"),
            sort_fields=("id", "name"),
        ),
    )
    binding = ResourceBinding(
        definition=definition,
        service=ResourceService(_ResourceDataSource()),
        templates=build_templates(()),
        crud_paths=crud_paths,
    )
    encoded = binding.codec.encode(RecordIdentity(values={"id": 1}))
    return Starlette(routes=build_resource_routes(binding)), encoded


@pytest.mark.anyio
async def test_resource_crud_affordances_use_mounted_canonical_server_paths() -> None:
    child, encoded = _resource_app(
        crud_paths=ResourceCrudPaths(
            create_path="/records/new",
            update_path="/records/{identity}/edit",
            delete_path="/records/{identity}/delete",
        )
    )
    app = Starlette(routes=[Mount("/admin", app=child)])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        listed = await client.get("/admin/records")
        detailed = await client.get(f"/admin/records/{encoded}")

    assert listed.status_code == 200
    assert 'href="/admin/records/new"' in listed.text
    assert "Create Record" in listed.text

    assert detailed.status_code == 200
    assert f'href="/admin/records/{encoded}/edit"' in detailed.text
    assert f'href="/admin/records/{encoded}/delete"' in detailed.text
    assert ">Edit</a>" in detailed.text
    assert ">Delete</a>" in detailed.text


def test_create_only_write_capability_does_not_claim_record_write_routes() -> None:
    create_only = _CreateOnlyMutationService()
    full = _FullMutationService()
    create_binding = _write_binding(create_only)
    full_binding = _write_binding(full)

    assert create_binding.has_record_write_routes is False
    assert full_binding.has_record_write_routes is True


@pytest.mark.anyio
async def test_create_only_resource_presentation_omits_edit_and_delete() -> None:
    app, encoded = _resource_app(crud_paths=ResourceCrudPaths(create_path="/records/new"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        listed = await client.get("/records")
        detailed = await client.get(f"/records/{encoded}")

    assert 'href="/records/new"' in listed.text
    assert ">Edit</a>" not in detailed.text
    assert ">Delete</a>" not in detailed.text


@pytest.mark.anyio
async def test_detail_uses_visible_fields_for_title_and_display_only_missing_value() -> None:
    app, encoded = _resource_app(crud_paths=None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/records/{encoded}")

    assert response.status_code == 200
    assert "data-rakit-record-title>Visible record</h1>" in response.text
    assert ">—</dd>" in response.text
    assert ">0</dd>" in response.text
    assert ">False</dd>" in response.text


class _CreateOnlyMutationService:
    async def create(
        self,
        submitted: Mapping[str, object],
        *,
        authorization: MutationAuthorization | None = None,
    ) -> object:
        del authorization
        return submitted


class _Record:
    name = "Ada"


class _FullMutationService(_CreateOnlyMutationService):
    record = _Record()

    async def get(self, identity: RecordIdentity) -> object | None:
        return self.record if identity.values == {"id": 1} else None

    def issue_update_token(self, record: object) -> str:
        assert record is self.record
        return "revision-token"

    async def update(
        self,
        identity: RecordIdentity,
        submitted: Mapping[str, object],
        *,
        concurrency_token: str | None,
        authorization: MutationAuthorization | None = None,
    ) -> object:
        del identity, submitted, concurrency_token, authorization
        return self.record

    async def issue_delete_token(self, identity: RecordIdentity) -> str:
        assert identity.values == {"id": 1}
        return "delete-token"

    async def delete(
        self,
        confirmation_token: str,
        *,
        identity: RecordIdentity,
        authorization: MutationAuthorization | None = None,
    ) -> None:
        del confirmation_token, identity, authorization


async def _allow(_request: object) -> bool:
    return True


async def _allow_mutation(
    _request: object,
    operation: MutationOperation,
    _identity: RecordIdentity | None,
) -> MutationAuthorization:
    return MutationAuthorization(
        admin_id="admin",
        resource_id="records",
        operation=operation,
        principal_id="tester",
        permissions=(f"admin.resources.records.{operation}",),
    )


def _write_binding(
    service: _CreateOnlyMutationService,
    *,
    include_file: bool = False,
) -> WriteResourceBinding:
    fields: tuple[FieldDefinition, ...]
    if include_file:
        fields = (
            FieldDefinition(
                field_id="name",
                python_type=str,
                label="Name",
                required=True,
                description="Visible record name.",
            ),
            FileField(field_id="attachment", label="Attachment"),
        )
    else:
        fields = (
            FieldDefinition(
                field_id="name",
                python_type=str,
                label="Name",
                required=True,
                description="Visible record name.",
            ),
        )
    return WriteResourceBinding(
        path="/records",
        label="Record",
        form_schema=FormSchema(fields=fields),
        mutation_service=service,
        templates=build_templates(()),
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: "submission-token",
        mutation_authorizer=_allow_mutation,
    )


@pytest.mark.anyio
async def test_create_form_uses_semantic_field_file_required_and_safe_cancel_contracts() -> None:
    binding = _write_binding(_CreateOnlyMutationService(), include_file=True)
    app = Starlette(routes=build_write_routes(binding))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/records/new")

    assert response.status_code == 200
    assert 'data-rakit-breadcrumb="resource-form"' in response.text
    assert 'href="/records"' in response.text
    assert 'class="rakit-file-input"' in response.text
    assert "Visible record name." in response.text
    assert '<span class="rakit-field-required" aria-hidden="true"> *</span>' in response.text
    assert '<span class="sr-only"> required</span>' in response.text
    assert 'name="csrf_token"' in response.text
    assert 'name="submission_token" value="submission-token"' in response.text


@pytest.mark.anyio
async def test_update_form_cancel_returns_to_canonical_record_detail() -> None:
    binding = _write_binding(_FullMutationService())
    encoded = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    app = Starlette(routes=build_write_routes(binding))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/records/{encoded}/edit")

    assert response.status_code == 200
    assert f'href="/records/{encoded}"' in response.text
    assert 'name="concurrency_token" value="revision-token"' in response.text
    assert "Save changes" in response.text


@pytest.mark.anyio
async def test_delete_confirmation_is_truthful_and_preserves_security_tokens() -> None:
    binding = _write_binding(_FullMutationService())
    encoded = IdentityCodec().encode(RecordIdentity(values={"id": 1}))
    app = Starlette(routes=build_write_routes(binding))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/records/{encoded}/delete")

    assert response.status_code == 200
    assert "Delete Record?" in response.text
    assert "configured resource adapter" in response.text
    assert "permanent or recoverable" in response.text
    assert "Confirm only if you intend to remove this record." in response.text
    assert "cannot be undone" not in response.text.casefold()
    assert 'href="/records"' in response.text
    assert 'name="csrf_token"' in response.text
    assert 'name="submission_token" value="submission-token"' in response.text
    assert 'name="delete_token" value="delete-token"' in response.text
    assert "Delete record" in response.text
