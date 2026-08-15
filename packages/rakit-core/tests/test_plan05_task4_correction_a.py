"""PLAN 05 TASK 4 CORRECTION A: one canonical ``ActionDefinition`` contract.

Every supported import path -- ``rakit_core.actions``, the compatibility
re-export ``rakit_core.definitions``, and the public ``rakit`` facade --
must resolve to the same class, and the compiler, permission catalogue, and
web runtime must all consume that one contract.  The web-level fail-closed
property (BULK is definition-only, never bindable) is covered by
``rakit-web``'s ``test_actions.py``.
"""

import pytest
from rakit_core.actions import (
    ActionDefinition,
    ActionPreview,
    ActionPreviewResolver,
    ActionRedirect,
    ActionScope,
    ActionSuccess,
    DomainActionExecutor,
)
from rakit_core.bulk import BulkExecutionPolicy, BulkPolicy
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import (
    ActionDefinition as DefinitionsActionDefinition,
)
from rakit_core.definitions import (
    ResourceDefinition,
    ResourceFieldPolicy,
)
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_core.identity import RecordIdentity
from rakit_core.permission_catalogue import generate_permission_catalogue
from rakit_core.permissions import PermissionRequirement
from rakit_core.query import PageResult, ResourceQuery
from rakit_core.transactions import TransactionPolicy


class _DataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query: ResourceQuery) -> PageResult:  # pragma: no cover
        raise AssertionError

    async def count(self, query: ResourceQuery) -> int:  # pragma: no cover
        raise AssertionError

    async def detail(self, identity: RecordIdentity) -> object:  # pragma: no cover
        raise AssertionError


def _resource(resource_id: str, path: str) -> ResourceDefinition:
    return ResourceDefinition(
        resource_id=resource_id,
        path=path,
        label=resource_id.title(),
        singular_label=resource_id.title(),
        field_policy=ResourceFieldPolicy(list_fields=("id",), detail_fields=("id",)),
    )


def _executor() -> DomainActionExecutor:
    return DomainActionExecutor(lambda _context: ActionSuccess())


def _preview(context: object) -> ActionPreview:
    return ActionPreview(title="Preview", description="Preview description")


def _definition(
    *,
    action_id: str = "approve",
    label: str = "Approve",
    scope: ActionScope = ActionScope.RECORD,
    resource_id: str = "orders",
    page_id: str | None = None,
    permission: PermissionRequirement | None = None,
    input_schema: FormSchema | None = None,
    preview: ActionPreviewResolver | None = None,
    needs_form: bool = False,
    needs_preview: bool = False,
    needs_confirmation: bool = False,
    mutating: bool = False,
    transaction_policy: TransactionPolicy = TransactionPolicy.READ_ONLY,
    bulk_policy: BulkPolicy | None = None,
) -> ActionDefinition:
    return ActionDefinition(
        action_id=action_id,
        label=label,
        scope=scope,
        resource_id=resource_id,
        page_id=page_id,
        permission=permission,
        input_schema=input_schema,
        preview=preview,
        needs_form=needs_form,
        needs_preview=needs_preview,
        needs_confirmation=needs_confirmation,
        mutating=mutating,
        transaction_policy=transaction_policy,
        bulk_policy=bulk_policy,
        executor=_executor(),
    )


def test_action_definition_is_one_canonical_type_across_import_paths() -> None:
    assert ActionDefinition is DefinitionsActionDefinition


def test_compiler_consumes_canonical_action_definition() -> None:
    builder = ApplicationBuilder(admin_id="ops")
    builder.add_resource(_resource("orders", "/orders"), _DataSource())
    action = _definition(action_id="approve", scope=ActionScope.RECORD)
    builder.add_action(action)

    compiled = compile_application(builder)

    assert compiled.actions == (action,)
    compiled_action = compiled.compiled_actions[0]
    assert isinstance(compiled_action.definition, ActionDefinition)
    assert compiled_action.definition is action
    assert compiled_action.permission == PermissionRequirement.all_of("ops.actions.approve.execute")
    assert any(route.path == "/orders/{identity}/_actions/approve" for route in compiled.routes)


def test_permission_catalogue_consumes_canonical_action_definition() -> None:
    action = _definition(action_id="approve", scope=ActionScope.RECORD)

    catalogue = generate_permission_catalogue(
        admin_id="ops", admin_label="Operations", actions=(action,)
    )

    keys = {definition.key for definition in catalogue.definitions}
    assert "ops.access" in keys
    assert "ops.actions.approve.execute" in keys


def test_page_scope_requires_page_owner_only() -> None:
    with pytest.raises(ValueError, match="page_id"):
        ActionDefinition(action_id="p1", label="P1", scope=ActionScope.PAGE, executor=_executor())
    with pytest.raises(ValueError, match="cannot also declare resource_id"):
        ActionDefinition(
            action_id="p1",
            label="P1",
            scope=ActionScope.PAGE,
            page_id="admin",
            resource_id="orders",
            executor=_executor(),
        )

    page_action = ActionDefinition(
        action_id="p1",
        label="P1",
        scope=ActionScope.PAGE,
        page_id="admin",
        executor=_executor(),
    )
    assert page_action.page_id == "admin"
    assert page_action.resource_id is None


def test_resource_and_record_scope_require_resource_owner_only() -> None:
    for scope in (ActionScope.RESOURCE, ActionScope.RECORD):
        with pytest.raises(ValueError, match="require resource_id"):
            ActionDefinition(action_id="a", label="A", scope=scope, executor=_executor())
        with pytest.raises(ValueError, match="Only PAGE"):
            ActionDefinition(
                action_id="a",
                label="A",
                scope=scope,
                resource_id="orders",
                page_id="admin",
                executor=_executor(),
            )

    record_action = _definition(action_id="approve", scope=ActionScope.RECORD)
    assert record_action.resource_id == "orders"
    assert record_action.page_id is None


def test_bulk_scope_defaults_policy_and_rejects_non_bulk_policy() -> None:
    bulk = ActionDefinition(
        action_id="bulk_archive",
        label="Bulk archive",
        scope=ActionScope.BULK,
        resource_id="orders",
        executor=_executor(),
    )
    assert bulk.bulk_policy is not None
    assert bulk.bulk_policy.execution is BulkExecutionPolicy.ATOMIC

    with pytest.raises(ValueError, match="Only BULK"):
        ActionDefinition(
            action_id="a",
            label="A",
            scope=ActionScope.RECORD,
            resource_id="orders",
            executor=_executor(),
            bulk_policy=BulkPolicy(),
        )


def test_mutating_transaction_semantics_are_retained() -> None:
    with pytest.raises(ValueError, match="read-only"):
        _definition(mutating=True)
    with pytest.raises(ValueError, match="automatic write"):
        _definition(transaction_policy=TransactionPolicy.AUTO)

    mutating = _definition(mutating=True, transaction_policy=TransactionPolicy.AUTO)
    assert mutating.mutating is True
    assert mutating.transaction_policy is TransactionPolicy.AUTO


def test_executor_is_required() -> None:
    with pytest.raises(ValueError, match="requires an executor"):
        ActionDefinition(
            action_id="approve",
            label="Approve",
            scope=ActionScope.RECORD,
            resource_id="orders",
        )


def test_form_preview_confirmation_contract_is_retained() -> None:
    with pytest.raises(ValueError, match="needs a form"):
        _definition(needs_form=True)
    with pytest.raises(ValueError, match="preview resolver"):
        _definition(needs_preview=True)
    with pytest.raises(ValueError, match="preview step"):
        _definition(needs_confirmation=True)
    typed_confirmation_schema = FormSchema(
        fields=(FieldDefinition(field_id="reason", python_type=str, required=True),)
    )
    typed_confirmation = _definition(
        needs_form=True,
        needs_confirmation=True,
        needs_preview=True,
        preview=_preview,
        input_schema=typed_confirmation_schema,
    )
    assert typed_confirmation.input_schema is typed_confirmation_schema

    with pytest.raises(ValueError, match="typed confirmation requires a form step"):
        _definition(
            needs_confirmation=True,
            needs_preview=True,
            preview=_preview,
            input_schema=typed_confirmation_schema,
        )

    unsafe_schema = FormSchema(
        fields=(
            FieldDefinition(
                field_id="opaque",
                python_type=str,
                readable=False,
                writable=True,
            ),
        )
    )
    with pytest.raises(ValueError, match="hidden or sensitive writable fields"):
        _definition(
            needs_form=True,
            needs_confirmation=True,
            needs_preview=True,
            preview=_preview,
            input_schema=unsafe_schema,
        )

    schema = FormSchema(
        fields=(FieldDefinition(field_id="reason", python_type=str, required=True, label="Reason"),)
    )
    formed = _definition(needs_form=True, input_schema=schema)
    assert formed.input_schema is schema
    assert formed.needs_form is True


def test_bulk_actions_compile_to_definitions_with_default_policy() -> None:
    builder = ApplicationBuilder(admin_id="ops")
    builder.add_resource(_resource("orders", "/orders"), _DataSource())
    bulk = ActionDefinition(
        action_id="bulk_archive",
        label="Bulk archive",
        scope=ActionScope.BULK,
        resource_id="orders",
        executor=_executor(),
    )
    builder.add_action(bulk)

    compiled = compile_application(builder)

    assert any(action.action_id == "bulk_archive" for action in compiled.actions)
    compiled_bulk = next(
        compiled_action
        for compiled_action in compiled.compiled_actions
        if compiled_action.definition.action_id == "bulk_archive"
    )
    assert compiled_bulk.definition.bulk_policy is not None


@pytest.mark.parametrize(
    "location",
    (
        "/",
        "/orders/1",
        "/orders/1?tab=history",
        "/orders/1#events",
    ),
)
def test_action_redirect_accepts_internal_application_paths(location: str) -> None:
    assert ActionRedirect(location=location).location == location


@pytest.mark.parametrize(
    "location",
    (
        "",
        "orders/1",
        "//evil.example",
        "///evil.example",
        "https://evil.example",
        "/\\evil.example",
        "/orders\r\nLocation: https://evil.example",
        "/orders\x00evil",
        "/orders\x7fevil",
    ),
)
def test_action_redirect_rejects_unsafe_locations(location: str) -> None:
    with pytest.raises(ValueError):
        ActionRedirect(location=location)
