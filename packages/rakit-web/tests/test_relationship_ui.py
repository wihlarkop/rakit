from dataclasses import dataclass
from typing import Any, cast

import httpx
import pytest
from rakit_core.errors import RakitError
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormLayout, FormSchema, RelationshipPanel
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.mutations import MutationAuthorization, OperationAuthorizationSet
from rakit_core.query import PageResult, ResourceQuery
from rakit_core.relationship_mutations import (
    ClearRelated,
    CreateRelated,
    SetRelated,
    UnlinkRelated,
    UpdateAssociationRelated,
)
from rakit_core.relationships import (
    CompiledRelationship,
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipEditMode,
    RelationshipKind,
)
from rakit_core.resources import ResourceService
from rakit_web.form_routes import WriteResourceBinding, build_write_routes
from rakit_web.relationship_routes import (
    RelationshipEditorBinding,
    RelationshipFormBinding,
    build_relationship_changes,
    build_relationship_routes,
    relationship_prefix,
)
from rakit_web.resource_routes import build_templates
from starlette.applications import Starlette


@dataclass
class Record:
    id: int
    label: str


class CandidateSource:
    identity_fields = ("id",)

    def __init__(self) -> None:
        self.records = (Record(1, "Ada"), Record(2, "Grace"))

    def identity_for(self, record: Record) -> RecordIdentity:
        return RecordIdentity(values={"id": record.id})

    async def list(self, query: ResourceQuery) -> PageResult[Record]:
        records = self.records
        if query.search:
            records = tuple(record for record in records if query.search in record.label)
        start = query.pagination.offset
        items = records[start : start + query.pagination.per_page]
        return PageResult(
            items=items,
            page=query.pagination.page,
            per_page=query.pagination.per_page,
            has_previous=query.pagination.page > 1,
            has_next=start + len(items) < len(records),
            total_count=len(records),
        )


class EditorProvider:
    def __init__(self) -> None:
        self.rows = {
            "customer": (Record(1, "Ada"),),
            "required_customer": (Record(1, "Ada"),),
            "items": (Record(1, "Ada"), Record(2, "Grace")),
        }

    async def editor_page(
        self, parent_identity, relationship_id, *, child_fields=(), page=1, per_page=25
    ):
        from rakit_core.relationship_mutations import RelationshipCandidate, RelationshipEditorRow

        rows = tuple(
            RelationshipEditorRow(
                candidate=RelationshipCandidate(
                    identity=RecordIdentity(values={"id": record.id}), label=record.label
                ),
                values={field: f"{record.label}-{field}" for field in child_fields},
                concurrency_token=f"child-{record.id}",
            )
            for record in self.rows[relationship_id]
        )
        start = (page - 1) * per_page
        items = rows[start : start + per_page]
        return PageResult(
            items=items,
            page=page,
            per_page=per_page,
            has_previous=page > 1,
            has_next=start + per_page < len(rows),
            total_count=len(rows),
        )

    async def issue_concurrency_token(self, parent_identity, relationship_id):
        return f"relationship-{relationship_id}"


class GraphService:
    record = Record(10, "Order")

    def __init__(self) -> None:
        self.graph_updates: list[tuple[RecordIdentity | None, object, dict[str, object]]] = []

    async def get(self, identity):
        return self.record if identity.values == {"id": 10} else None

    def issue_update_token(self, _record):
        return "parent-token"

    async def update_graph(self, identity, submitted, **kwargs):
        self.graph_updates.append((identity, submitted, kwargs))
        return object()

    async def create_graph(self, submitted, **kwargs):
        self.graph_updates.append((None, submitted, kwargs))
        return object()

    async def create(self, submitted, *, authorization=None):
        return object()

    async def update(self, identity, submitted, *, concurrency_token=None, authorization=None):
        return object()

    async def issue_delete_token(self, identity):
        return "delete"

    async def delete(self, confirmation_token, *, identity, authorization=None):
        return None


async def _allow(_request) -> bool:
    return True


async def _authorization(_request, operation, identity):
    return MutationAuthorization(
        admin_id="admin",
        resource_id="orders",
        operation=operation,
        principal_id="tester",
        permissions=("admin.resources.orders.update",),
        target_identity=identity,
    )


async def _graph_authorization(_request, root, parent_identity, changes):
    capabilities = [
        MutationAuthorization(
            admin_id="admin",
            resource_id="orders",
            operation=change.operation_id,
            principal_id="tester",
            permissions=("admin.resources.orders.update",),
            target_identity=parent_identity,
        )
        for change in changes
    ]
    return OperationAuthorizationSet(root=root, capabilities=tuple(capabilities))


async def _relationship_editor_authorization(_request, _relationship_id, _parent_identity) -> bool:
    return True


def _compiled(
    relationship_id: str,
    *,
    kind=RelationshipKind.MANY_TO_ONE,
    cardinality=RelationshipCardinality.TO_ONE,
    edit_mode=RelationshipEditMode.LINK,
    nullable=True,
):
    definition = RelationshipDefinition(
        relationship_id=relationship_id,
        target_resource_id="people",
        label=relationship_id.title(),
        kind=kind,
        cardinality=cardinality,
        nullable=nullable,
        writable=True,
        edit_mode=edit_mode,
        record_label_field="label",
    )
    return CompiledRelationship(
        source_resource_id="orders",
        definition=definition,
        mutation_permission=MutationAuthorization(
            admin_id="admin",
            resource_id="orders",
            operation="update",
            principal_id="tester",
            permissions=("admin.resources.orders.update",),
        ).requirement,
        target_delete_permission=None,
        route_path=f"/orders/{{identity}}/_relationships/{relationship_id}",
    )


def _binding(
    *, relationship_form: RelationshipFormBinding
) -> tuple[WriteResourceBinding, GraphService]:
    service = GraphService()
    binding = WriteResourceBinding(
        path="/orders",
        label="Order",
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="status", python_type=str, required=True),),
            update_layout=FormLayout(
                children=(
                    RelationshipPanel(layout_id="customer-panel", relationship_id="customer"),
                    RelationshipPanel(layout_id="items-panel", relationship_id="items"),
                )
            ),
        ),
        mutation_service=service,
        templates=build_templates(()),
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: "submission",
        mutation_authorizer=_authorization,
        relationship_form=relationship_form,
        graph_mutation_authorizer=_graph_authorization,
        relationship_editor_authorizer=_relationship_editor_authorization,
    )
    return binding, service


def _relationship_form() -> RelationshipFormBinding:
    source = CandidateSource()
    provider = EditorProvider()
    customer = RelationshipEditorBinding(
        relationship=_compiled("customer"),
        target_service=ResourceService(cast(Any, source)),
        state_provider=provider,
        target_search_fields=("label",),
    )
    items = RelationshipEditorBinding(
        relationship=_compiled(
            "items",
            kind=RelationshipKind.ONE_TO_MANY,
            cardinality=RelationshipCardinality.TO_MANY,
            edit_mode=RelationshipEditMode.INLINE,
        ),
        target_service=ResourceService(cast(Any, source)),
        state_provider=provider,
        target_form_schema=FormSchema(
            fields=(FieldDefinition(field_id="sku", python_type=str, required=True),)
        ),
    )
    return RelationshipFormBinding(editors=(customer, items))


@pytest.mark.anyio
async def test_relationship_editors_are_scoped_and_final_post_uses_graph_update() -> None:
    form = _relationship_form()
    binding, service = _binding(relationship_form=form)
    routes = [*build_write_routes(binding), *build_relationship_routes(binding, form)]
    app = Starlette(routes=routes)
    codec = IdentityCodec()
    encoded_parent = codec.encode(RecordIdentity(values={"id": 10}))
    grace = codec.encode(RecordIdentity(values={"id": 2}))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        edit = await client.get(f"/orders/{encoded_parent}/edit")
        assert edit.status_code == 200
        assert "Ada" in edit.text
        options = await client.get(
            f"/orders/{encoded_parent}/_relationships/customer/options?q=Grace",
            headers={"HX-Request": "true"},
        )
        assert "Grace" in options.text
        assert "Ada" not in options.text
        result = await client.post(
            f"/orders/{encoded_parent}/edit",
            data={
                "status": "draft-changed",
                "csrf_token": "csrf",
                "submission_token": "submission",
                "concurrency_token": "parent-token",
                f"{relationship_prefix('customer')}set": grace,
            },
            follow_redirects=False,
        )
    assert result.status_code == 303
    _, state, kwargs = cast(tuple[RecordIdentity, Any, dict[str, Any]], service.graph_updates[-1])
    assert dict(state.normalized) == {"status": "draft-changed"}
    steps = kwargs["relationship_changes"][0].steps
    assert isinstance(steps[0], SetRelated)
    assert steps[0].identity.values == {"id": 2}


@pytest.mark.anyio
async def test_inline_fragment_preserves_unsaved_child_values_without_writing() -> None:
    form = _relationship_form()
    binding, service = _binding(relationship_form=form)
    app = Starlette(
        routes=[*build_write_routes(binding), *build_relationship_routes(binding, form)]
    )
    encoded_parent = IdentityCodec().encode(RecordIdentity(values={"id": 10}))
    prefix = relationship_prefix("items")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/orders/{encoded_parent}/_relationships/items/page/2",
            data={
                "status": "draft-changed",
                "csrf_token": "csrf",
                f"{prefix}create__new-a__sku": "X",
            },
            headers={"HX-Request": "true"},
        )
    assert response.status_code == 200
    assert 'value="X"' in response.text
    assert service.graph_updates == []


@pytest.mark.anyio
async def test_parent_create_posts_inline_child_through_graph_root() -> None:
    form = _relationship_form()
    binding, service = _binding(relationship_form=form)
    app = Starlette(routes=build_write_routes(binding))
    prefix = relationship_prefix("items")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/orders/new",
            data={
                "status": "new-order",
                "csrf_token": "csrf",
                "submission_token": "submission",
                f"{prefix}create__new-line__sku": "SKU-1",
            },
            follow_redirects=False,
        )
    assert response.status_code == 303
    parent, state, kwargs = service.graph_updates[-1]
    assert parent is None
    assert dict(cast(Any, state).normalized) == {"status": "new-order"}
    steps = cast(Any, kwargs["relationship_changes"])[0].steps
    assert isinstance(steps[0], CreateRelated)
    assert dict(steps[0].values) == {"sku": "SKU-1"}


@pytest.mark.anyio
async def test_relationship_parser_uses_typed_create_and_clear_steps() -> None:
    source = CandidateSource()
    provider = EditorProvider()
    customer = RelationshipEditorBinding(
        relationship=_compiled("customer"),
        target_service=ResourceService(cast(Any, source)),
        state_provider=provider,
    )
    items = RelationshipEditorBinding(
        relationship=_compiled(
            "items",
            kind=RelationshipKind.ONE_TO_MANY,
            cardinality=RelationshipCardinality.TO_MANY,
            edit_mode=RelationshipEditMode.INLINE,
        ),
        target_service=ResourceService(cast(Any, source)),
        state_provider=provider,
        target_form_schema=FormSchema(
            fields=(FieldDefinition(field_id="sku", python_type=str, required=True),)
        ),
    )
    changes = await build_relationship_changes(
        RelationshipFormBinding(editors=(customer, items)),
        {
            f"{relationship_prefix('customer')}clear": "true",
            f"{relationship_prefix('items')}create__new-a__sku": "X",
        },
        parent_identity=RecordIdentity(values={"id": 10}),
    )
    assert isinstance(changes[0].steps[0], ClearRelated)
    assert any(isinstance(step, CreateRelated) for step in changes[1].steps)


@pytest.mark.anyio
async def test_association_fields_use_declared_schema_and_typed_step() -> None:
    source = CandidateSource()

    class AssociationProvider(EditorProvider):
        async def editor_page(
            self, parent_identity, relationship_id, *, child_fields=(), page=1, per_page=25
        ):
            from rakit_core.relationship_mutations import (
                RelationshipCandidate,
                RelationshipEditorRow,
            )

            assert relationship_id == "enrollments"
            return PageResult(
                items=(
                    RelationshipEditorRow(
                        candidate=RelationshipCandidate(
                            identity=RecordIdentity(values={"id": 2}), label="Grace"
                        ),
                        association_identity=RecordIdentity(values={"id": 99}),
                        values={"grade": "B"},
                    ),
                ),
                page=page,
                per_page=per_page,
                has_previous=False,
                has_next=False,
            )

    requirement = _compiled("customer").mutation_permission
    definition = RelationshipDefinition(
        relationship_id="enrollments",
        target_resource_id="people",
        label="Enrollments",
        kind=RelationshipKind.ASSOCIATION_OBJECT,
        cardinality=RelationshipCardinality.TO_MANY,
        writable=True,
        edit_mode=RelationshipEditMode.INLINE,
        record_label_field="label",
        association_fields=("grade",),
        association_target_resource_id="people",
    )
    association = RelationshipEditorBinding(
        relationship=CompiledRelationship(
            source_resource_id="orders",
            definition=definition,
            mutation_permission=requirement,
            target_delete_permission=None,
            route_path="/orders/{identity}/_relationships/enrollments",
        ),
        target_service=ResourceService(cast(Any, source)),
        state_provider=AssociationProvider(),
        association_form_schema=FormSchema(
            fields=(FieldDefinition(field_id="grade", python_type=str, required=True),)
        ),
    )
    codec = IdentityCodec()
    target = codec.encode(RecordIdentity(values={"id": 2}))
    changes = await build_relationship_changes(
        RelationshipFormBinding(editors=(association,)),
        {
            f"{relationship_prefix('enrollments')}association__{target}__grade": "A",
        },
        parent_identity=RecordIdentity(values={"id": 10}),
    )
    step = changes[0].steps[0]
    assert isinstance(step, UpdateAssociationRelated)
    assert dict(step.values) == {"grade": "A"}

    with pytest.raises(RakitError):
        await build_relationship_changes(
            RelationshipFormBinding(editors=(association,)),
            {
                f"{relationship_prefix('enrollments')}association__{target}__secret": "no",
            },
            parent_identity=RecordIdentity(values={"id": 10}),
        )


@pytest.mark.anyio
async def test_unknown_relationship_control_is_rejected_without_a_scalar_exception() -> None:
    with pytest.raises(RakitError):
        await build_relationship_changes(
            _relationship_form(),
            {f"{relationship_prefix('customer')}unexpected": "value"},
            parent_identity=RecordIdentity(values={"id": 10}),
        )


@pytest.mark.anyio
async def test_to_many_omission_is_noop_and_unlink_is_explicit() -> None:
    form = _relationship_form()
    no_intent = await build_relationship_changes(
        form,
        {f"{relationship_prefix('items')}selection_present": "true"},
        parent_identity=RecordIdentity(values={"id": 10}),
    )
    assert no_intent == ()

    encoded = IdentityCodec().encode(RecordIdentity(values={"id": 2}))
    changes = await build_relationship_changes(
        form,
        {f"{relationship_prefix('items')}unlink__{encoded}": encoded},
        parent_identity=RecordIdentity(values={"id": 10}),
    )
    assert isinstance(changes[0].steps[0], UnlinkRelated)
    assert changes[0].steps[0].identity.values == {"id": 2}


@pytest.mark.anyio
async def test_non_nullable_to_one_clear_is_rejected() -> None:
    source = CandidateSource()
    editor = RelationshipEditorBinding(
        relationship=_compiled("required_customer", nullable=False),
        target_service=ResourceService(cast(Any, source)),
        state_provider=EditorProvider(),
    )
    with pytest.raises(RakitError):
        await build_relationship_changes(
            RelationshipFormBinding(editors=(editor,)),
            {f"{relationship_prefix('required_customer')}clear": "true"},
            parent_identity=RecordIdentity(values={"id": 10}),
        )
