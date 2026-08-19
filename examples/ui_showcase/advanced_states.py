"""Deterministic UI-06B/D browser-acceptance fixtures for the showcase app."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, Field
from rakit import (
    ActionDefinition,
    ActionIntent,
    ActionPresentation,
    ActionScope,
    Admin,
    Autocomplete,
    DataSourceCapabilities,
    FileUpload,
    LauncherItem,
    MultiAutocomplete,
    PageDefinition,
    PageResult,
    PageWebPresentation,
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipKind,
    ResourceAdmin,
)
from rakit_core.actions import ActionSuccess
from rakit_core.di import ServiceScope
from rakit_core.fields import FieldDefinition, FileField
from rakit_core.forms import FieldLayout, FormLayout, FormSchema, RelationshipPanel
from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import MutationAuthorization, MutationOperation, OperationAuthorizationSet
from rakit_core.operations import OperationContext
from rakit_core.pages import DomainPageHandler, PageContext, PageRedirect, PageRejected
from rakit_core.pagination import PagePagination
from rakit_core.pagination import PageResult as ResourcePage
from rakit_core.permissions import PermissionRequirement
from rakit_core.query import ResourceQuery
from rakit_core.relationship_mutations import RelationshipCandidate, RelationshipEditorRow
from rakit_core.relationships import (
    CompiledRelationship,
    RelationshipDestructivePolicy,
    RelationshipEditMode,
    RelationshipOrderingDefinition,
)
from rakit_core.resources import ResourceService
from rakit_core.transactions import TransactionPolicy
from rakit_storage import FileAccess, FileStorage, StoredFile, TemporaryUpload
from rakit_web.form_routes import WriteResourceBinding
from rakit_web.relationship_routes import RelationshipEditorBinding, RelationshipFormBinding
from rakit_web.resource_routes import build_templates
from starlette.requests import Request


class _ShowcaseIdempotencyStore:
    """Development-only store used by explicit write fixtures."""

    production_safe = False

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


class _ShowcaseDataSource:
    capabilities = DataSourceCapabilities(read=True)

    def __init__(self, rows: tuple[Mapping[str, object], ...], fields: tuple[str, ...]) -> None:
        self.rows: tuple[dict[str, object], ...] = tuple(dict(row) for row in rows)
        self.fields = fields
        self.identity_fields = ("id",)

    def identity_for(self, record: Mapping[str, object]) -> RecordIdentity:
        value = record["id"]
        if not isinstance(value, str | int | UUID) or isinstance(value, bool):
            raise TypeError("showcase record id must be an identity scalar")
        return RecordIdentity(values={"id": value})

    async def list(self, query: ResourceQuery) -> ResourcePage[dict[str, object]]:
        rows = self.rows
        if query.search:
            needle = query.search.casefold()
            rows = tuple(
                row
                for row in rows
                if any(needle in str(value).casefold() for value in row.values())
            )
        pagination = query.pagination
        if not isinstance(pagination, PagePagination):
            raise ValueError("UI showcase sources support page pagination only")
        start = pagination.offset
        items = rows[start : start + pagination.per_page]
        return ResourcePage(
            items=items,
            page=pagination.page,
            per_page=pagination.per_page,
            has_previous=pagination.page > 1,
            has_next=start + len(items) < len(rows),
            total_count=len(rows),
        )

    async def count(self, query: ResourceQuery) -> int:
        return len((await self.list(query)).items)

    async def detail(self, identity: RecordIdentity) -> dict[str, object] | None:
        wanted = str(identity.values["id"])
        return next((row for row in self.rows if str(row["id"]) == wanted), None)

    def validate_relationship(
        self,
        definition: RelationshipDefinition,
        target_data_source: object,
        association_target_data_source: object | None,
    ) -> None:
        del definition, target_data_source, association_target_data_source


PEOPLE = tuple(
    {"id": index, "name": f"Person {index:02d}", "team": "Operations" if index % 2 else "Support"}
    for index in range(1, 36)
)
RELATIONSHIP_RECORDS = (
    {"id": 1, "title": "Selected relationship state", "status": "Draft"},
    {"id": 2, "title": "Empty to-one relationship state", "status": "Draft"},
)

PEOPLE_SOURCE = _ShowcaseDataSource(PEOPLE, ("id", "name", "team"))
RELATIONSHIP_SOURCE = _ShowcaseDataSource(RELATIONSHIP_RECORDS, ("id", "title", "status"))


_CUSTOMER = RelationshipDefinition(
    relationship_id="customer",
    target_resource_id="acceptance_people",
    label="Customer",
    kind=RelationshipKind.MANY_TO_ONE,
    cardinality=RelationshipCardinality.TO_ONE,
    nullable=True,
    writable=True,
    edit_mode=RelationshipEditMode.LINK,
    record_label_field="name",
    presentation=Autocomplete(
        search_fields=("name",),
        display_fields=("name", "team"),
        placeholder="Search customer...",
        min_query_length=1,
        page_size=12,
    ),
)
_TAGS = RelationshipDefinition(
    relationship_id="tags",
    target_resource_id="acceptance_people",
    label="Compact team links",
    kind=RelationshipKind.MANY_TO_MANY,
    cardinality=RelationshipCardinality.TO_MANY,
    writable=True,
    edit_mode=RelationshipEditMode.LINK,
    record_label_field="name",
    presentation=MultiAutocomplete(
        search_fields=("name",),
        display_fields=("name", "team"),
        placeholder="Add team links...",
        min_query_length=1,
        page_size=12,
    ),
)
_PARTICIPANTS = RelationshipDefinition(
    relationship_id="participants",
    target_resource_id="acceptance_people",
    label="Paginated participants",
    kind=RelationshipKind.MANY_TO_MANY,
    cardinality=RelationshipCardinality.TO_MANY,
    writable=True,
    edit_mode=RelationshipEditMode.LINK,
    record_label_field="name",
    presentation=MultiAutocomplete(
        search_fields=("name",),
        display_fields=("name", "team"),
        placeholder="Add participants...",
        min_query_length=1,
        page_size=10,
    ),
)
_LINE_ITEMS = RelationshipDefinition(
    relationship_id="line_items",
    target_resource_id="acceptance_people",
    label="Inline ordered rows",
    kind=RelationshipKind.ONE_TO_MANY,
    cardinality=RelationshipCardinality.TO_MANY,
    writable=True,
    edit_mode=RelationshipEditMode.INLINE,
    ordered=True,
    ordering=RelationshipOrderingDefinition(position_field="position"),
    record_label_field="name",
)
_LARGE_ORDER = RelationshipDefinition(
    relationship_id="large_order",
    target_resource_id="acceptance_people",
    label="Reorder unavailable rows",
    kind=RelationshipKind.ONE_TO_MANY,
    cardinality=RelationshipCardinality.TO_MANY,
    writable=True,
    edit_mode=RelationshipEditMode.INLINE,
    ordered=True,
    ordering=RelationshipOrderingDefinition(position_field="position"),
    record_label_field="name",
)
_READ_ONLY = RelationshipDefinition(
    relationship_id="read_only_team",
    target_resource_id="acceptance_people",
    label="Read-only team",
    kind=RelationshipKind.MANY_TO_MANY,
    cardinality=RelationshipCardinality.TO_MANY,
    writable=False,
    edit_mode=RelationshipEditMode.READ_ONLY,
    record_label_field="name",
)
_UNLINK_ONLY = RelationshipDefinition(
    relationship_id="unlink_only",
    target_resource_id="acceptance_people",
    label="Unlink-only members",
    kind=RelationshipKind.MANY_TO_MANY,
    cardinality=RelationshipCardinality.TO_MANY,
    writable=True,
    edit_mode=RelationshipEditMode.LINK,
    destructive_policy=RelationshipDestructivePolicy(),
    record_label_field="name",
)
RELATIONSHIPS = (
    _CUSTOMER,
    _TAGS,
    _PARTICIPANTS,
    _LINE_ITEMS,
    _LARGE_ORDER,
    _READ_ONLY,
    _UNLINK_ONLY,
)


class AcceptancePeopleAdmin(ResourceAdmin):
    resource_id = "acceptance_people"
    path = "/acceptance-people"
    label = "Acceptance people"
    singular_label = "Acceptance person"
    data_source = PEOPLE_SOURCE
    list_fields = ("id", "name", "team")
    detail_fields = ("id", "name", "team")
    search_fields = ("name",)
    sort_fields = ("id", "name")


class RelationshipStatesAdmin(ResourceAdmin):
    resource_id = "relationship_states"
    path = "/relationship-states"
    label = "Relationship states"
    singular_label = "Relationship state"
    data_source = RELATIONSHIP_SOURCE
    list_fields = ("id", "title", "status")
    detail_fields = ("id", "title", "status")
    sort_fields = ("id", "title")
    relationships = RELATIONSHIPS


@dataclass
class _RelationshipStateProvider:
    per_page: int = 25

    def _identities(self, relationship_id: str, parent_id: int) -> tuple[int, ...]:
        if relationship_id == "customer":
            return (1,) if parent_id == 1 else ()
        if relationship_id == "tags":
            return (1, 2, 3)
        if relationship_id == "participants":
            return tuple(range(1, 31))
        if relationship_id == "line_items":
            return (4, 5)
        if relationship_id == "large_order":
            return (6, 7, 8, 9)
        if relationship_id == "read_only_team":
            return (10, 11)
        if relationship_id == "unlink_only":
            return (12, 13, 14)
        return ()

    async def editor_page(
        self,
        parent_identity: RecordIdentity,
        relationship_id: str,
        *,
        child_fields: tuple[str, ...] = (),
        page: int = 1,
        per_page: int = 25,
    ) -> ResourcePage[RelationshipEditorRow]:
        parent_id = int(parent_identity.values["id"])
        identities = self._identities(relationship_id, parent_id)
        start = (page - 1) * per_page
        selected = identities[start : start + per_page]
        rows = tuple(
            RelationshipEditorRow(
                candidate=RelationshipCandidate(
                    identity=RecordIdentity(values={"id": identity}),
                    label=f"Person {identity:02d}",
                ),
                values={field: f"{field}-{identity}" for field in child_fields},
                concurrency_token=f"relationship-child-{relationship_id}-{identity}",
            )
            for identity in selected
        )
        return ResourcePage(
            items=rows,
            page=page,
            per_page=per_page,
            has_previous=page > 1,
            has_next=start + len(rows) < len(identities),
            total_count=len(identities),
        )

    async def issue_concurrency_token(
        self, parent_identity: RecordIdentity, relationship_id: str
    ) -> str:
        return f"relationship-{parent_identity.values['id']}-{relationship_id}"

    async def reorder_identities(
        self,
        parent_identity: RecordIdentity,
        relationship_id: str,
        *,
        maximum: int,
    ) -> tuple[RecordIdentity, ...] | None:
        identities = self._identities(relationship_id, int(parent_identity.values["id"]))
        if len(identities) > maximum:
            return None
        return tuple(RecordIdentity(values={"id": identity}) for identity in identities)


class _RelationshipMutationService:
    def __init__(self) -> None:
        self._records: dict[int, dict[str, object]] = {
            int(row["id"]): {key: value for key, value in row.items()}
            for row in RELATIONSHIP_RECORDS
        }

    async def get(self, identity: RecordIdentity) -> dict[str, object] | None:
        return self._records.get(int(identity.values["id"]))

    def issue_update_token(self, record: object) -> str:
        del record
        return "relationship-parent-token"

    async def create(self, submitted: object, *, authorization: object | None = None) -> object:
        del authorization
        return submitted

    async def update(
        self,
        identity: RecordIdentity,
        submitted: object,
        *,
        concurrency_token: str | None,
        authorization: object | None = None,
    ) -> object:
        del concurrency_token, authorization
        return {"id": identity.values["id"], "submitted": submitted}

    async def create_graph(self, submitted: object, **kwargs: object) -> object:
        del kwargs
        return submitted

    async def update_graph(
        self, identity: RecordIdentity, submitted: object, **kwargs: object
    ) -> object:
        del kwargs
        return {"id": identity.values["id"], "submitted": submitted}

    async def issue_delete_token(self, identity: RecordIdentity) -> str:
        return f"delete-{identity.values['id']}"

    async def delete(
        self,
        confirmation_token: str,
        *,
        identity: RecordIdentity,
        authorization: object | None = None,
    ) -> None:
        del confirmation_token, identity, authorization

    def bind_delete_nonce_store(self, store: object) -> None:
        del store


class _MemoryFileStorage:
    storage_id = "showcase-documents"
    production_safe = False

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self._counter = 0

    async def save(
        self,
        upload: TemporaryUpload,
        *,
        prefix: str | None = None,
        max_size: int | None = None,
        operation_context: OperationContext | None = None,
    ) -> StoredFile:
        del operation_context
        chunks: list[bytes] = []
        async for chunk in upload.stream():
            chunks.append(chunk)
        payload = b"".join(chunks)
        if max_size is not None and len(payload) > max_size:
            raise ValueError("showcase upload exceeds max_size")
        self._counter += 1
        base = f"upload-{self._counter}.pdf"
        key = f"{prefix}/{base}" if prefix else f"showcase/private/{base}"
        self.objects[key] = payload
        return StoredFile(
            storage_id=self.storage_id,
            key=key,
            original_name=upload.original_name,
            content_type=upload.content_type,
            size=len(payload),
            checksum=f"sha256:{hashlib.sha256(payload).hexdigest()}",
        )

    def open(
        self,
        file: StoredFile,
        *,
        operation_context: OperationContext | None = None,
    ) -> AsyncIterator[bytes]:
        del operation_context

        async def stream() -> AsyncIterator[bytes]:
            yield self.objects[file.key]

        return stream()

    async def delete(
        self,
        file: StoredFile,
        *,
        operation_context: OperationContext | None = None,
    ) -> None:
        del operation_context
        self.objects.pop(file.key, None)

    async def resolve_access(
        self,
        file: StoredFile,
        *,
        operation_context: OperationContext | None = None,
    ) -> FileAccess:
        del file, operation_context
        return FileAccess(public=False)


FILE_STORAGE = _MemoryFileStorage()
_SEEDED_PDF = b"%PDF-1.4\n% Rakit UI-06B deterministic showcase\n"
_SEEDED_FILE = StoredFile(
    storage_id="showcase-documents",
    key="showcase/private/current-contract.pdf",
    original_name="current-contract.pdf",
    content_type="application/pdf",
    size=len(_SEEDED_PDF),
    checksum=f"sha256:{hashlib.sha256(_SEEDED_PDF).hexdigest()}",
)
FILE_STORAGE.objects[_SEEDED_FILE.key] = _SEEDED_PDF
DOCUMENT_ROWS = ({"id": 1, "attachment": _SEEDED_FILE.model_dump(mode="python")},)
DOCUMENT_SOURCE = _ShowcaseDataSource(DOCUMENT_ROWS, ("id", "attachment"))


class AcceptanceDocumentsAdmin(ResourceAdmin):
    resource_id = "acceptance_documents"
    path = "/acceptance-documents"
    label = "Upload states"
    singular_label = "Upload state"
    data_source = DOCUMENT_SOURCE
    list_fields = ("id",)
    detail_fields = ("id",)
    sort_fields = ("id",)


class _DocumentMutationService:
    def __init__(self) -> None:
        self._records = {1: dict(DOCUMENT_ROWS[0])}

    async def get(self, identity: RecordIdentity) -> dict[str, object] | None:
        return self._records.get(int(identity.values["id"]))

    def issue_update_token(self, record: object) -> str:
        del record
        return "document-update-token"

    async def create(self, submitted: object, *, authorization: object | None = None) -> object:
        del authorization
        return submitted

    async def update(
        self,
        identity: RecordIdentity,
        submitted: object,
        *,
        concurrency_token: str | None,
        authorization: object | None = None,
    ) -> object:
        del concurrency_token, authorization
        return {"id": identity.values["id"], "submitted": submitted}

    async def issue_delete_token(self, identity: RecordIdentity) -> str:
        return f"document-delete-{identity.values['id']}"

    async def delete(
        self,
        confirmation_token: str,
        *,
        identity: RecordIdentity,
        authorization: object | None = None,
    ) -> None:
        del confirmation_token, identity, authorization

    def bind_delete_nonce_store(self, store: object) -> None:
        del store


async def _allow(_request: object) -> bool:
    return True


async def _mutation_authorization(
    _request: object, operation: MutationOperation, identity: RecordIdentity | None
) -> MutationAuthorization:
    return MutationAuthorization(
        admin_id="ui_showcase",
        resource_id="relationship_states",
        operation=operation,
        principal_id="ui-showcase-operator",
        permissions=("admin.resources.relationship_states.update",),
        target_identity=identity,
    )


async def _graph_authorization(
    _request: object,
    root: MutationAuthorization,
    parent_identity: RecordIdentity | None,
    changes: object,
) -> OperationAuthorizationSet:
    del parent_identity, changes
    return OperationAuthorizationSet(root=root, capabilities=())


async def _editor_authorization(
    _request: Request,
    _relationship_id: str,
    _parent_identity: RecordIdentity | None,
    /,
) -> bool:
    return True


def _compiled(definition: RelationshipDefinition) -> CompiledRelationship:
    requirement = PermissionRequirement.all_of("admin.resources.relationship_states.update")
    return CompiledRelationship(
        source_resource_id="relationship_states",
        definition=definition,
        mutation_permission=requirement,
        target_delete_permission=None,
        route_path=f"/relationship-states/{{identity}}/_relationships/{definition.relationship_id}",
        ordering=definition.ordering,
    )


def _relationship_form() -> RelationshipFormBinding:
    provider = _RelationshipStateProvider()
    target_service = ResourceService(cast(Any, PEOPLE_SOURCE))
    editors: list[RelationshipEditorBinding] = []
    for definition in RELATIONSHIPS:
        inline = definition.edit_mode is RelationshipEditMode.INLINE
        safe_maximum = 2 if definition.relationship_id == "large_order" else 10
        editors.append(
            RelationshipEditorBinding(
                relationship=_compiled(definition),
                target_service=target_service,
                state_provider=provider,
                target_search_fields=("name",),
                target_form_schema=(
                    FormSchema(
                        fields=(
                            FieldDefinition(
                                field_id="note",
                                python_type=str,
                                label="Row note",
                                required=True,
                            ),
                        )
                    )
                    if inline
                    else None
                ),
                reorder_safe_maximum=safe_maximum,
            )
        )
    return RelationshipFormBinding(editors=tuple(editors))


class PageMutationInput(BaseModel):
    reason: str = Field(min_length=3, description="Use 'reject' to exercise business rejection.")


class _UnsupportedPayload:
    def __str__(self) -> str:
        raise AssertionError("default page renderer must not stringify unsupported payloads")

    def __repr__(self) -> str:
        raise AssertionError("default page renderer must not repr unsupported payloads")


def _scalar_page(_context: PageContext) -> PageResult[str]:
    return PageResult(payload="Safe scalar payload")


def _mapping_page(_context: PageContext) -> PageResult[dict[str, object]]:
    return PageResult(payload={"status": "Ready", "count": 3, "owner": "Operations"})


def _table_page(_context: PageContext) -> PageResult[list[dict[str, object]]]:
    return PageResult(
        payload=[
            {"name": "Alpha", "state": "Ready", "count": 2},
            {"name": "Beta", "state": "Review", "count": 4},
        ]
    )


def _empty_page(_context: PageContext) -> PageResult[None]:
    return PageResult(payload=None)


def _unsupported_page(_context: PageContext) -> PageResult[object]:
    return PageResult(payload=_UnsupportedPayload())


def _mutating_page(context: PageContext) -> PageRedirect | PageRejected:
    values = cast(PageMutationInput, context.values)
    if values.reason.strip().casefold() == "reject":
        return PageRejected(
            errors={"reason": "The deterministic business rule rejected this value."},
            message="Business rejection exercised without changing page transport.",
        )
    return PageRedirect(
        location="/acceptance-page-mapping",
        message="Mutating page completed through POST/Redirect/Get.",
    )


class _PageDangerAction:
    async def execute(self, _context: object) -> ActionSuccess[dict[str, object]]:
        return ActionSuccess(
            payload={"state": "reviewed"},
            message="Danger page action exercised in the showcase.",
        )


ADVANCED_LAUNCHERS = (
    LauncherItem(
        launcher_id="relationship_states",
        label="Relationship states",
        path="/relationship-states",
        description=(
            "Writable TO_ONE/TO_MANY, pagination, inline reorder, and unlink-only UI-06B states."
        ),
    ),
    LauncherItem(
        launcher_id="upload_states",
        label="Upload states",
        path="/acceptance-documents",
        description=(
            "Create and edit FileField flows with a real in-memory development storage descriptor."
        ),
    ),
    LauncherItem(
        launcher_id="page_payload_states",
        label="Page payload states",
        path="/acceptance-page-mapping",
        description="Safe default custom-page payload rendering and mutating feedback states.",
    ),
)


def configure_ui06_acceptance(admin: Admin) -> None:
    """Register explicit public runtime fixtures before the admin is compiled."""

    admin.register(AcceptancePeopleAdmin)
    admin.register(RelationshipStatesAdmin)
    admin.register(AcceptanceDocumentsAdmin)

    admin.builder.registry.add_value(
        FileStorage,
        FILE_STORAGE,
        scope=ServiceScope.APPLICATION,
        name="showcase-documents",
    )

    relationship_layout = FormLayout(
        children=(FieldLayout("status"),)
        + tuple(
            RelationshipPanel(
                layout_id=f"{definition.relationship_id}-panel",
                relationship_id=definition.relationship_id,
            )
            for definition in RELATIONSHIPS
        )
    )
    relationship_binding = WriteResourceBinding(
        path="/relationship-states",
        label="Relationship state",
        form_schema=FormSchema(
            fields=(
                FieldDefinition(
                    field_id="status",
                    python_type=str,
                    label="Parent status",
                    required=True,
                ),
            ),
            layout=relationship_layout,
            update_layout=relationship_layout,
        ),
        mutation_service=_RelationshipMutationService(),
        templates=build_templates(()),
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: "showcase-submission",
        mutation_authorizer=_mutation_authorization,
        graph_mutation_authorizer=_graph_authorization,
        relationship_editor_authorizer=_editor_authorization,
        relationship_form=_relationship_form(),
        idempotency_store=_ShowcaseIdempotencyStore(),
    )
    admin.register_write_resource("relationship_states", relationship_binding)

    file_binding = WriteResourceBinding(
        path="/acceptance-documents",
        label="Upload state",
        form_schema=FormSchema(
            fields=(
                FileField(
                    field_id="attachment",
                    storage_id="showcase-documents",
                    label="PDF attachment",
                    description=(
                        "Replace the current PDF or leave it empty to keep the existing file."
                    ),
                    required=True,
                    max_size=10 * 1024 * 1024,
                    allowed_extensions=(".pdf",),
                    allowed_mime_types=("application/pdf",),
                    presentation=FileUpload(drag_drop=True, preview=True),
                ),
            )
        ),
        mutation_service=_DocumentMutationService(),
        templates=build_templates(()),
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: "showcase-submission",
        mutation_authorizer=_mutation_authorization,
        idempotency_store=_ShowcaseIdempotencyStore(),
    )
    admin.register_write_resource("acceptance_documents", file_binding)

    pages = (
        PageDefinition(
            page_id="acceptance_page_scalar",
            path="/acceptance-page-scalar",
            label="Scalar payload",
            handler=DomainPageHandler(_scalar_page),
        ),
        PageDefinition(
            page_id="acceptance_page_mapping",
            path="/acceptance-page-mapping",
            label="Mapping payload",
            handler=DomainPageHandler(_mapping_page),
        ),
        PageDefinition(
            page_id="acceptance_page_table",
            path="/acceptance-page-table",
            label="Table payload",
            handler=DomainPageHandler(_table_page),
        ),
        PageDefinition(
            page_id="acceptance_page_empty",
            path="/acceptance-page-empty",
            label="Empty payload",
            handler=DomainPageHandler(_empty_page),
        ),
        PageDefinition(
            page_id="acceptance_page_unsupported",
            path="/acceptance-page-unsupported",
            label="Unsupported payload",
            handler=DomainPageHandler(_unsupported_page),
        ),
    )
    for page in pages:
        admin.register_page(page)

    admin.register_page(
        PageDefinition(
            page_id="acceptance_page_mutation",
            path="/acceptance-page-mutation",
            label="Mutating page feedback",
            input_schema=PageMutationInput,
            handler=DomainPageHandler(_mutating_page),
            mutating=True,
            transaction_policy=TransactionPolicy.DISABLED,
        ),
        actions=(
            ActionDefinition(
                action_id="page_danger_review",
                label="Danger review action",
                scope=ActionScope.PAGE,
                page_id="acceptance_page_mutation",
                executor=_PageDangerAction(),
            ),
        ),
        web=PageWebPresentation(
            actions={
                "page_danger_review": ActionPresentation(intent=ActionIntent.DANGER),
            }
        ),
    )
