"""Deterministic, non-persistent browser fixture for Plan 05 relationship UI review.

This stays beside the existing SQLAlchemy example so maintainers can inspect the
current server-rendered relationship controls without changing the framework or
the read-only example application.  Its in-memory graph service deliberately
does not persist a final Save: it is a visual/form-state review harness, not a
replacement for the Phase 3B persistence integration suite.
"""

from dataclasses import dataclass
from typing import Any, cast

from rakit_core.fields import FieldDefinition
from rakit_core.forms import FieldLayout, FormLayout, FormSchema, RelationshipPanel
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import MutationAuthorization, OperationAuthorizationSet
from rakit_core.permissions import PermissionRequirement
from rakit_core.query import PagePagination, PageResult, ResourceQuery
from rakit_core.relationship_mutations import (
    DeleteRelated,
    RelationshipCandidate,
    RelationshipChangePlan,
    RelationshipEditorRow,
)
from rakit_core.relationships import (
    CompiledRelationship,
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipDestructivePolicy,
    RelationshipEditMode,
    RelationshipKind,
    RelationshipOrderingDefinition,
)
from rakit_core.resources import ResourceService
from rakit_web.assets import static_files, static_url
from rakit_web.form_routes import WriteResourceBinding, build_write_routes
from rakit_web.relationship_routes import (
    RelationshipEditorBinding,
    RelationshipFormBinding,
    build_relationship_routes,
)
from rakit_web.resource_routes import build_templates
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Mount, Route


@dataclass
class DemoRecord:
    id: int
    label: str


@dataclass
class DemoOrder:
    id: int
    status: str


class Candidates:
    """A bounded, searchable source that mirrors the editor read contract."""

    identity_fields = ("id",)

    def __init__(self) -> None:
        self.records = tuple(DemoRecord(index, f"Candidate {index:02d}") for index in range(1, 61))

    def identity_for(self, record: DemoRecord) -> RecordIdentity:
        return RecordIdentity(values={"id": record.id})

    async def list(self, query: ResourceQuery) -> PageResult[DemoRecord]:
        search = (query.search or "").casefold()
        visible = tuple(record for record in self.records if search in record.label.casefold())
        pagination = query.pagination
        if not isinstance(pagination, PagePagination):
            raise ValueError("Candidates supports page-number pagination only")
        start = pagination.offset
        page = visible[start : start + pagination.per_page]
        return PageResult(
            items=page,
            page=pagination.page,
            per_page=pagination.per_page,
            has_previous=pagination.page > 1,
            has_next=start + len(page) < len(visible),
            total_count=len(visible),
        )


class DemoRelationshipState:
    """Read-only relationship state with enough rows to exercise pagination."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[RelationshipEditorRow, ...]] = {
            "customer": (self._row(1, "Candidate 01"),),
            "tags": tuple(self._row(index, f"Candidate {index:02d}") for index in range(11, 41)),
            "items": tuple(
                self._row(
                    index,
                    f"Line {index:02d}",
                    values={"sku": f"SKU-{index:03d}", "quantity": str(index)},
                )
                for index in range(21, 51)
            ),
            "courses": tuple(
                self._row(index, f"Course {index - 50:02d}", values={"grade": "B+"})
                for index in range(51, 55)
            ),
        }

    @staticmethod
    def _row(
        identity: int, label: str, *, values: dict[str, object] | None = None
    ) -> RelationshipEditorRow:
        return RelationshipEditorRow(
            candidate=RelationshipCandidate(
                identity=RecordIdentity(values={"id": identity}), label=label
            ),
            values=values or {},
            concurrency_token=f"demo-child-{identity}",
        )

    async def editor_page(
        self,
        parent_identity: RecordIdentity,
        relationship_id: str,
        *,
        child_fields: tuple[str, ...] = (),
        page: int = 1,
        per_page: int = 25,
    ) -> PageResult[RelationshipEditorRow]:
        rows = self.rows[relationship_id]
        start = (page - 1) * per_page
        return PageResult(
            items=rows[start : start + per_page],
            page=page,
            per_page=per_page,
            has_previous=page > 1,
            has_next=start + per_page < len(rows),
            total_count=len(rows),
        )

    async def issue_concurrency_token(
        self, parent_identity: RecordIdentity, relationship_id: str
    ) -> str:
        return f"demo-relationship-{relationship_id}"

    async def reorder_identities(
        self, parent_identity: RecordIdentity, relationship_id: str, *, maximum: int
    ) -> tuple[RecordIdentity, ...] | None:
        rows = self.rows[relationship_id]
        if relationship_id != "items" or len(rows) > maximum:
            return None
        return tuple(row.candidate.identity for row in rows)

    async def preview_destructive_impact(
        self, _plan: object, *, authorization: object
    ) -> tuple[RecordIdentity, ...]:
        return (RecordIdentity(values={"id": 1}),)

    async def issue_destructive_confirmation(self, _plan: object, *, authorization: object) -> str:
        return "demo-signed-relationship-confirmation"

    async def preview_child_delete(
        self, _parent: RecordIdentity, _relationship: str, _child: RecordIdentity
    ) -> object:
        return type("DeletePreview", (), {"relationship_impact": ("dependent attachment",)})()

    async def issue_child_delete_confirmation(
        self, _parent: RecordIdentity, _relationship: str, child: RecordIdentity
    ) -> str:
        return f"demo-signed-child-delete-{child.values['id']}"


class DemoGraphService:
    """Provides the final form contract without turning this browser fixture into a datastore."""

    def __init__(self) -> None:
        self.order = DemoOrder(id=10, status="draft")

    async def get(self, identity: RecordIdentity) -> DemoOrder | None:
        return self.order if identity.values == {"id": 10} else None

    def issue_update_token(self, _record: object) -> str:
        return "demo-parent-token"

    async def create_graph(self, submitted: Any, **_kwargs: object) -> DemoOrder:
        return DemoOrder(id=11, status=str(submitted.normalized.get("status", "draft")))

    async def update_graph(
        self, _identity: RecordIdentity, submitted: Any, **_kwargs: object
    ) -> DemoOrder:
        self.order.status = str(submitted.normalized.get("status", self.order.status))
        return self.order

    async def create(self, submitted: Any, *, authorization: object | None = None) -> DemoOrder:
        return await self.create_graph(submitted)

    async def update(
        self,
        identity: RecordIdentity,
        submitted: Any,
        *,
        concurrency_token: str | None,
        authorization: object | None = None,
    ) -> DemoOrder:
        return await self.update_graph(identity, submitted)

    async def issue_delete_token(self, identity: RecordIdentity) -> str:
        return "demo-delete-token"

    async def delete(
        self,
        confirmation_token: str,
        *,
        identity: RecordIdentity,
        authorization: object | None = None,
    ) -> None:
        return None


_PARENT_UPDATE = PermissionRequirement.all_of("demo.orders.update")
_CHILD_DELETE = PermissionRequirement.all_of("demo.items.delete")


def _relationship(
    relationship_id: str,
    *,
    label: str,
    kind: RelationshipKind,
    cardinality: RelationshipCardinality,
    mode: RelationshipEditMode,
    nullable: bool = True,
    ordering: RelationshipOrderingDefinition | None = None,
    association: bool = False,
    child_delete: bool = False,
) -> CompiledRelationship:
    definition = RelationshipDefinition(
        relationship_id=relationship_id,
        target_resource_id="candidates",
        association_target_resource_id="courses" if association else None,
        association_fields=("grade",) if association else (),
        label=label,
        kind=kind,
        cardinality=cardinality,
        nullable=nullable,
        ordered=ordering is not None,
        ordering=ordering,
        writable=True,
        edit_mode=mode,
        record_label_field="label",
        destructive_policy=RelationshipDestructivePolicy(
            allow_child_delete=child_delete, allow_delete_orphan=True
        ),
    )
    return CompiledRelationship(
        source_resource_id="orders",
        definition=definition,
        mutation_permission=_PARENT_UPDATE,
        target_delete_permission=_CHILD_DELETE if child_delete else None,
        target_create_permission=_PARENT_UPDATE if mode is RelationshipEditMode.INLINE else None,
        target_update_permission=_PARENT_UPDATE if mode is RelationshipEditMode.INLINE else None,
        ordering=ordering,
        route_path=f"/orders/{{identity}}/_relationships/{relationship_id}",
    )


def _positive_quantity(value: object) -> int:
    quantity = int(str(value))
    if quantity < 1:
        raise ValueError("quantity must be positive")
    return quantity


async def _allow(_request: Request) -> bool:
    return True


async def _authorize(
    _request: Request, operation: str, identity: RecordIdentity | None
) -> MutationAuthorization:
    return MutationAuthorization.for_requirement(
        admin_id="relationship-review",
        resource_id="orders",
        operation=operation,
        principal_id="local-reviewer",
        requirement=_PARENT_UPDATE,
        target_identity=identity,
    )


async def _authorize_graph(
    _request: Request,
    root: MutationAuthorization,
    parent: RecordIdentity | None,
    changes: tuple[object, ...],
) -> OperationAuthorizationSet:
    capabilities: list[MutationAuthorization] = []
    for change in cast(tuple[RelationshipChangePlan, ...], changes):
        operation_id = change.operation_id
        capabilities.append(
            MutationAuthorization.for_requirement(
                admin_id="relationship-review",
                resource_id="orders",
                operation=operation_id,
                principal_id="local-reviewer",
                requirement=_PARENT_UPDATE,
                target_identity=parent,
            )
        )
        for step in change.steps:
            if isinstance(step, DeleteRelated):
                capabilities.append(
                    MutationAuthorization.for_requirement(
                        admin_id="relationship-review",
                        resource_id="candidates",
                        operation=f"{operation_id}:target-delete",
                        principal_id="local-reviewer",
                        requirement=_CHILD_DELETE,
                        target_identity=step.identity,
                    )
                )
    return OperationAuthorizationSet(root=root, capabilities=tuple(capabilities))


async def _orders(_: Request) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<link rel='stylesheet' href='{static_url('rakit.css')}'>"
        "<title>Relationship UI Review</title>"
        "</head><body class='min-h-screen bg-slate-50 text-slate-900'>"
        "<main class='mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8'>"
        "<section class='rakit-panel p-4'>"
        "<p class='text-sm font-medium text-slate-500'>Rakit review fixture</p>"
        "<h1 class='mt-2 text-2xl font-semibold tracking-tight'>Relationship UI Review</h1>"
        "<p class='mt-3 text-sm leading-6 text-slate-600'>"
        "Inspect the compact relationship editor and its form-state interactions.</p>"
        "<div class='mt-6 flex flex-wrap gap-3'>"
        "<a class='rakit-button' href='/orders/new'>Create sample order</a>"
        "<a class='rakit-button rakit-button-secondary' "
        "href='/orders/eyJpZCI6MTB9/edit'>Edit populated order</a>"
        "</div></section></main></body></html>"
    )


def _binding() -> WriteResourceBinding:
    candidates = Candidates()
    state = DemoRelationshipState()
    source = ResourceService(cast(Any, candidates))
    items_ordering = RelationshipOrderingDefinition(position_field="position")
    editors = (
        RelationshipEditorBinding(
            relationship=_relationship(
                "customer",
                label="Customer",
                kind=RelationshipKind.MANY_TO_ONE,
                cardinality=RelationshipCardinality.TO_ONE,
                mode=RelationshipEditMode.LINK,
            ),
            target_service=source,
            state_provider=state,
            target_search_fields=("label",),
            candidate_page_size=12,
        ),
        RelationshipEditorBinding(
            relationship=_relationship(
                "tags",
                label="Tags",
                kind=RelationshipKind.MANY_TO_MANY,
                cardinality=RelationshipCardinality.TO_MANY,
                mode=RelationshipEditMode.LINK,
            ),
            target_service=source,
            state_provider=state,
            target_search_fields=("label",),
        ),
        RelationshipEditorBinding(
            relationship=_relationship(
                "items",
                label="Line items",
                kind=RelationshipKind.ONE_TO_MANY,
                cardinality=RelationshipCardinality.TO_MANY,
                mode=RelationshipEditMode.INLINE,
                ordering=items_ordering,
                child_delete=True,
            ),
            target_service=source,
            state_provider=state,
            target_form_schema=FormSchema(
                fields=(
                    FieldDefinition(field_id="sku", python_type=str, required=True),
                    FieldDefinition(
                        field_id="quantity",
                        python_type=int,
                        required=True,
                        parser=_positive_quantity,
                    ),
                )
            ),
            candidate_page_size=12,
            reorder_safe_maximum=40,
        ),
        RelationshipEditorBinding(
            relationship=_relationship(
                "courses",
                label="Course enrolments",
                kind=RelationshipKind.ASSOCIATION_OBJECT,
                cardinality=RelationshipCardinality.TO_MANY,
                mode=RelationshipEditMode.INLINE,
                association=True,
            ),
            target_service=source,
            state_provider=state,
            association_form_schema=FormSchema(
                fields=(FieldDefinition(field_id="grade", python_type=str, required=True),)
            ),
            candidate_page_size=12,
        ),
    )
    relationship_form = RelationshipFormBinding(editors=editors)
    form_schema = FormSchema(
        fields=(FieldDefinition(field_id="status", python_type=str, required=True),),
        layout=FormLayout(
            children=(
                FieldLayout("status"),
                RelationshipPanel(layout_id="customer", relationship_id="customer"),
                RelationshipPanel(layout_id="tags", relationship_id="tags"),
                RelationshipPanel(layout_id="items", relationship_id="items"),
                RelationshipPanel(layout_id="courses", relationship_id="courses"),
            )
        ),
    )
    return WriteResourceBinding(
        path="/orders",
        label="Order",
        form_schema=form_schema,
        mutation_service=DemoGraphService(),
        templates=build_templates(()),
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: "demo-submission-token",
        relationship_form=relationship_form,
        mutation_authorizer=_authorize,
        graph_mutation_authorizer=_authorize_graph,
        relationship_editor_authorizer=lambda _request, _id, _parent: _allow(_request),
    )


binding = _binding()
assert binding.relationship_form is not None
app = Starlette(
    routes=[
        Route("/orders", _orders),
        *build_write_routes(binding),
        *build_relationship_routes(binding, binding.relationship_form),
        Mount("/_system/static", app=static_files()),
    ]
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
