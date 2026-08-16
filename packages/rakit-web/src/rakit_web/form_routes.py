"""Secure, explicit resource write routes.

The binding deliberately receives a compiled ``FormSchema`` and a narrow
mutation service rather than an ORM model.  HTTP concerns (CSRF, identity
decoding, duplicate form fields, redirects) stay here; writable-field and
optimistic-write invariants remain in the datasource service.
"""

import hashlib
import json
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import Protocol, cast
from urllib.parse import quote

from rakit_core.di import ServiceResolver
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.events import EventPublisher
from rakit_core.fields import FileField
from rakit_core.forms import (
    CollapsibleGroup,
    Column,
    CustomBlock,
    FieldLayout,
    FormIssue,
    FormLayout,
    FormSchema,
    FormValidationError,
    RelationshipPanel,
    Row,
    Section,
    Tab,
    Tabs,
)
from rakit_core.idempotency import (
    IdempotencyReservation,
    IdempotencyStatus,
    IdempotencyStore,
    OperationReceipt,
)
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.mutations import MutationAuthorization, MutationOperation, OperationAuthorizationSet
from rakit_core.operations import (
    CancellationContext,
    Deadline,
    OperationContext,
    activate_operation_context,
    new_operation_id,
    run_with_deadline,
)
from rakit_storage import FileStorage
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from ._paths import mounted_path
from .file_uploads import (
    FilePreparation,
    canonical_submission_values,
    cleanup_deleted_record_files,
    cleanup_replaced_uploads,
    compensate_uploads,
    file_accept,
    file_fields,
    has_file_fields,
    prepare_file_submission,
    record_stored_file,
    submission_for_display,
)
from .relationship_routes import (
    RelationshipFormBinding,
    build_relationship_changes,
    render_relationship_panels,
    split_relationship_submission,
)
from .results import mutation_success
from .security.cookies import CSRF_COOKIE_NAME


class CreateMutationService(Protocol):
    async def create(
        self,
        submitted: Mapping[str, object],
        *,
        authorization: MutationAuthorization | None = None,
    ) -> object: ...


class WriteMutationService(CreateMutationService, Protocol):
    async def get(self, identity: RecordIdentity) -> object | None: ...

    def issue_update_token(self, record: object) -> str: ...

    async def update(
        self,
        identity: RecordIdentity,
        submitted: Mapping[str, object],
        *,
        concurrency_token: str | None,
        authorization: MutationAuthorization | None = None,
    ) -> object: ...

    async def issue_delete_token(self, identity: RecordIdentity) -> str: ...

    async def delete(
        self,
        confirmation_token: str,
        *,
        identity: RecordIdentity,
        authorization: MutationAuthorization | None = None,
    ) -> None: ...


class GraphMutationService(WriteMutationService, Protocol):
    async def create_graph(
        self,
        submitted: Mapping[str, object],
        *,
        relationship_changes: tuple[object, ...],
        authorizations: OperationAuthorizationSet,
        idempotency_token: str | None = None,
    ) -> object: ...

    async def update_graph(
        self,
        identity: RecordIdentity,
        submitted: Mapping[str, object],
        *,
        relationship_changes: tuple[object, ...],
        authorizations: OperationAuthorizationSet,
        concurrency_token: str | None = None,
        idempotency_token: str | None = None,
    ) -> object: ...


Verifier = Callable[[Request], Awaitable[bool]]
SubmissionTokenIssuer = Callable[[Request], str]
MutationAuthorizer = Callable[
    [Request, MutationOperation, RecordIdentity | None], Awaitable[MutationAuthorization | None]
]
GraphMutationAuthorizer = Callable[
    [Request, MutationAuthorization, RecordIdentity | None, tuple[object, ...]],
    Awaitable[OperationAuthorizationSet | None],
]
RelationshipEditorAuthorizer = Callable[[Request, str, RecordIdentity | None], Awaitable[bool]]
OperationScopeFactory = Callable[[], AbstractAsyncContextManager[ServiceResolver]]


def _relationship_panel_ids(layout: FormLayout) -> set[str]:
    def walk(node: object) -> set[str]:
        if isinstance(node, RelationshipPanel):
            return {node.relationship_id}
        if isinstance(node, Tabs):
            return {relationship_id for tab in node.tabs for relationship_id in walk(tab)}
        if isinstance(node, Tab | Row | Column | Section | CollapsibleGroup):
            return {relationship_id for child in node.children for relationship_id in walk(child)}
        return set()

    return {relationship_id for child in layout.children for relationship_id in walk(child)}


@dataclass(frozen=True)
class WriteResourceBinding:
    path: str
    label: str
    form_schema: FormSchema
    mutation_service: CreateMutationService
    templates: Jinja2Templates
    authorize: Verifier
    verify_csrf: Verifier
    verify_submission_token: Verifier
    issue_submission_token: SubmissionTokenIssuer
    resource_id: str | None = None
    deadline_seconds: float | None = None
    idempotency_store: IdempotencyStore | None = None
    mutation_authorizer: MutationAuthorizer | None = None
    htmx_refresh_targets: tuple[str, ...] = ()
    success_message: str | None = None
    operation_scope: OperationScopeFactory | None = None
    relationship_form: RelationshipFormBinding | None = None
    graph_mutation_authorizer: GraphMutationAuthorizer | None = None
    relationship_editor_authorizer: RelationshipEditorAuthorizer | None = None
    codec: IdentityCodec = field(default_factory=IdentityCodec)

    def __post_init__(self) -> None:
        editors = (
            {editor.relationship_id for editor in self.relationship_form.editors}
            if self.relationship_form is not None
            else set()
        )
        panels = _relationship_panel_ids(self.form_schema.resolved_layout(operation="create"))
        panels.update(_relationship_panel_ids(self.form_schema.resolved_layout(operation="update")))
        missing = panels - editors
        if missing:
            raise ValueError(
                "RelationshipPanel references an editor that is not bound: "
                + ", ".join(sorted(missing))
            )

    @property
    def _route_resource_id(self) -> str:
        return self.resource_id or self.path

    @property
    def create_path(self) -> str:
        return f"{self.path}/new"

    @property
    def update_path(self) -> str:
        return f"{self.path}/{{identity}}/edit"

    @property
    def delete_path(self) -> str:
        return f"{self.path}/{{identity}}/delete"


async def _parse_form(
    request: Request, binding: WriteResourceBinding
) -> tuple[dict[str, object], dict[str, str]] | None:
    file_ids = {field.field_id for field in file_fields(binding.form_schema)}
    try:
        form = await request.form(
            max_files=len(file_ids),
            max_fields=len(binding.form_schema.fields)
            + (1_000 if binding.relationship_form else 4),
        )
    except HTTPException:
        return None
    items = form.multi_items()
    names = [name for name, _ in items]
    if len(names) != len(set(names)):
        return None
    reserved = {"csrf_token", "submission_token", "concurrency_token", "delete_token"}
    values: dict[str, object] = {}
    tokens: dict[str, str] = {}
    for name, value in items:
        if name in reserved:
            if not isinstance(value, str):
                return None
            tokens[name] = value
            continue
        if isinstance(value, UploadFile):
            if name not in file_ids:
                return None
            values[name] = value
            continue
        if not isinstance(value, str):
            return None
        values[name] = value
    try:
        split_relationship_submission(binding.relationship_form, values)
    except ValueError:
        return None
    return values, tokens


def _record_values(binding: WriteResourceBinding, record: object) -> dict[str, object]:
    return {
        field.field_id: binding.form_schema.format_value(
            field.field_id, getattr(record, field.field_id, "")
        )
        for field in binding.form_schema.fields
        if field.writable and field.readable and not field.sensitive
    }


def _field_dom_id(binding: WriteResourceBinding, field_id: str) -> str:
    safe_resource = re.sub(r"[^a-zA-Z0-9_-]", "-", binding._route_resource_id)
    safe_field = re.sub(r"[^a-zA-Z0-9_-]", "-", field_id)
    return f"rakit-{safe_resource}-{safe_field}"


def _node_fields(node: object) -> tuple[str, ...]:
    if isinstance(node, FieldLayout):
        return (node.field_id,)
    if isinstance(node, Column | Section | CollapsibleGroup):
        return tuple(field_id for child in node.children for field_id in _node_fields(child))
    if isinstance(node, Row):
        return tuple(field_id for column in node.children for field_id in _node_fields(column))
    if isinstance(node, Tabs):
        return tuple(field_id for tab in node.tabs for field_id in _node_fields(tab))
    if isinstance(node, Tab):
        return tuple(field_id for child in node.children for field_id in _node_fields(child))
    return ()


def _layout_view(
    layout: FormLayout,
    controls: Mapping[str, Mapping[str, object]],
    issue_map: Mapping[str, tuple[object, ...]],
    relationship_panels: Mapping[str, Mapping[str, object]],
) -> tuple[tuple[dict[str, object], ...], str | None]:
    ordered_invalid = [
        field_id
        for child in layout.children
        for field_id in _node_fields(child)
        if field_id in issue_map and field_id in controls
    ]
    first_invalid = ordered_invalid[0] if ordered_invalid else None

    def render(node: object) -> dict[str, object]:
        if isinstance(node, FieldLayout):
            return {"kind": "field", "field": controls.get(node.field_id)}
        if isinstance(node, RelationshipPanel):
            return {
                "kind": "relationship",
                "id": node.layout_id,
                "relationship": node.relationship_id,
                "panel": relationship_panels.get(node.relationship_id),
                "template": "relationships/panel.html",
            }
        if isinstance(node, CustomBlock):
            return {"kind": "custom", "id": node.layout_id, "block": node.block_id}
        if isinstance(node, Column):
            return {"kind": "column", "children": tuple(render(child) for child in node.children)}
        if isinstance(node, Row):
            return {"kind": "row", "children": tuple(render(child) for child in node.children)}
        if isinstance(node, Section):
            return {
                "kind": "section",
                "id": node.layout_id,
                "title": node.title,
                "children": tuple(render(child) for child in node.children),
            }
        if isinstance(node, CollapsibleGroup):
            fields = _node_fields(node)
            return {
                "kind": "collapsible",
                "id": node.layout_id,
                "label": node.label,
                "open": any(field_id in issue_map for field_id in fields),
                "children": tuple(render(child) for child in node.children),
            }
        if isinstance(node, Tabs):
            tabs = []
            for tab in node.tabs:
                fields = _node_fields(tab)
                count = len({field_id for field_id in fields if field_id in issue_map})
                tabs.append(
                    {
                        "id": tab.layout_id,
                        "label": tab.label,
                        "errors": count,
                        "active": first_invalid in fields if first_invalid else tab is node.tabs[0],
                        "children": tuple(render(child) for child in tab.children),
                    }
                )
            return {"kind": "tabs", "id": node.layout_id, "tabs": tuple(tabs)}
        raise TypeError("Unsupported form layout node")

    return tuple(render(child) for child in layout.children), first_invalid


async def _form_response(
    binding: WriteResourceBinding,
    request: Request,
    *,
    title: str,
    action_path: str,
    submitted: Mapping[str, object] | None = None,
    issues: tuple[object, ...] = (),
    concurrency_token: str | None = None,
    operation: str = "create",
    status_code: int = 200,
    parent_identity: RecordIdentity | None = None,
    relationship_issues: tuple[Mapping[str, object], ...] = (),
) -> Response:
    issue_map: dict[str, tuple[object, ...]] = {}
    for issue in issues:
        field_id = getattr(issue, "field_id", None)
        if isinstance(field_id, str):
            issue_map[field_id] = (*issue_map.get(field_id, ()), issue)
    controls = {
        field.field_id: {
            "id": _field_dom_id(binding, field.field_id),
            "name": field.field_id,
            "label": field.label or field.field_id,
            "description": field.description,
            "description_id": f"{_field_dom_id(binding, field.field_id)}-description",
            "error_id": f"{_field_dom_id(binding, field.field_id)}-error",
            "value": (submitted or {}).get(field.field_id, ""),
            "issues": issue_map.get(field.field_id, ()),
            "is_file": isinstance(field, FileField),
            "accept": file_accept(field) if isinstance(field, FileField) else "",
            "required": field.required,
        }
        for field in binding.form_schema.fields
        if field.writable and field.readable and not field.sensitive
    }
    relationship_panels = await render_relationship_panels(
        binding.relationship_form,
        parent_identity=parent_identity,
        submitted=submitted or {},
        issues=relationship_issues,
    )
    layout, first_invalid = _layout_view(
        binding.form_schema.resolved_layout(operation=operation),
        controls,
        issue_map,
        relationship_panels,
    )
    return binding.templates.TemplateResponse(
        request,
        "forms/form.html",
        {
            "title": title,
            "label": binding.label,
            "layout": layout,
            "issues": issues,
            "summary_issues": tuple(
                {
                    "message": getattr(issue, "message", "Invalid value."),
                    "field_id": getattr(issue, "field_id", None),
                    "label": (
                        controls[field_id]["label"]
                        if isinstance((field_id := getattr(issue, "field_id", None)), str)
                        and field_id in controls
                        else None
                    ),
                    "anchor": (
                        _field_dom_id(binding, field_id)
                        if isinstance(field_id, str) and field_id in controls
                        else None
                    ),
                }
                for issue in issues
            ),
            "global_issues": tuple(
                issue for issue in issues if getattr(issue, "field_id", None) is None
            ),
            "first_invalid_id": _field_dom_id(binding, first_invalid) if first_invalid else None,
            "action_url": mounted_path(request, action_path),
            "csrf_token": request.cookies.get(CSRF_COOKIE_NAME, ""),
            "submission_token": binding.issue_submission_token(request),
            "concurrency_token": concurrency_token,
            "has_file_fields": has_file_fields(binding.form_schema),
            "codec": binding.relationship_form.codec
            if binding.relationship_form
            else binding.codec,
        },
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def _relationship_error_issues(error: RakitError) -> tuple[Mapping[str, object], ...]:
    """Keep structured relationship errors out of the scalar/global form path."""

    details = error.details
    if not isinstance(details, Mapping):
        return ()
    issue = details.get("relationship_issue")
    if not isinstance(issue, Mapping):
        return ()
    relationship_id = issue.get("relationship_id")
    if not isinstance(relationship_id, str):
        return ()
    row_key = issue.get("row_key")
    kind = issue.get("kind")
    raw_issues = issue.get("issues")
    if isinstance(raw_issues, tuple):
        return tuple(
            {
                "relationship_id": relationship_id,
                "row_key": row_key,
                "field_id": raw.get("field_id") if isinstance(raw, Mapping) else None,
                "message": raw.get("message", error.message)
                if isinstance(raw, Mapping)
                else error.message,
                "kind": kind,
            }
            for raw in raw_issues
        )
    return (
        {
            "relationship_id": relationship_id,
            "row_key": row_key,
            "field_id": issue.get("field_id"),
            "message": issue.get("message", error.message),
            "kind": kind,
        },
    )


def _error(status_code: int, message: str) -> PlainTextResponse:
    return PlainTextResponse(
        message, status_code=status_code, headers={"Cache-Control": "no-store"}
    )


def _identity(binding: WriteResourceBinding, encoded: str) -> RecordIdentity | None:
    try:
        return binding.codec.decode(encoded)
    except ValueError:
        return None


def _write_routes_available(binding: WriteResourceBinding) -> bool:
    service = binding.mutation_service
    return all(
        callable(getattr(service, name, None))
        for name in ("get", "issue_update_token", "update", "issue_delete_token", "delete")
    )


async def _execute_with_deadline(
    binding: WriteResourceBinding,
    request: Request,
    awaitable: Awaitable[object],
    authorization: MutationAuthorization,
) -> object:
    if binding.deadline_seconds is None and binding.operation_scope is None:
        return await awaitable
    deadline = (
        Deadline.after(binding.deadline_seconds) if binding.deadline_seconds is not None else None
    )

    @asynccontextmanager
    async def scoped_services() -> AsyncIterator[ServiceResolver | None]:
        if binding.operation_scope is None:
            yield None
        else:
            async with binding.operation_scope() as services:
                yield services

    async with scoped_services() as services:
        context = OperationContext(
            deadline=deadline,
            cancellation=CancellationContext(),
            request_id=cast(str, request.scope.get("state", {}).get("request_id", "")),
            operation_id=new_operation_id(),
            principal=request.scope.get("state", {}).get("principal"),
            principal_id=authorization.principal_id,
            admin_id=authorization.admin_id,
            resource_id=authorization.resource_id,
            operation=authorization.operation,
            permissions=authorization.permissions,
            permission_requirement=authorization.requirement,
            services=services,
            events=services.require(EventPublisher) if services is not None else None,
        )
        with activate_operation_context(context):
            if deadline is None:
                return await awaitable
            return await run_with_deadline(awaitable, deadline)


async def _graph_authorizations(
    binding: WriteResourceBinding,
    request: Request,
    root: MutationAuthorization,
    parent_identity: RecordIdentity | None,
    changes: tuple[object, ...],
) -> OperationAuthorizationSet:
    if binding.graph_mutation_authorizer is None:
        raise RakitError(
            code=ErrorCode.AUTH_FORBIDDEN,
            message="Relationship graph mutation is not authorized.",
            status_code=403,
        )
    authorizations = await binding.graph_mutation_authorizer(
        request, root, parent_identity, changes
    )
    if authorizations is None or authorizations.root != root:
        raise RakitError(
            code=ErrorCode.AUTH_FORBIDDEN,
            message="Relationship graph mutation is not authorized.",
            status_code=403,
        )
    return authorizations


async def _claim_submission(
    binding: WriteResourceBinding,
    request: Request,
    *,
    submitted: Mapping[str, object],
    tokens: Mapping[str, str],
    operation: str,
    identity: RecordIdentity | None = None,
) -> tuple[IdempotencyReservation | None, Response | None]:
    """Atomically claim a verified submission token for one canonical operation."""
    if binding.idempotency_store is None:
        return None, None
    token = tokens.get("submission_token")
    if not token:
        return None, _error(409, "Invalid submission token")
    payload = {
        "operation": operation,
        "path": binding.path,
        "identity": dict(identity.values) if identity is not None else None,
        "values": dict(sorted(canonical_submission_values(submitted).items())),
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    reservation = await binding.idempotency_store.begin(
        hashlib.sha256(token.encode()).hexdigest(), fingerprint=fingerprint
    )
    if reservation.status is IdempotencyStatus.COMPLETED:
        return reservation, mutation_success(
            request,
            location=mounted_path(request, binding.path),
            refresh_targets=binding.htmx_refresh_targets,
            message=binding.success_message,
        )
    if not reservation.claimed:
        return reservation, _error(409, "Submission is already in progress")
    return reservation, None


async def _authorization(
    binding: WriteResourceBinding,
    request: Request,
    operation: MutationOperation,
    identity: RecordIdentity | None,
) -> MutationAuthorization | None:
    if binding.mutation_authorizer is None:
        return None
    return await binding.mutation_authorizer(request, operation, identity)


@asynccontextmanager
async def _file_services(binding: WriteResourceBinding) -> AsyncIterator[ServiceResolver]:
    if binding.operation_scope is None:
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message="File fields require an operation service scope.",
            status_code=500,
        )
    async with binding.operation_scope() as services:
        yield services


async def _prepare_bound_files(
    binding: WriteResourceBinding,
    submitted: Mapping[str, object],
    *,
    previous_record: object | None = None,
) -> FilePreparation:
    if not has_file_fields(binding.form_schema):
        return FilePreparation(values=dict(submitted), uploads=(), issues=())
    async with _file_services(binding) as services:
        return await prepare_file_submission(
            binding.form_schema,
            submitted,
            services=services,
            previous_record=previous_record,
        )


async def _compensate_bound_files(
    binding: WriteResourceBinding,
    preparation: FilePreparation,
) -> None:
    if not preparation.uploads:
        return
    async with _file_services(binding) as services:
        await compensate_uploads(preparation.uploads, services=services)


async def _cleanup_replaced_bound_files(
    binding: WriteResourceBinding,
    preparation: FilePreparation,
) -> None:
    if not preparation.uploads:
        return
    async with _file_services(binding) as services:
        await cleanup_replaced_uploads(preparation.uploads, services=services)


async def _cleanup_deleted_bound_files(
    binding: WriteResourceBinding,
    record: object,
) -> None:
    if not has_file_fields(binding.form_schema):
        return
    async with _file_services(binding) as services:
        await cleanup_deleted_record_files(binding.form_schema, record, services=services)


def build_write_routes(binding: WriteResourceBinding) -> list[Route]:
    async def create_get(request: Request) -> Response:
        if not await binding.authorize(request):
            return _error(403, "Forbidden")
        return await _form_response(
            binding, request, title=f"New {binding.label}", action_path=binding.create_path
        )

    async def create_post(request: Request) -> Response:
        if not await binding.authorize(request):
            return _error(403, "Forbidden")
        authorization = await _authorization(binding, request, "create", None)
        if authorization is None:
            return _error(403, "Forbidden")
        if not await binding.verify_csrf(request):
            return _error(403, "Invalid CSRF token")
        if not await binding.verify_submission_token(request):
            return _error(409, "Invalid submission token")
        parsed = await _parse_form(request, binding)
        if parsed is None:
            return _error(400, "Invalid form")
        submitted, tokens = parsed
        display_submitted = submission_for_display(submitted)
        preparation = FilePreparation(values=dict(submitted), uploads=(), issues=())
        reservation: IdempotencyReservation | None = None
        try:
            scalar_submitted, _ = split_relationship_submission(
                binding.relationship_form, submitted
            )
            preparation = await _prepare_bound_files(binding, scalar_submitted)
            if preparation.issues:
                await _compensate_bound_files(binding, preparation)
                return await _form_response(
                    binding,
                    request,
                    title=f"New {binding.label}",
                    action_path=binding.create_path,
                    submitted=display_submitted,
                    issues=preparation.issues,
                    status_code=422,
                )
            state = binding.form_schema.parse(preparation.values)
            normalized = dict(state.normalized)
            changes = (
                await build_relationship_changes(
                    binding.relationship_form, submitted, parent_identity=None
                )
                if binding.relationship_form is not None
                else ()
            )
            if binding.relationship_form is not None:
                graph_service = cast(GraphMutationService, binding.mutation_service)
                if not callable(getattr(graph_service, "create_graph", None)):
                    raise RakitError(
                        code=ErrorCode.CONFIG_INVALID,
                        message="Relationship forms require graph mutation support.",
                        status_code=500,
                    )
                graph_authorizations = await _graph_authorizations(
                    binding, request, authorization, None, changes
                )
                await _execute_with_deadline(
                    binding,
                    request,
                    graph_service.create_graph(
                        state,
                        relationship_changes=changes,
                        authorizations=graph_authorizations,
                        idempotency_token=tokens.get("submission_token"),
                    ),
                    authorization,
                )
            else:
                reservation, replay = await _claim_submission(
                    binding, request, submitted=normalized, tokens=tokens, operation="create"
                )
                if replay is not None:
                    await _compensate_bound_files(binding, preparation)
                    return replay
                await _execute_with_deadline(
                    binding,
                    request,
                    binding.mutation_service.create(state, authorization=authorization),
                    authorization,
                )
                if reservation is not None and binding.idempotency_store is not None:
                    await binding.idempotency_store.complete(
                        reservation,
                        OperationReceipt(
                            operation_id=str(uuid.uuid4()),
                            status="succeeded",
                            result_kind="redirect",
                            redirect_route=binding.path,
                        ),
                    )
        except FormValidationError as exc:
            await _compensate_bound_files(binding, preparation)
            return await _form_response(
                binding,
                request,
                title=f"New {binding.label}",
                action_path=binding.create_path,
                submitted=display_submitted,
                issues=exc.state.issues,
                status_code=422,
            )
        except RakitError as exc:
            await _compensate_bound_files(binding, preparation)
            if reservation is not None and binding.idempotency_store is not None:
                await binding.idempotency_store.release(reservation)
            if binding.relationship_form is not None:
                return await _form_response(
                    binding,
                    request,
                    title=f"New {binding.label}",
                    action_path=binding.create_path,
                    submitted=display_submitted,
                    issues=()
                    if _relationship_error_issues(exc)
                    else (FormIssue(None, exc.message),),
                    relationship_issues=_relationship_error_issues(exc),
                    status_code=exc.status_code,
                )
            return _error(exc.status_code, "Invalid form")
        except ValueError:
            await _compensate_bound_files(binding, preparation)
            if reservation is not None and binding.idempotency_store is not None:
                await binding.idempotency_store.release(reservation)
            return _error(400, "Invalid form")
        return mutation_success(
            request,
            location=mounted_path(request, binding.path),
            refresh_targets=binding.htmx_refresh_targets,
            message=binding.success_message,
        )

    routes = [
        Route(
            binding.create_path,
            create_get,
            methods=["GET"],
            name=f"resource:{binding._route_resource_id}:create",
        ),
        Route(
            binding.create_path,
            create_post,
            methods=["POST"],
            name=f"resource:{binding._route_resource_id}:create.submit",
        ),
    ]
    if not _write_routes_available(binding):
        return routes
    mutation_service = cast(WriteMutationService, binding.mutation_service)

    async def update_get(request: Request) -> Response:
        if not await binding.authorize(request):
            return _error(403, "Forbidden")
        identity = _identity(binding, request.path_params["identity"])
        if identity is None:
            return _error(400, "Invalid resource identity")
        record = await mutation_service.get(identity)
        if record is None:
            return _error(404, "Resource was not found")
        return await _form_response(
            binding,
            request,
            title=f"Edit {binding.label}",
            action_path=f"{binding.path}/{request.path_params['identity']}/edit",
            submitted=_record_values(binding, record),
            concurrency_token=mutation_service.issue_update_token(record),
            parent_identity=identity,
            operation="update",
        )

    async def update_post(request: Request) -> Response:
        if not await binding.authorize(request):
            return _error(403, "Forbidden")
        identity = _identity(binding, request.path_params["identity"])
        if identity is None:
            return _error(400, "Invalid resource identity")
        authorization = await _authorization(binding, request, "update", identity)
        if authorization is None:
            return _error(403, "Forbidden")
        if not await binding.verify_csrf(request):
            return _error(403, "Invalid CSRF token")
        if not await binding.verify_submission_token(request):
            return _error(409, "Invalid submission token")
        record = await mutation_service.get(identity)
        if record is None:
            return _error(404, "Resource was not found")
        parsed = await _parse_form(request, binding)
        if parsed is None:
            return _error(400, "Invalid form")
        submitted, tokens = parsed
        display_submitted = submission_for_display(submitted)
        preparation = FilePreparation(values=dict(submitted), uploads=(), issues=())
        reservation: IdempotencyReservation | None = None
        try:
            scalar_submitted, _ = split_relationship_submission(
                binding.relationship_form, submitted
            )
            preparation = await _prepare_bound_files(
                binding,
                scalar_submitted,
                previous_record=record,
            )
            if preparation.issues:
                await _compensate_bound_files(binding, preparation)
                return await _form_response(
                    binding,
                    request,
                    title=f"Edit {binding.label}",
                    action_path=f"{binding.path}/{request.path_params['identity']}/edit",
                    submitted=display_submitted,
                    issues=preparation.issues,
                    concurrency_token=tokens.get("concurrency_token"),
                    operation="update",
                    status_code=422,
                    parent_identity=identity,
                )
            state = binding.form_schema.parse(preparation.values)
            normalized = dict(state.normalized)
            changes = (
                await build_relationship_changes(
                    binding.relationship_form, submitted, parent_identity=identity
                )
                if binding.relationship_form is not None
                else ()
            )
            if binding.relationship_form is not None:
                graph_service = cast(GraphMutationService, mutation_service)
                if not callable(getattr(graph_service, "update_graph", None)):
                    raise RakitError(
                        code=ErrorCode.CONFIG_INVALID,
                        message="Relationship forms require graph mutation support.",
                        status_code=500,
                    )
                graph_authorizations = await _graph_authorizations(
                    binding, request, authorization, identity, changes
                )
                await _execute_with_deadline(
                    binding,
                    request,
                    graph_service.update_graph(
                        identity,
                        state,
                        relationship_changes=changes,
                        authorizations=graph_authorizations,
                        concurrency_token=tokens.get("concurrency_token"),
                        idempotency_token=tokens.get("submission_token"),
                    ),
                    authorization,
                )
            else:
                reservation, replay = await _claim_submission(
                    binding,
                    request,
                    submitted=normalized,
                    tokens=tokens,
                    operation="update",
                    identity=identity,
                )
                if replay is not None:
                    await _compensate_bound_files(binding, preparation)
                    return replay
                await _execute_with_deadline(
                    binding,
                    request,
                    mutation_service.update(
                        identity,
                        state,
                        concurrency_token=tokens.get("concurrency_token"),
                        authorization=authorization,
                    ),
                    authorization,
                )
                if reservation is not None and binding.idempotency_store is not None:
                    await binding.idempotency_store.complete(
                        reservation,
                        OperationReceipt(
                            operation_id=str(uuid.uuid4()),
                            status="succeeded",
                            result_kind="redirect",
                            redirect_route=binding.path,
                        ),
                    )
            await _cleanup_replaced_bound_files(binding, preparation)
        except FormValidationError as exc:
            await _compensate_bound_files(binding, preparation)
            return await _form_response(
                binding,
                request,
                title=f"Edit {binding.label}",
                action_path=f"{binding.path}/{request.path_params['identity']}/edit",
                submitted=display_submitted,
                issues=exc.state.issues,
                concurrency_token=tokens.get("concurrency_token"),
                operation="update",
                status_code=422,
                parent_identity=identity,
            )
        except RakitError as exc:
            await _compensate_bound_files(binding, preparation)
            if reservation is not None and binding.idempotency_store is not None:
                await binding.idempotency_store.release(reservation)
            if binding.relationship_form is not None:
                return await _form_response(
                    binding,
                    request,
                    title=f"Edit {binding.label}",
                    action_path=f"{binding.path}/{request.path_params['identity']}/edit",
                    submitted=display_submitted,
                    issues=()
                    if _relationship_error_issues(exc)
                    else (FormIssue(None, exc.message),),
                    relationship_issues=_relationship_error_issues(exc),
                    concurrency_token=tokens.get("concurrency_token"),
                    operation="update",
                    status_code=exc.status_code,
                    parent_identity=identity,
                )
            return _error(exc.status_code, "Mutation rejected")
        except ValueError:
            await _compensate_bound_files(binding, preparation)
            if reservation is not None and binding.idempotency_store is not None:
                await binding.idempotency_store.release(reservation)
            return _error(400, "Invalid form")
        return mutation_success(
            request,
            location=mounted_path(request, binding.path),
            refresh_targets=binding.htmx_refresh_targets,
            message=binding.success_message,
        )

    async def delete_get(request: Request) -> Response:
        if not await binding.authorize(request):
            return _error(403, "Forbidden")
        identity = _identity(binding, request.path_params["identity"])
        if identity is None:
            return _error(400, "Invalid resource identity")
        try:
            token = await mutation_service.issue_delete_token(identity)
        except RakitError as exc:
            return _error(exc.status_code, "Resource was not found")
        return binding.templates.TemplateResponse(
            request,
            "forms/delete_confirm.html",
            {
                "action_url": mounted_path(
                    request, f"{binding.path}/{request.path_params['identity']}/delete"
                ),
                "csrf_token": request.cookies.get(CSRF_COOKIE_NAME, ""),
                "delete_token": token,
                "submission_token": binding.issue_submission_token(request),
            },
            headers={"Cache-Control": "no-store"},
        )

    async def delete_post(request: Request) -> Response:
        if not await binding.authorize(request):
            return _error(403, "Forbidden")
        identity = _identity(binding, request.path_params["identity"])
        if identity is None:
            return _error(400, "Invalid resource identity")
        authorization = await _authorization(binding, request, "delete", identity)
        if authorization is None:
            return _error(403, "Forbidden")
        if not await binding.verify_csrf(request):
            return _error(403, "Invalid CSRF token")
        if not await binding.verify_submission_token(request):
            return _error(409, "Invalid submission token")
        parsed = await _parse_form(request, binding)
        if parsed is None:
            return _error(400, "Invalid form")
        submitted, tokens = parsed
        token = tokens.get("delete_token")
        if not token:
            return _error(400, "Invalid delete confirmation")
        record = await mutation_service.get(identity)
        if record is None:
            return _error(404, "Resource was not found")
        reservation: IdempotencyReservation | None = None
        try:
            reservation, replay = await _claim_submission(
                binding,
                request,
                submitted=submitted,
                tokens=tokens,
                operation="delete",
                identity=identity,
            )
            if replay is not None:
                return replay
            await _execute_with_deadline(
                binding,
                request,
                mutation_service.delete(token, identity=identity, authorization=authorization),
                authorization,
            )
            if reservation is not None and binding.idempotency_store is not None:
                await binding.idempotency_store.complete(
                    reservation,
                    OperationReceipt(
                        operation_id=str(uuid.uuid4()),
                        status="succeeded",
                        result_kind="redirect",
                        redirect_route=binding.path,
                    ),
                )
            await _cleanup_deleted_bound_files(binding, record)
        except RakitError as exc:
            if reservation is not None and binding.idempotency_store is not None:
                await binding.idempotency_store.release(reservation)
            return _error(exc.status_code, "Delete rejected")
        except ValueError:
            if reservation is not None and binding.idempotency_store is not None:
                await binding.idempotency_store.release(reservation)
            return _error(400, "Delete rejected")
        return mutation_success(
            request,
            location=mounted_path(request, binding.path),
            refresh_targets=binding.htmx_refresh_targets,
            message=binding.success_message,
        )

    async def download_file(request: Request) -> Response:
        if not await binding.authorize(request):
            return _error(403, "Forbidden")
        identity = _identity(binding, request.path_params["identity"])
        if identity is None:
            return _error(400, "Invalid resource identity")
        field_id = request.path_params["field_id"]
        field = next(
            (
                candidate
                for candidate in file_fields(binding.form_schema)
                if candidate.field_id == field_id and candidate.readable and not candidate.sensitive
            ),
            None,
        )
        if field is None:
            return _error(404, "File was not found")
        record = await mutation_service.get(identity)
        if record is None:
            return _error(404, "Resource was not found")
        stored = record_stored_file(record, field)
        if stored is None:
            return _error(404, "File was not found")
        if stored.storage_id != field.storage_id:
            return _error(404, "File was not found")

        async def stream() -> AsyncIterator[bytes]:
            async with _file_services(binding) as services:
                storage = services.require(FileStorage, name=stored.storage_id)
                await storage.resolve_access(stored)
                async for chunk in storage.open(stored):
                    yield chunk

        filename = quote(stored.original_name, safe="")
        return StreamingResponse(
            stream(),
            media_type=stored.content_type,
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
                "Content-Length": str(stored.size),
                "X-Content-Type-Options": "nosniff",
            },
        )

    routes.extend(
        (
            Route(
                binding.update_path,
                update_get,
                methods=["GET"],
                name=f"resource:{binding._route_resource_id}:edit",
            ),
            Route(
                binding.update_path,
                update_post,
                methods=["POST"],
                name=f"resource:{binding._route_resource_id}:edit.submit",
            ),
            Route(
                binding.delete_path,
                delete_get,
                methods=["GET"],
                name=f"resource:{binding._route_resource_id}:delete",
            ),
            Route(
                binding.delete_path,
                delete_post,
                methods=["POST"],
                name=f"resource:{binding._route_resource_id}:delete.submit",
            ),
            Route(
                f"{binding.path}/{{identity}}/_files/{{field_id}}",
                download_file,
                methods=["GET"],
                name=f"resource:{binding._route_resource_id}:file.download",
            ),
        )
    )
    return routes
