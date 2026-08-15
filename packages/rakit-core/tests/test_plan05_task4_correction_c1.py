"""PLAN 05 TASK 4 CORRECTION C1: canonical action OperationPlan mapping.

``build_action_operation_plan`` maps a prepared ``ActionContext`` onto the
generic ``OperationPlan`` seam; ``execute_operation_plan`` is the single
application execution boundary (RBAC never re-run in core).
"""

import pytest
from rakit_core.actions import (
    ActionContext,
    ActionDefinition,
    ActionPreview,
    ActionScope,
    ActionSuccess,
    DomainActionExecutor,
    build_action_operation_plan,
)
from rakit_core.auth import Principal
from rakit_core.errors import RakitError
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_core.operations import (
    CancellationContext,
    OperationContext,
    OperationKind,
    activate_operation_context,
    execute_operation_plan,
)
from rakit_core.permissions import PermissionRequirement
from rakit_core.transactions import TransactionPolicy


def _executor() -> DomainActionExecutor:
    return DomainActionExecutor(lambda _context: ActionSuccess(payload={"ok": True}))


def _authorization(
    *,
    resource_id: str = "orders",
    operation: str = "action:approve",
    principal_id: str = "operator",
    requirement: PermissionRequirement | None = None,
    target_identity: RecordIdentity | None = None,
) -> OperationAuthorization:
    return OperationAuthorization.for_requirement(
        admin_id="ops",
        resource_id=resource_id,
        operation=operation,
        principal_id=principal_id,
        requirement=requirement or PermissionRequirement.all_of("ops.actions.approve.execute"),
        target_identity=target_identity,
    )


def _record_action() -> ActionDefinition:
    return ActionDefinition(
        action_id="approve",
        label="Approve",
        scope=ActionScope.RECORD,
        resource_id="orders",
        mutating=True,
        transaction_policy=TransactionPolicy.AUTO,
        requires_concurrency=True,
        needs_confirmation=True,
        needs_preview=True,
        preview=lambda _context: ActionPreview(title="Approve", description="Approve order"),
        executor=_executor(),
    )


def _record_context() -> ActionContext:
    identity = RecordIdentity(values={"id": 7})
    return ActionContext(
        definition=_record_action(),
        scope=ActionScope.RECORD,
        identity=identity,
        record=object(),
        authorization=_authorization(target_identity=identity),
    )


def _operation_context(
    context: ActionContext,
) -> OperationContext:
    assert context.authorization is not None
    return OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        request_id="req-1",
        operation_id="op-1",
        principal=Principal(subject_id="operator", authenticated=True),
        principal_id="operator",
        admin_id=context.authorization.admin_id,
        resource_id=context.authorization.resource_id,
        operation=context.authorization.operation,
        permissions=context.authorization.permissions,
        permission_requirement=context.authorization.requirement,
    )


def test_plan_kind_and_operation_id() -> None:
    plan = build_action_operation_plan(_record_context())
    assert plan.kind is OperationKind.ACTION
    assert plan.operation_id == "approve"


def test_plan_carries_exact_authorization_capability() -> None:
    context = _record_context()
    plan = build_action_operation_plan(context)
    assert plan.authorization is context.authorization
    assert plan.authorization is not None
    assert plan.authorization.permissions == ("ops.actions.approve.execute",)


def test_record_target_identity_is_carried() -> None:
    context = _record_context()
    plan = build_action_operation_plan(context)
    assert plan.target_identity == context.identity == RecordIdentity(values={"id": 7})


def test_resource_and_page_actions_have_no_target_identity() -> None:
    for scope, definition in (
        (
            ActionScope.RESOURCE,
            ActionDefinition(
                action_id="export",
                label="Export",
                scope=ActionScope.RESOURCE,
                resource_id="orders",
                executor=_executor(),
            ),
        ),
        (
            ActionScope.PAGE,
            ActionDefinition(
                action_id="refresh",
                label="Refresh",
                scope=ActionScope.PAGE,
                page_id="report",
                executor=_executor(),
            ),
        ),
    ):
        context = ActionContext(
            definition=definition,
            scope=scope,
            authorization=_authorization(
                resource_id="orders" if scope is ActionScope.RESOURCE else "report",
                operation=f"action:{definition.action_id}",
                requirement=PermissionRequirement.all_of(
                    f"ops.actions.{definition.action_id}.execute"
                ),
            ),
        )
        plan = build_action_operation_plan(context)
        assert plan.target_identity is None


def test_transaction_metadata_is_preserved_exactly() -> None:
    mutating = build_action_operation_plan(_record_context())
    assert mutating.mutating is True
    assert mutating.transaction_policy is TransactionPolicy.AUTO

    read_only = ActionContext(
        definition=ActionDefinition(
            action_id="export",
            label="Export",
            scope=ActionScope.RESOURCE,
            resource_id="orders",
            executor=_executor(),
        ),
        scope=ActionScope.RESOURCE,
        authorization=_authorization(
            resource_id="orders",
            operation="action:export",
            requirement=PermissionRequirement.all_of("ops.actions.export.execute"),
        ),
    )
    plan = build_action_operation_plan(read_only)
    assert plan.mutating is False
    assert plan.transaction_policy is TransactionPolicy.READ_ONLY


def test_concurrency_and_confirmation_flags_map() -> None:
    plan = build_action_operation_plan(_record_context())
    assert plan.concurrency_required is True
    assert plan.confirmation_required is True

    plain = ActionContext(
        definition=ActionDefinition(
            action_id="export",
            label="Export",
            scope=ActionScope.RESOURCE,
            resource_id="orders",
            executor=_executor(),
        ),
        scope=ActionScope.RESOURCE,
        authorization=_authorization(
            resource_id="orders",
            operation="action:export",
            requirement=PermissionRequirement.all_of("ops.actions.export.execute"),
        ),
    )
    assert build_action_operation_plan(plain).concurrency_required is False
    assert build_action_operation_plan(plain).confirmation_required is False


def test_idempotency_fingerprint_is_carried_byte_for_byte() -> None:
    plan = build_action_operation_plan(_record_context(), idempotency_fingerprint="fp-123")
    assert plan.idempotency_fingerprint == "fp-123"


@pytest.mark.anyio
async def test_execute_operation_plan_invokes_executor_once() -> None:
    calls: list[int] = []

    async def handler(_context: ActionContext) -> ActionSuccess:
        calls.append(1)
        return ActionSuccess(payload={"ok": True})

    action = ActionDefinition(
        action_id="approve",
        label="Approve",
        scope=ActionScope.RECORD,
        resource_id="orders",
        executor=DomainActionExecutor(handler),
    )
    identity = RecordIdentity(values={"id": 7})
    context = ActionContext(
        definition=action,
        scope=ActionScope.RECORD,
        identity=identity,
        record=object(),
        authorization=_authorization(target_identity=identity),
    )
    plan = build_action_operation_plan(context)
    operation_context = _operation_context(context)

    with activate_operation_context(operation_context):
        result = await execute_operation_plan(plan, operation_context)

    assert isinstance(result, ActionSuccess)
    assert result.payload == {"ok": True}
    assert calls == [1]


def test_plan_fails_closed_on_invalid_contexts() -> None:
    identity = RecordIdentity(values={"id": 7})
    with pytest.raises(ValueError, match="executor"):
        build_action_operation_plan(
            ActionContext(
                definition=ActionDefinition(
                    action_id="approve",
                    label="Approve",
                    scope=ActionScope.RECORD,
                    resource_id="orders",
                ),
                scope=ActionScope.RECORD,
                identity=identity,
                authorization=_authorization(target_identity=identity),
            )
        )
    with pytest.raises(ValueError, match="authorization"):
        build_action_operation_plan(
            ActionContext(
                definition=_record_action(),
                scope=ActionScope.RECORD,
                identity=identity,
                authorization=None,
            )
        )
    with pytest.raises(ValueError, match="target does not match"):
        build_action_operation_plan(
            ActionContext(
                definition=_record_action(),
                scope=ActionScope.RECORD,
                identity=RecordIdentity(values={"id": 8}),
                authorization=_authorization(target_identity=RecordIdentity(values={"id": 9})),
            )
        )
    with pytest.raises(ValueError, match="requires a record identity"):
        build_action_operation_plan(
            ActionContext(
                definition=_record_action(),
                scope=ActionScope.RECORD,
                identity=None,
                authorization=_authorization(target_identity=None),
            )
        )
    with pytest.raises(ValueError, match="cannot carry a record identity"):
        build_action_operation_plan(
            ActionContext(
                definition=ActionDefinition(
                    action_id="export",
                    label="Export",
                    scope=ActionScope.RESOURCE,
                    resource_id="orders",
                    executor=_executor(),
                ),
                scope=ActionScope.RESOURCE,
                identity=identity,
                authorization=_authorization(
                    resource_id="orders",
                    operation="action:export",
                    requirement=PermissionRequirement.all_of("ops.actions.export.execute"),
                    target_identity=identity,
                ),
            )
        )


@pytest.mark.anyio
async def test_plan_execution_rejects_mismatched_context() -> None:
    context = _record_context()
    plan = build_action_operation_plan(context)

    mismatched = _operation_context(context)
    mismatched = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        request_id="req-1",
        operation_id="op-1",
        principal=Principal(subject_id="intruder", authenticated=True),
        principal_id="intruder",
        admin_id=mismatched.admin_id,
        resource_id=mismatched.resource_id,
        operation=mismatched.operation,
        permissions=mismatched.permissions,
        permission_requirement=mismatched.permission_requirement,
    )
    with pytest.raises(RakitError), activate_operation_context(mismatched):
        await execute_operation_plan(plan, mismatched)

    wrong_resource = _operation_context(context)
    wrong_resource = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        request_id="req-1",
        operation_id="op-1",
        principal=Principal(subject_id="operator", authenticated=True),
        principal_id="operator",
        admin_id=wrong_resource.admin_id,
        resource_id="customers",
        operation=wrong_resource.operation,
        permissions=wrong_resource.permissions,
        permission_requirement=wrong_resource.permission_requirement,
    )
    with pytest.raises(RakitError), activate_operation_context(wrong_resource):
        await execute_operation_plan(plan, wrong_resource)

    wrong_operation = _operation_context(context)
    wrong_operation = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        request_id="req-1",
        operation_id="op-1",
        principal=Principal(subject_id="operator", authenticated=True),
        principal_id="operator",
        admin_id=wrong_operation.admin_id,
        resource_id=wrong_operation.resource_id,
        operation="action:export",
        permissions=wrong_operation.permissions,
        permission_requirement=wrong_operation.permission_requirement,
    )
    with pytest.raises(RakitError), activate_operation_context(wrong_operation):
        await execute_operation_plan(plan, wrong_operation)
