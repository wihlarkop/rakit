"""Thin form-state routes and parsers for compiled relationship editors.

Relationship writes never happen here.  This module converts normal form
controls into the sealed typed graph steps and offers read-only HTMX helpers
for scoped candidates and relationship panels.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, cast
from uuid import uuid4

from rakit_core.errors import ErrorCode, RakitError
from rakit_core.forms import FormSchema, FormValidationError
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_core.operations import (
    CancellationContext,
    OperationContext,
    activate_operation_context,
    new_operation_id,
)
from rakit_core.query import PageResult, ResourceQuery
from rakit_core.relationship_mutations import (
    ClearRelated,
    CreateRelated,
    DeleteRelated,
    LinkRelated,
    RelationshipCandidate,
    RelationshipChangePlan,
    RelationshipEditorRow,
    RelationshipMutationKind,
    RelationshipMutationPlan,
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
    async def editor_page(
        self,
        parent_identity: RecordIdentity,
        relationship_id: str,
        *,
        child_fields: tuple[str, ...] = (),
        page: int = 1,
        per_page: int = 25,
    ) -> PageResult[RelationshipEditorRow]: ...

    async def issue_concurrency_token(
        self, parent_identity: RecordIdentity, relationship_id: str
    ) -> str: ...

    async def reorder_identities(
        self,
        parent_identity: RecordIdentity,
        relationship_id: str,
        *,
        maximum: int,
    ) -> tuple[RecordIdentity, ...] | None: ...


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
    reorder_safe_maximum: int = 100

    def __post_init__(self) -> None:
        definition = self.relationship.definition
        if self.candidate_page_size < 1 or self.candidate_page_size > 200:
            raise ValueError("candidate_page_size must be between 1 and 200")
        if self.reorder_safe_maximum < 1 or self.reorder_safe_maximum > 1_000:
            raise ValueError("reorder_safe_maximum must be between 1 and 1000")
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


def _identity_key(identity: RecordIdentity) -> str:
    return json.dumps(dict(identity.values), sort_keys=True, separators=(",", ":"))


def _relationship_intent_fingerprint(values: Mapping[str, object]) -> str:
    """A UI-only invalidation marker; signed backend claims remain authoritative."""

    relevant = {
        name: value
        for name, value in values.items()
        if name
        not in {
            "destructive_confirmation",
            "confirmation_intent",
            "confirmation_impact",
        }
        and not name.startswith("delete__")
    }
    encoded = json.dumps(relevant, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _preview_plan(
    editor: RelationshipEditorBinding,
    parent_identity: RecordIdentity,
    change: RelationshipChangePlan,
) -> RelationshipMutationPlan | None:
    """Adapt only the destructive graph steps to the sealed relationship preview API."""

    sets = [step for step in change.steps if isinstance(step, SetRelated)]
    clears = [step for step in change.steps if isinstance(step, ClearRelated)]
    unlinks = [step for step in change.steps if isinstance(step, UnlinkRelated)]
    if sets:
        kind, targets = RelationshipMutationKind.SET, (sets[-1].identity,)
    elif clears:
        kind, targets = RelationshipMutationKind.CLEAR, ()
    elif unlinks:
        kind, targets = RelationshipMutationKind.REMOVE, tuple(step.identity for step in unlinks)
    else:
        return None
    return RelationshipMutationPlan(
        operation_id=change.operation_id,
        parent_resource_id=editor.relationship.source_resource_id,
        parent_identity=parent_identity,
        relationship_id=editor.relationship_id,
        kind=kind,
        target_identities=targets,
        authorization_requirement=editor.relationship.mutation_permission,
        concurrency_token=change.concurrency_token,
    )


async def _preview_context(
    binding: Any,
    request: Request,
    editor: RelationshipEditorBinding,
    parent_identity: RecordIdentity,
    change: RelationshipChangePlan,
) -> tuple[OperationAuthorization, Any]:
    """Reuse the normal graph authorization bundle for a read-only preview."""

    root_authorizer = getattr(binding, "mutation_authorizer", None)
    graph_authorizer = getattr(binding, "graph_mutation_authorizer", None)
    if not callable(root_authorizer) or not callable(graph_authorizer):
        raise RakitError(
            code=ErrorCode.AUTH_FORBIDDEN,
            message="Relationship preview is not authorized.",
            status_code=403,
        )
    root = await root_authorizer(request, "update", parent_identity)
    if root is None:
        raise RakitError(code=ErrorCode.AUTH_FORBIDDEN, message="Forbidden", status_code=403)
    authorizations = await graph_authorizer(request, root, parent_identity, (change,))
    if authorizations is None:
        raise RakitError(code=ErrorCode.AUTH_FORBIDDEN, message="Forbidden", status_code=403)
    try:
        return (
            authorizations.require(
                resource_id=editor.relationship.source_resource_id,
                operation=change.operation_id,
                requirement=editor.relationship.mutation_permission,
                target_identity=parent_identity,
            ),
            authorizations,
        )
    except ValueError as exc:
        raise RakitError(
            code=ErrorCode.AUTH_FORBIDDEN, message="Forbidden", status_code=403
        ) from exc


async def _with_preview_context(
    request: Request,
    authorization: OperationAuthorization,
    awaitable: Any,
) -> Any:
    """A read-only exact relationship capability, without a persistence UoW."""

    context = OperationContext(
        deadline=None,
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
    )
    with activate_operation_context(context):
        return await awaitable


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
        if name in {
            "concurrency",
            "destructive_confirmation",
            "confirmation_intent",
            "confirmation_impact",
            "search",
            "delete_preview",
        }:
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
            and name.startswith(("link__", "unlink__"))
            and name.partition("__")[2]
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
        if name.startswith("delete_intent__") and name.removeprefix("delete_intent__"):
            continue
        if name.startswith("delete_impact__") and name.removeprefix("delete_impact__"):
            continue
        if (
            editor.relationship.ordering is not None
            and name.startswith("order__")
            and name.removeprefix("order__")
        ):
            continue
        if name.startswith("move__"):
            parts = name.split("__", 2)
            if (
                editor.relationship.ordering is not None
                and len(parts) == 3
                and parts[2] in {"up", "down"}
            ):
                continue
        if name.startswith("issue__"):
            parts = name.split("__", 2)
            if (
                len(parts) == 3
                and parts[1]
                and (
                    (parts[1] == "panel" and parts[2] == "panel")
                    or parts[2] in target_fields
                    or parts[2] in association_fields
                )
            ):
                continue
        raise _invalid_relationship_field()


def _schema_values(
    schema: FormSchema,
    values: Mapping[str, object],
    *,
    relationship_id: str,
    row_key: str,
    association: bool = False,
) -> Mapping[str, Any]:
    try:
        return schema.parse(values).normalized
    except FormValidationError as exc:
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="Inline relationship fields are invalid.",
            status_code=422,
            details={
                "relationship_issue": {
                    "relationship_id": relationship_id,
                    "row_key": row_key,
                    "kind": "association_field" if association else "field",
                    "issues": tuple(
                        {"field_id": issue.field_id, "message": issue.message}
                        for issue in exc.state.issues
                    ),
                }
            },
        ) from exc


async def build_relationship_changes(
    binding: RelationshipFormBinding,
    submitted: Mapping[str, object],
    *,
    parent_identity: RecordIdentity | None,
    allow_unconfirmed_delete: bool = False,
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
        steps: list[object] = []
        for name, value in values.items():
            if name.startswith("link__"):
                steps.append(LinkRelated(identity=_identity(binding.codec, value)))
            elif name.startswith("unlink__"):
                steps.append(UnlinkRelated(identity=_identity(binding.codec, value)))

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
                        CreateRelated(
                            values=_schema_values(
                                editor.target_form_schema,
                                row_values,
                                relationship_id=editor.relationship_id,
                                row_key=row_key,
                            )
                        )
                    )
            update_ids = {
                name.split("__", 2)[1]
                for name in values
                if name.startswith("update__") and len(name.split("__", 2)) == 3
            }
            for encoded in update_ids:
                row_values = _fields_for_prefix(values, f"update__{encoded}__")
                if row_values:
                    token = values.get(f"update_token__{encoded}")
                    steps.append(
                        UpdateRelated(
                            identity=_identity(binding.codec, encoded),
                            values=_schema_values(
                                editor.target_form_schema,
                                row_values,
                                relationship_id=editor.relationship_id,
                                row_key=encoded,
                            ),
                            concurrency_token=token if isinstance(token, str) else None,
                        )
                    )

        if editor.association_form_schema is not None:
            association_ids = {
                name.split("__", 2)[1]
                for name in values
                if name.startswith("association__") and len(name.split("__", 2)) == 3
            }
            for encoded in association_ids:
                association_values = _fields_for_prefix(values, f"association__{encoded}__")
                if association_values:
                    steps.append(
                        UpdateAssociationRelated(
                            target_identity=_identity(binding.codec, encoded),
                            association_identity=None,
                            values=_schema_values(
                                editor.association_form_schema,
                                association_values,
                                relationship_id=editor.relationship_id,
                                row_key=encoded,
                                association=True,
                            ),
                        )
                    )

        for name, confirmation in values.items():
            if name.startswith("delete_intent__") and confirmation:
                encoded = name.removeprefix("delete_intent__")
                confirmation = values.get(f"delete__{encoded}")
                if not isinstance(confirmation, str):
                    if allow_unconfirmed_delete:
                        continue
                    raise RakitError(
                        code=ErrorCode.VALIDATION_FAILED,
                        message="Deleting this child requires a current deletion confirmation.",
                        status_code=422,
                        details={
                            "relationship_issue": {
                                "relationship_id": editor.relationship_id,
                                "row_key": encoded,
                                "kind": "row",
                                "message": "Deletion confirmation is required.",
                            }
                        },
                    )
                steps.append(
                    DeleteRelated(
                        identity=_identity(binding.codec, encoded), confirmation_token=confirmation
                    )
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
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Reorder requires a complete relationship ordering state.",
                status_code=422,
            )
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
            if parent_identity is None:
                raise _invalid_relationship_field()
            complete_order = await editor.state_provider.reorder_identities(
                parent_identity,
                editor.relationship_id,
                maximum=editor.reorder_safe_maximum,
            )
            decoded_order = tuple(_identity(binding.codec, encoded) for encoded in order_values)
            if (
                complete_order is None
                or len(decoded_order) != len(complete_order)
                or len({_identity_key(identity) for identity in decoded_order})
                != len(decoded_order)
                or {_identity_key(identity) for identity in decoded_order}
                != {_identity_key(identity) for identity in complete_order}
            ):
                raise RakitError(
                    code=ErrorCode.VALIDATION_FAILED,
                    message="Relationship reorder requires a complete current ordering state.",
                    status_code=422,
                )
            steps.append(ReorderRelated(identities=decoded_order))

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
    issues: tuple[Mapping[str, object], ...] = (),
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
    editor_page = (
        await editor.state_provider.editor_page(
            parent_identity,
            editor.relationship_id,
            child_fields=child_fields,
            page=page,
            per_page=editor.candidate_page_size,
        )
        if parent_identity is not None and definition.readable
        else PageResult(
            items=(),
            page=page,
            per_page=editor.candidate_page_size,
            has_previous=False,
            has_next=False,
        )
    )
    rows = editor_page.items
    prefix = relationship_prefix(editor.relationship_id)
    values = _fields_for_prefix(submitted, prefix)
    pending_links = {name.removeprefix("link__") for name in values if name.startswith("link__")}
    pending_unlinks = {
        name.removeprefix("unlink__") for name in values if name.startswith("unlink__")
    }
    complete_order: tuple[RecordIdentity, ...] | None = None
    if parent_identity is not None and editor.relationship.ordering is not None:
        complete_order = await editor.state_provider.reorder_identities(
            parent_identity,
            editor.relationship_id,
            maximum=editor.reorder_safe_maximum,
        )
    submitted_order = [
        value
        for _, value in sorted(
            (name, value) for name, value in values.items() if name.startswith("order__")
        )
        if isinstance(value, str)
    ]
    complete_order_values = (
        tuple(IdentityCodec().encode(identity) for identity in complete_order)
        if complete_order is not None
        else ()
    )
    reorderable = bool(
        complete_order_values
        and len(submitted_order) in {0, len(complete_order_values)}
        and (
            not submitted_order
            or submitted_order == list(complete_order_values)
            or set(submitted_order) == set(complete_order_values)
        )
    )
    order_values = (
        tuple(submitted_order) if reorderable and submitted_order else complete_order_values
    )
    confirmation_intent = _relationship_intent_fingerprint(values)
    confirmation = values.get("destructive_confirmation")
    confirmation_current = (
        isinstance(confirmation, str) and values.get("confirmation_intent") == confirmation_intent
    )
    row_views: list[dict[str, object]] = []
    rendered_names: set[str] = {
        "concurrency",
        "selection_present",
        "search",
        "destructive_confirmation",
        "confirmation_intent",
        "confirmation_impact",
    }
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
                "delete_confirmation": values.get(f"delete__{encoded}"),
                "delete_intent": bool(values.get(f"delete_intent__{encoded}")),
                "delete_impact": values.get(f"delete_impact__{encoded}"),
            }
        )
        rendered_names.add(f"unlink__{encoded}")
        rendered_names.add(f"delete_intent__{encoded}")
        rendered_names.add(f"delete__{encoded}")
        rendered_names.add(f"delete_impact__{encoded}")
        rendered_names.add(f"update_token__{encoded}")
        for field_id in row.values:
            rendered_names.add(f"{value_prefix}{field_id}")
    draft_rows: dict[str, dict[str, object]] = {}
    for name, value in values.items():
        if not name.startswith("create__"):
            continue
        parts = name.split("__", 2)
        if len(parts) == 3 and parts[1].startswith("new-"):
            draft_rows.setdefault(parts[1], {})[parts[2]] = value
            rendered_names.add(name)
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
    issue_map: dict[tuple[str | None, str | None], list[str]] = {}
    panel_issues: list[str] = []
    for issue in issues:
        if issue.get("relationship_id") != editor.relationship_id:
            continue
        row_key = issue.get("row_key")
        field_id = issue.get("field_id")
        message = issue.get("message")
        if isinstance(message, str):
            if row_key is None and field_id is None:
                panel_issues.append(message)
            else:
                issue_map.setdefault(
                    (
                        str(row_key) if row_key is not None else None,
                        str(field_id) if field_id else None,
                    ),
                    [],
                ).append(message)
    for name, message in values.items():
        if not name.startswith("issue__") or not isinstance(message, str):
            continue
        parts = name.split("__", 2)
        if len(parts) == 3:
            if parts[1] == "panel" and parts[2] == "panel":
                panel_issues.append(message)
            else:
                issue_map.setdefault((parts[1], parts[2]), []).append(message)
    error_inputs = (
        *({"name": "issue__panel__panel", "value": message} for message in panel_issues),
        *(
            {
                "name": f"issue__{row_key or 'panel'}__{field_id or 'panel'}",
                "value": message,
            }
            for (row_key, field_id), messages in issue_map.items()
            for message in messages
        ),
    )
    return {
        "relationship": definition,
        "relationship_id": editor.relationship_id,
        "prefix": prefix,
        "rows": tuple(row_views),
        "draft_rows": tuple(
            {"key": key, "values": row_values} for key, row_values in draft_rows.items()
        ),
        "selected": pending_links,
        "pending_unlinks": pending_unlinks,
        "options": tuple(options_by_identity.values()),
        "concurrency_token": token,
        "reorderable": reorderable,
        "order_values": order_values,
        "reorder_unavailable": (
            editor.relationship.ordering is not None and complete_order is None
        ),
        "confirmation": confirmation if confirmation_current else None,
        "confirmation_intent": confirmation_intent if confirmation_current else None,
        "confirmation_impact": values.get("confirmation_impact") if confirmation_current else None,
        "delete_available": bool(
            definition.destructive_policy.allow_child_delete
            and editor.relationship.target_delete_permission is not None
            and callable(getattr(editor.state_provider, "issue_child_delete_confirmation", None))
            and callable(getattr(editor.state_provider, "preview_child_delete", None))
        ),
        "panel_issues": tuple(panel_issues),
        "relationship_issues": issue_map,
        "error_inputs": error_inputs,
        "page": page,
        "total_label": (
            f"{editor_page.total_count} items"
            if editor_page.total_count is not None
            else (f"Page {page}" if editor_page.has_previous or editor_page.has_next else "")
        ),
        "total_pages": (
            (editor_page.total_count + editor_page.per_page - 1) // editor_page.per_page
            if editor_page.total_count is not None
            else None
        ),
        "has_previous_page": editor_page.has_previous,
        "has_next_page": editor_page.has_next,
        "page_path": page_path,
        "preview_path": f"{page_path}/preview" if page_path is not None else None,
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
        "pending_inputs": tuple(
            {"name": name, "value": value}
            for name, value in values.items()
            if name not in rendered_names
        ),
    }


async def render_relationship_panels(
    binding: RelationshipFormBinding | None,
    *,
    parent_identity: RecordIdentity | None,
    submitted: Mapping[str, object] = {},
    issues: tuple[Mapping[str, object], ...] = (),
) -> dict[str, dict[str, object]]:
    if binding is None:
        return {}
    return {
        editor.relationship_id: await relationship_panel_view(
            editor, parent_identity=parent_identity, submitted=submitted, issues=issues
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
                name.removeprefix(f"{relationship_prefix(editor.relationship_id)}link__")
                for name in request.query_params
                if name.startswith(f"{relationship_prefix(editor.relationship_id)}link__")
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

        async def preview(request: Request, editor: RelationshipEditorBinding = editor) -> Response:
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
            try:
                split_relationship_submission(relationship_binding, submitted)
                changes = await build_relationship_changes(
                    relationship_binding,
                    submitted,
                    parent_identity=identity,
                    allow_unconfirmed_delete=True,
                )
                change = next(
                    (item for item in changes if item.relationship_id == editor.relationship_id),
                    None,
                )
                dialog_context: dict[str, object] | None = None
                active_delete = submitted.get(
                    f"{relationship_prefix(editor.relationship_id)}delete_preview"
                )
                if active_delete is not None:
                    if not isinstance(active_delete, str):
                        raise _invalid_relationship_field()
                    issue = getattr(editor.state_provider, "issue_child_delete_confirmation", None)
                    preview_delete = getattr(editor.state_provider, "preview_child_delete", None)
                    if not callable(issue) or not callable(preview_delete):
                        raise RakitError(
                            code=ErrorCode.CONFIG_INVALID,
                            message="Inline child deletion is not supported by this relationship.",
                            status_code=500,
                        )
                    encoded = active_delete
                    child = _identity(relationship_binding.codec, encoded)
                    delete_change = RelationshipChangePlan(
                        operation_id=f"relationship:{editor.relationship_id}",
                        relationship_id=editor.relationship_id,
                        steps=(DeleteRelated(identity=child, confirmation_token="preview"),),
                        authorization_requirement=editor.relationship.mutation_permission,
                    )
                    _, authorizations = await _preview_context(
                        binding, request, editor, identity, delete_change
                    )
                    target_requirement = editor.relationship.target_delete_permission
                    if target_requirement is None:
                        raise RakitError(
                            code=ErrorCode.AUTH_FORBIDDEN,
                            message="Relationship child deletion is not authorized.",
                            status_code=403,
                        )
                    try:
                        authorizations.require(
                            resource_id=str(editor.relationship.definition.target_resource_id),
                            operation=f"{delete_change.operation_id}:target-delete",
                            requirement=target_requirement,
                            target_identity=child,
                        )
                    except ValueError as exc:
                        raise RakitError(
                            code=ErrorCode.AUTH_FORBIDDEN,
                            message="Relationship child deletion is not authorized.",
                            status_code=403,
                        ) from exc
                    # Membership is resolved by the adapter before it previews the child.
                    child_preview = await preview_delete(identity, editor.relationship_id, child)
                    confirmation = await issue(identity, editor.relationship_id, child)
                    impact = getattr(child_preview, "relationship_impact", ())
                    dialog_context = {
                        "prefix": relationship_prefix(editor.relationship_id),
                        "delete_identity": encoded,
                        "confirmation": confirmation,
                        "confirmation_intent": "",
                        "impact": ", ".join(str(item) for item in impact)
                        or "No additional cascade impact.",
                        "title": f"Delete {editor.relationship.definition.label.rstrip('s')}?",
                        "description": "This item will be marked for deletion.",
                        "confirm_label": "Mark for deletion",
                        "resource_label": binding.label,
                    }
                else:
                    if change is None:
                        raise RakitError(
                            code=ErrorCode.VALIDATION_FAILED,
                            message="Choose a relationship change before requesting confirmation.",
                            status_code=422,
                        )
                    plan = _preview_plan(editor, identity, change)
                    if plan is None:
                        raise RakitError(
                            code=ErrorCode.VALIDATION_FAILED,
                            message=(
                                "This relationship change has no destructive impact to confirm."
                            ),
                            status_code=422,
                        )
                    capability, _ = await _preview_context(
                        binding, request, editor, identity, change
                    )
                    preview_impact = getattr(
                        editor.state_provider, "preview_destructive_impact", None
                    )
                    issue = getattr(editor.state_provider, "issue_destructive_confirmation", None)
                    if not callable(preview_impact) or not callable(issue):
                        raise RakitError(
                            code=ErrorCode.CONFIG_INVALID,
                            message="Relationship destructive preview is not available.",
                            status_code=500,
                        )
                    impact = await _with_preview_context(
                        request, capability, preview_impact(plan, authorization=capability)
                    )
                    if not impact:
                        raise RakitError(
                            code=ErrorCode.VALIDATION_FAILED,
                            message=(
                                "This relationship change is not destructive and does not need "
                                "confirmation."
                            ),
                            status_code=422,
                        )
                    confirmation = await _with_preview_context(
                        request, capability, issue(plan, authorization=capability)
                    )
                    confirmation_intent = _relationship_intent_fingerprint(
                        _fields_for_prefix(submitted, relationship_prefix(editor.relationship_id))
                    )
                    dialog_context = {
                        "prefix": relationship_prefix(editor.relationship_id),
                        "delete_identity": None,
                        "confirmation": confirmation,
                        "confirmation_intent": confirmation_intent,
                        "impact": str(len(impact)),
                        "title": f"Review {editor.relationship.definition.label} change",
                        "description": "The relationship change has a destructive impact.",
                        "confirm_label": "Confirm change",
                        "resource_label": binding.label,
                    }
                if dialog_context is not None:
                    return binding.templates.TemplateResponse(
                        request,
                        "relationships/preview_dialog.html",
                        dialog_context,
                        headers={"Cache-Control": "no-store"},
                    )
                panel = await relationship_panel_view(
                    editor,
                    parent_identity=identity,
                    submitted=submitted,
                    page=int(request.query_params.get("page", "1")),
                )
                return binding.templates.TemplateResponse(
                    request,
                    "relationships/panel.html",
                    {"panel": panel, "codec": relationship_binding.codec},
                    headers={"Cache-Control": "no-store"},
                )
            except (RakitError, ValueError) as exc:
                message = (
                    exc.message
                    if isinstance(exc, RakitError)
                    else "Invalid relationship confirmation request"
                )
                return PlainTextResponse(message, status_code=getattr(exc, "status_code", 422))

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
                Route(
                    f"{route_path}/preview",
                    preview,
                    methods=["POST"],
                    name=f"relationship:{editor.relationship.source_resource_id}:{editor.relationship_id}:preview",
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
