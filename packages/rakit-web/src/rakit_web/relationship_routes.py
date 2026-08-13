"""Thin form-state routes and parsers for compiled relationship editors.

Relationship writes never happen here.  This module converts normal form
controls into the sealed typed graph steps and offers read-only HTMX helpers
for scoped candidates and relationship panels.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, cast
from uuid import uuid4

from rakit_core.errors import ErrorCode, RakitError
from rakit_core.forms import FormSchema, FormValidationError
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.query import ResourceQuery
from rakit_core.relationship_mutations import (
    ClearRelated,
    CreateRelated,
    DeleteRelated,
    LinkRelated,
    RelationshipCandidate,
    RelationshipChangePlan,
    RelationshipEditorRow,
    ReorderRelated,
    SetRelated,
    UnlinkRelated,
    UpdateAssociationRelated,
    UpdateRelated,
)
from rakit_core.relationships import (
    CompiledRelationship,
    RelationshipCardinality,
    RelationshipEditMode,
    RelationshipKind,
    resolve_record_label,
)
from rakit_core.resources import ResourceService
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route

_PREFIX = "__rakit_rel__"
_MAX_FRAGMENT_FIELDS = 1_000


class RelationshipEditorStateProvider(Protocol):
    async def editor_rows(
        self,
        parent_identity: RecordIdentity,
        relationship_id: str,
        *,
        child_fields: tuple[str, ...] = (),
    ) -> tuple[RelationshipEditorRow, ...]: ...

    async def issue_concurrency_token(
        self, parent_identity: RecordIdentity, relationship_id: str
    ) -> str: ...


@dataclass(frozen=True)
class RelationshipEditorBinding:
    """One explicitly configured editor surface for a compiled relationship."""

    relationship: CompiledRelationship
    target_service: ResourceService
    state_provider: RelationshipEditorStateProvider
    target_form_schema: FormSchema | None = None
    association_form_schema: FormSchema | None = None
    target_search_fields: tuple[str, ...] = ()
    candidate_page_size: int = 25

    def __post_init__(self) -> None:
        definition = self.relationship.definition
        if self.candidate_page_size < 1 or self.candidate_page_size > 200:
            raise ValueError("candidate_page_size must be between 1 and 200")
        if definition.kind is RelationshipKind.ASSOCIATION_OBJECT:
            if self.association_form_schema is not None:
                fields = {field.field_id for field in self.association_form_schema.fields}
                if fields != set(definition.association_fields):
                    raise ValueError(
                        "association form fields must exactly match compiled allow-list"
                    )
        elif self.association_form_schema is not None:
            raise ValueError("association form schema requires an association-object relationship")

    @property
    def relationship_id(self) -> str:
        return str(self.relationship.definition.relationship_id)

    @property
    def editable(self) -> bool:
        return self.relationship.definition.effective_writable


@dataclass(frozen=True)
class RelationshipFormBinding:
    """Optional relationship UI attached to one existing write form binding."""

    editors: tuple[RelationshipEditorBinding, ...]
    codec: IdentityCodec = field(default_factory=IdentityCodec)

    def __post_init__(self) -> None:
        ids = tuple(editor.relationship_id for editor in self.editors)
        if len(ids) != len(set(ids)):
            raise ValueError("relationship editor ids must be unique")

    def editor(self, relationship_id: str) -> RelationshipEditorBinding:
        for editor in self.editors:
            if editor.relationship_id == relationship_id:
                return editor
        raise ValueError("Unknown relationship editor")


def relationship_prefix(relationship_id: str) -> str:
    return f"{_PREFIX}{relationship_id}__"


def split_relationship_submission(
    binding: RelationshipFormBinding | None,
    submitted: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    """Classify the strict scalar and declared relationship namespaces."""

    scalar: dict[str, object] = {}
    relationship: dict[str, object] = {}
    for name, value in submitted.items():
        if not name.startswith(_PREFIX):
            scalar[name] = value
            continue
        if binding is None:
            raise ValueError("Unknown form field")
        body = name.removeprefix(_PREFIX)
        relationship_id, separator, remainder = body.partition("__")
        if not separator or not remainder:
            raise ValueError("Malformed relationship form field")
        binding.editor(relationship_id)
        relationship[name] = value
    return scalar, relationship


def _identity(codec: IdentityCodec, encoded: object) -> RecordIdentity:
    if not isinstance(encoded, str):
        raise ValueError("Malformed relationship identity")
    return codec.decode(encoded)


def _fields_for_prefix(values: Mapping[str, object], prefix: str) -> dict[str, object]:
    return {
        name.removeprefix(prefix): value
        for name, value in values.items()
        if name.startswith(prefix)
    }


def _invalid_relationship_field() -> RakitError:
    return RakitError(
        code=ErrorCode.VALIDATION_FAILED,
        message="Relationship form input is not valid for this editor.",
        status_code=422,
    )


def _validate_relationship_field_names(
    editor: RelationshipEditorBinding,
    values: Mapping[str, object],
) -> None:
    """Reject controls outside the editor's deliberately small form grammar."""

    definition = editor.relationship.definition
    target_fields = (
        {field.field_id for field in editor.target_form_schema.fields}
        if editor.target_form_schema is not None
        else set()
    )
    association_fields = (
        {field.field_id for field in editor.association_form_schema.fields}
        if editor.association_form_schema is not None
        else set()
    )
    for name in values:
        if name in {"concurrency", "destructive_confirmation", "search"}:
            continue
        if (
            definition.cardinality is RelationshipCardinality.TO_MANY
            and name == "selection_present"
        ):
            continue
        if definition.cardinality is RelationshipCardinality.TO_ONE and name in {"set", "clear"}:
            continue
        if (
            definition.cardinality is RelationshipCardinality.TO_MANY
            and name.startswith("target__")
            and name.removeprefix("target__")
        ):
            continue
        if name.startswith("create__"):
            parts = name.split("__", 2)
            if len(parts) == 3 and parts[2] in target_fields:
                continue
        if name.startswith("update__"):
            parts = name.split("__", 2)
            if len(parts) == 3 and parts[2] in target_fields:
                continue
        if name.startswith("update_token__") and name.removeprefix("update_token__"):
            continue
        if name.startswith("association__"):
            parts = name.split("__", 2)
            if len(parts) == 3 and parts[2] in association_fields:
                continue
        if name.startswith("delete__") and name.removeprefix("delete__"):
            continue
        if name.startswith("order__") and name.removeprefix("order__"):
            continue
        if name.startswith("move__"):
            parts = name.split("__", 2)
            if (
                editor.relationship.ordering is not None
                and len(parts) == 3
                and parts[2] in {"up", "down"}
            ):
                continue
        raise _invalid_relationship_field()


def _schema_values(schema: FormSchema, values: Mapping[str, object]) -> Mapping[str, Any]:
    try:
        return schema.parse(values).normalized
    except FormValidationError as exc:
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="Inline relationship fields are invalid.",
            status_code=422,
            details={"issues": tuple(issue.message for issue in exc.state.issues)},
        ) from exc


async def build_relationship_changes(
    binding: RelationshipFormBinding,
    submitted: Mapping[str, object],
    *,
    parent_identity: RecordIdentity | None,
) -> tuple[RelationshipChangePlan, ...]:
    """Revalidate submitted relationship form state into sealed graph plans."""

    _, relationship_values = split_relationship_submission(binding, submitted)
    changes: list[RelationshipChangePlan] = []
    for editor in binding.editors:
        definition = editor.relationship.definition
        prefix = relationship_prefix(editor.relationship_id)
        values = _fields_for_prefix(relationship_values, prefix)
        if not values:
            continue
        if not editor.editable:
            raise RakitError(
                code=ErrorCode.AUTH_FORBIDDEN,
                message="This relationship is not writable.",
                status_code=403,
            )
        _validate_relationship_field_names(editor, values)
        current_rows = (
            await editor.state_provider.editor_rows(
                parent_identity,
                editor.relationship_id,
                child_fields=(
                    tuple(
                        field.field_id
                        for field in editor.target_form_schema.fields
                        if field.writable and field.readable and not field.sensitive
                    )
                    if editor.target_form_schema is not None
                    else ()
                ),
            )
            if parent_identity is not None
            else ()
        )
        current = {binding.codec.encode(row.candidate.identity): row for row in current_rows}
        steps: list[object] = []
        selected: dict[str, RecordIdentity] = {}
        for name, value in values.items():
            if name.startswith("target__"):
                selected[name.removeprefix("target__")] = _identity(binding.codec, value)

        if definition.cardinality is RelationshipCardinality.TO_ONE:
            if "clear" in values:
                if not definition.nullable:
                    raise RakitError(
                        code=ErrorCode.VALIDATION_FAILED,
                        message="A required relationship cannot be cleared.",
                        status_code=422,
                    )
                steps.append(ClearRelated())
            elif "set" in values and values["set"] not in {"", None}:
                steps.append(SetRelated(identity=_identity(binding.codec, values["set"])))
        else:
            for encoded, identity in selected.items():
                if encoded not in current:
                    steps.append(LinkRelated(identity=identity))
            for encoded, row in current.items():
                if encoded not in selected:
                    steps.append(UnlinkRelated(identity=row.candidate.identity))

        if editor.target_form_schema is not None:
            row_keys = {
                parts[1]
                for name in values
                if name.startswith("create__")
                for parts in (name.split("__", 2),)
                if len(parts) == 3
            }
            for row_key in row_keys:
                if not row_key.startswith("new-") or not row_key[4:].replace("-", "").isalnum():
                    raise ValueError("Malformed inline row key")
                row_values = _fields_for_prefix(values, f"create__{row_key}__")
                if any(value not in {"", None} for value in row_values.values()):
                    steps.append(
                        CreateRelated(values=_schema_values(editor.target_form_schema, row_values))
                    )
            for encoded, row in current.items():
                row_values = _fields_for_prefix(values, f"update__{encoded}__")
                if row_values and encoded in selected:
                    token = values.get(f"update_token__{encoded}")
                    steps.append(
                        UpdateRelated(
                            identity=row.candidate.identity,
                            values=_schema_values(editor.target_form_schema, row_values),
                            concurrency_token=token if isinstance(token, str) else None,
                        )
                    )

        if editor.association_form_schema is not None:
            for encoded, row in current.items():
                association_values = _fields_for_prefix(values, f"association__{encoded}__")
                if association_values:
                    steps.append(
                        UpdateAssociationRelated(
                            target_identity=row.candidate.identity,
                            association_identity=row.association_identity,
                            values=_schema_values(
                                editor.association_form_schema, association_values
                            ),
                        )
                    )

        for encoded, row in current.items():
            confirmation = values.get(f"delete__{encoded}")
            if confirmation:
                if not isinstance(confirmation, str):
                    raise ValueError("Malformed child delete confirmation")
                steps.append(
                    DeleteRelated(identity=row.candidate.identity, confirmation_token=confirmation)
                )

        order_values: list[str] = []
        for _, value in sorted(
            (name, value) for name, value in values.items() if name.startswith("order__")
        ):
            if not isinstance(value, str):
                raise _invalid_relationship_field()
            order_values.append(value)
        moves = [
            (name.split("__", 2), value)
            for name, value in values.items()
            if name.startswith("move__")
        ]
        if moves and not order_values:
            order_values = [binding.codec.encode(row.candidate.identity) for row in current_rows]
        for parts, value in moves:
            if len(parts) != 3 or not isinstance(value, str):
                raise _invalid_relationship_field()
            encoded, direction = parts[1:]
            try:
                index = order_values.index(encoded)
            except ValueError as exc:
                raise _invalid_relationship_field() from exc
            offset = -1 if direction == "up" else 1
            destination = index + offset
            if 0 <= destination < len(order_values):
                order_values[index], order_values[destination] = (
                    order_values[destination],
                    order_values[index],
                )
        if order_values:
            if editor.relationship.ordering is None:
                raise RakitError(
                    code=ErrorCode.VALIDATION_FAILED,
                    message="Relationship is not safely reorderable.",
                    status_code=422,
                )
            steps.append(
                ReorderRelated(
                    identities=tuple(_identity(binding.codec, value) for value in order_values)
                )
            )

        if not steps:
            continue
        concurrency_token = values.get("concurrency")
        destructive_confirmation = values.get("destructive_confirmation")
        changes.append(
            RelationshipChangePlan(
                operation_id=f"relationship:{editor.relationship_id}",
                relationship_id=editor.relationship_id,
                steps=tuple(cast(Any, steps)),
                authorization_requirement=editor.relationship.mutation_permission,
                concurrency_token=concurrency_token if isinstance(concurrency_token, str) else None,
                destructive_confirmation=(
                    destructive_confirmation if isinstance(destructive_confirmation, str) else None
                ),
            )
        )
    return tuple(changes)


async def _candidate_options(
    editor: RelationshipEditorBinding, *, query: str | None, page: int = 1
) -> tuple[RelationshipCandidate, ...]:
    source = editor.target_service.data_source
    identity_for = getattr(source, "identity_for", None)
    if not callable(identity_for):
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message="Relationship target data source cannot provide canonical identities.",
            status_code=500,
        )
    result = await editor.target_service.list(
        ResourceQuery.from_params(
            page=page,
            per_page=editor.candidate_page_size,
            allowed_sort_fields=(),
            identity_fields=source.identity_fields,
            search=query if editor.target_search_fields else None,
        )
    )
    return tuple(
        RelationshipCandidate(
            identity=identity_for(record),
            label=resolve_record_label(editor.relationship.definition, record),
        )
        for record in result.items
    )


async def relationship_panel_view(
    editor: RelationshipEditorBinding,
    *,
    parent_identity: RecordIdentity | None,
    submitted: Mapping[str, object] = {},
    page: int = 1,
) -> dict[str, object]:
    definition = editor.relationship.definition
    child_fields = (
        tuple(
            field.field_id
            for field in editor.target_form_schema.fields
            if field.writable and field.readable and not field.sensitive
        )
        if editor.target_form_schema is not None
        else ()
    )
    rows = (
        await editor.state_provider.editor_rows(
            parent_identity, editor.relationship_id, child_fields=child_fields
        )
        if parent_identity is not None and definition.readable
        else ()
    )
    prefix = relationship_prefix(editor.relationship_id)
    values = _fields_for_prefix(submitted, prefix)
    selected = {name.removeprefix("target__") for name in values if name.startswith("target__")}
    if not selected and "selection_present" not in values:
        selected = {IdentityCodec().encode(row.candidate.identity) for row in rows}
    row_views: list[dict[str, object]] = []
    for row in rows:
        encoded = IdentityCodec().encode(row.candidate.identity)
        value_prefix = (
            f"association__{encoded}__"
            if definition.kind is RelationshipKind.ASSOCIATION_OBJECT
            else f"update__{encoded}__"
        )
        row_views.append(
            {
                "candidate": row.candidate,
                "values": {**dict(row.values), **_fields_for_prefix(values, value_prefix)},
                "association_identity": row.association_identity,
                "concurrency_token": row.concurrency_token,
            }
        )
    draft_rows: dict[str, dict[str, object]] = {}
    for name, value in values.items():
        if not name.startswith("create__"):
            continue
        parts = name.split("__", 2)
        if len(parts) == 3 and parts[1].startswith("new-"):
            draft_rows.setdefault(parts[1], {})[parts[2]] = value
    start = max(page - 1, 0) * editor.candidate_page_size
    paginated_rows = tuple(row_views[start : start + editor.candidate_page_size])
    token = (
        await editor.state_provider.issue_concurrency_token(parent_identity, editor.relationship_id)
        if parent_identity is not None and editor.editable
        else None
    )
    options_by_identity = {
        IdentityCodec().encode(option.identity): option
        for option in await _candidate_options(editor, query=None, page=page)
    }
    # A currently scoped member remains renderable even when it falls outside
    # the bounded candidate page used by a native select.
    for row in rows:
        options_by_identity.setdefault(
            IdentityCodec().encode(row.candidate.identity), row.candidate
        )
    page_path = None
    if parent_identity is not None:
        encoded_parent = IdentityCodec().encode(parent_identity)
        page_path = editor.relationship.route_path.replace("{identity}", encoded_parent)
    return {
        "relationship": definition,
        "relationship_id": editor.relationship_id,
        "prefix": prefix,
        "rows": paginated_rows,
        "draft_rows": tuple(
            {"key": key, "values": row_values} for key, row_values in draft_rows.items()
        ),
        "selected": selected,
        "options": tuple(options_by_identity.values()),
        "concurrency_token": token,
        "reorderable": editor.relationship.ordering is not None,
        "page": page,
        "has_previous_page": page > 1,
        "has_next_page": start + editor.candidate_page_size < len(row_views),
        "page_path": page_path,
        "options_path": f"{page_path}/options" if page_path is not None else None,
        "new_row_key": f"new-{uuid4()}",
        "inline_fields": tuple(
            field.field_id
            for field in (
                editor.association_form_schema.fields
                if definition.kind is RelationshipKind.ASSOCIATION_OBJECT
                and editor.association_form_schema is not None
                else (
                    editor.target_form_schema.fields
                    if editor.target_form_schema is not None
                    else ()
                )
            )
            if field.writable and field.readable and not field.sensitive
        ),
    }


async def render_relationship_panels(
    binding: RelationshipFormBinding | None,
    *,
    parent_identity: RecordIdentity | None,
    submitted: Mapping[str, object] = {},
) -> dict[str, dict[str, object]]:
    if binding is None:
        return {}
    return {
        editor.relationship_id: await relationship_panel_view(
            editor, parent_identity=parent_identity, submitted=submitted
        )
        for editor in binding.editors
        if editor.relationship.definition.edit_mode is not RelationshipEditMode.HIDDEN
    }


async def _authorize_editor(
    binding: Any,
    request: Request,
    editor: RelationshipEditorBinding,
    parent_identity: RecordIdentity,
) -> bool:
    """Require both the normal parent write surface and exact relationship permission."""

    if not await binding.authorize(request):
        return False
    authorizer = getattr(binding, "relationship_editor_authorizer", None)
    return bool(
        callable(authorizer) and await authorizer(request, editor.relationship_id, parent_identity)
    )


def build_relationship_routes(
    binding: Any,
    relationship_binding: RelationshipFormBinding,
) -> list[Route]:
    """Build scoped, render-only helper routes under compiled ownership paths."""

    routes: list[Route] = []
    for editor in relationship_binding.editors:
        route_path = editor.relationship.route_path

        async def options(request: Request, editor: RelationshipEditorBinding = editor) -> Response:
            identity = binding.codec.decode(request.path_params["identity"])
            if not await _authorize_editor(binding, request, editor, identity):
                return PlainTextResponse("Forbidden", status_code=403)
            if (
                not callable(getattr(binding.mutation_service, "get", None))
                or await binding.mutation_service.get(identity) is None
            ):
                return PlainTextResponse("Resource was not found", status_code=404)
            options = await _candidate_options(editor, query=request.query_params.get("q"))
            selected = {
                name.removeprefix(f"{relationship_prefix(editor.relationship_id)}target__")
                for name in request.query_params
                if name.startswith(f"{relationship_prefix(editor.relationship_id)}target__")
            }
            return binding.templates.TemplateResponse(
                request,
                "relationships/options.html",
                {
                    "options": options,
                    "codec": relationship_binding.codec,
                    "prefix": relationship_prefix(editor.relationship_id),
                    "selected": selected,
                    "options_id": f"rakit-relationship-{editor.relationship_id}-options",
                },
                headers={"Cache-Control": "no-store"},
            )

        async def page(request: Request, editor: RelationshipEditorBinding = editor) -> Response:
            identity = binding.codec.decode(request.path_params["identity"])
            if not await _authorize_editor(
                binding, request, editor, identity
            ) or not await binding.verify_csrf(request):
                return PlainTextResponse("Forbidden", status_code=403)
            form = await request.form(max_files=0, max_fields=_MAX_FRAGMENT_FIELDS)
            submitted = {
                name: value
                for name, value in form.multi_items()
                if isinstance(name, str) and isinstance(value, str)
            }
            split_relationship_submission(relationship_binding, submitted)
            if (
                not callable(getattr(binding.mutation_service, "get", None))
                or await binding.mutation_service.get(identity) is None
            ):
                return PlainTextResponse("Resource was not found", status_code=404)
            panel = await relationship_panel_view(
                editor,
                parent_identity=identity,
                submitted=submitted,
                page=int(request.path_params["page"]),
            )
            return binding.templates.TemplateResponse(
                request,
                "relationships/panel.html",
                {"panel": panel, "codec": relationship_binding.codec},
                headers={"Cache-Control": "no-store"},
            )

        routes.extend(
            (
                Route(
                    f"{route_path}/options",
                    options,
                    methods=["GET"],
                    name=f"relationship:{editor.relationship.source_resource_id}:{editor.relationship_id}:options",
                ),
                Route(
                    f"{route_path}/page/{{page:int}}",
                    page,
                    methods=["POST"],
                    name=f"relationship:{editor.relationship.source_resource_id}:{editor.relationship_id}:page",
                ),
            )
        )
    return routes


__all__ = [
    "RelationshipEditorBinding",
    "RelationshipEditorStateProvider",
    "RelationshipFormBinding",
    "build_relationship_changes",
    "build_relationship_routes",
    "relationship_prefix",
    "render_relationship_panels",
    "split_relationship_submission",
]
