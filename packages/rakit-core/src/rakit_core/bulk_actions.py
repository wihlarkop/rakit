"""Operation-plan builders for synchronous Plan 05 bulk actions."""

from collections.abc import Awaitable
from typing import Any, cast

from .actions import (
    ActionContext,
    ActionRejected,
    ActionResult,
    ActionScope,
    ActionSuccess,
    ActionValidation,
)
from .bulk import (
    BulkActionOutcome,
    BulkExecutionPolicy,
    BulkItemOutcome,
    BulkItemStatus,
)
from .errors import ErrorCode, RakitError
from .mutations import OperationAuthorization
from .operations import (
    OperationContext,
    OperationExecutor,
    OperationKind,
    OperationPlan,
    resolve_operation_executor_capabilities,
    validate_operation_transaction_contract,
)
from .transactions import TransactionPolicy


def _require_bulk_context(context: ActionContext) -> None:
    if context.definition.scope is not ActionScope.BULK:
        raise ValueError("Bulk operation plans require a BULK action")
    if context.identity is None or context.record is None:
        raise ValueError("Bulk target contexts require a scoped identity and record")
    authorization = context.authorization
    if authorization is None:
        raise ValueError("Bulk target contexts require authorization")
    if authorization.target_identity != context.identity:
        raise ValueError("Bulk target authorization must bind the selected identity")
    if authorization.resource_id != context.definition.resource_id:
        raise ValueError("Bulk target authorization must bind the owning resource")
    if authorization.operation != f"action:{context.definition.action_id}":
        raise ValueError("Bulk target authorization must bind the action operation")


def _require_root_capability(
    context: ActionContext,
    root: OperationAuthorization,
) -> None:
    authorization = context.authorization
    assert authorization is not None
    if (
        authorization.admin_id != root.admin_id
        or authorization.resource_id != root.resource_id
        or authorization.operation != root.operation
        or authorization.principal_id != root.principal_id
        or authorization.requirement != root.requirement
    ):
        raise ValueError("Bulk target authorization must match the root action capability")


def _item_outcome(context: ActionContext, result: ActionResult[Any]) -> BulkItemOutcome:
    assert context.identity is not None
    if isinstance(result, ActionSuccess):
        return BulkItemOutcome(
            identity=context.identity,
            status=BulkItemStatus.SUCCEEDED,
            message=result.message,
        )
    if isinstance(result, ActionRejected):
        return BulkItemOutcome(
            identity=context.identity,
            status=BulkItemStatus.REJECTED,
            message=result.message,
            errors=result.errors,
        )
    if isinstance(result, ActionValidation):
        return BulkItemOutcome(
            identity=context.identity,
            status=BulkItemStatus.REJECTED,
            message="Validation failed",
            errors={
                str(issue.field_id): issue.message
                for issue in result.issues
                if issue.field_id is not None
            },
        )
    raise RakitError(
        code=ErrorCode.CONFIG_INVALID,
        message=(
            "Bulk action executors must return ActionSuccess, ActionRejected, "
            "or ActionValidation for each selected target."
        ),
        status_code=500,
        details={
            "action_id": context.definition.action_id,
            "reason": "unsupported_bulk_item_result",
            "result_type": type(result).__name__,
        },
    )


def build_bulk_target_operation_plan(
    context: ActionContext,
    *,
    idempotency_fingerprint: str | None = None,
) -> OperationPlan[ActionContext, ActionResult[Any]]:
    """Build one independently durable target operation for BEST_EFFORT execution."""

    _require_bulk_context(context)
    action = context.definition
    assert action.executor is not None
    assert context.authorization is not None
    executor = action.executor

    def execute(
        _operation_context: OperationContext,
        target_context: ActionContext,
    ) -> Awaitable[ActionResult[Any]]:
        return executor.execute(target_context)

    plan_execute: OperationExecutor[ActionContext, ActionResult[Any]] = execute
    plan = cast(
        OperationPlan[ActionContext, ActionResult[Any]],
        OperationPlan(
            operation_id=f"{action.action_id}:target",
            kind=OperationKind.ACTION,
            input=context,
            authorization=context.authorization,
            target_identity=context.identity,
            mutating=action.mutating,
            transaction_policy=action.transaction_policy,
            idempotency_fingerprint=idempotency_fingerprint,
            executor_capabilities=resolve_operation_executor_capabilities(executor),
            result_is_success=lambda result: isinstance(result, ActionSuccess),
            execute=plan_execute,
        ),
    )
    validate_operation_transaction_contract(plan)
    return plan


def build_atomic_bulk_operation_plan(
    contexts: tuple[ActionContext, ...],
    *,
    authorization: OperationAuthorization,
    idempotency_fingerprint: str | None = None,
) -> OperationPlan[tuple[ActionContext, ...], BulkActionOutcome]:
    """Build one root operation whose selected targets share one durable outcome."""

    if not contexts:
        raise ValueError("Atomic bulk execution requires at least one target")
    for context in contexts:
        _require_bulk_context(context)
    action = contexts[0].definition
    if any(context.definition is not action for context in contexts):
        raise ValueError("Atomic bulk target contexts must share one action definition")
    if authorization.target_identity is not None:
        raise ValueError("Atomic bulk root authorization cannot bind one target identity")
    if authorization.resource_id != action.resource_id:
        raise ValueError("Atomic bulk root authorization must bind the owning resource")
    if authorization.operation != f"action:{action.action_id}":
        raise ValueError("Atomic bulk root authorization must bind the action operation")
    for context in contexts:
        _require_root_capability(context, authorization)
    if action.mutating and action.transaction_policy is not TransactionPolicy.AUTO:
        raise ValueError("Mutating ATOMIC bulk actions require TransactionPolicy.AUTO")
    assert action.executor is not None
    executor = action.executor

    async def execute(
        _operation_context: OperationContext,
        target_contexts: tuple[ActionContext, ...],
    ) -> BulkActionOutcome:
        items: list[BulkItemOutcome] = []
        for index, target_context in enumerate(target_contexts):
            result = await executor.execute(target_context)
            item = _item_outcome(target_context, result)
            items.append(item)
            if item.status is not BulkItemStatus.SUCCEEDED:
                items.extend(
                    BulkItemOutcome(
                        identity=remaining.identity,
                        status=BulkItemStatus.SKIPPED,
                        message="Skipped because atomic bulk execution was rejected",
                    )
                    for remaining in target_contexts[index + 1 :]
                    if remaining.identity is not None
                )
                break
        return BulkActionOutcome(execution=BulkExecutionPolicy.ATOMIC, items=tuple(items))

    plan_execute: OperationExecutor[tuple[ActionContext, ...], BulkActionOutcome] = execute
    plan = OperationPlan(
        operation_id=action.action_id,
        kind=OperationKind.ACTION,
        input=contexts,
        authorization=authorization,
        target_identity=None,
        mutating=action.mutating,
        transaction_policy=action.transaction_policy,
        idempotency_fingerprint=idempotency_fingerprint,
        executor_capabilities=resolve_operation_executor_capabilities(executor),
        result_is_success=lambda outcome: outcome.all_succeeded,
        execute=plan_execute,
    )
    validate_operation_transaction_contract(plan)
    return plan


def bulk_item_outcome(context: ActionContext, result: ActionResult[Any]) -> BulkItemOutcome:
    """Normalize one BEST_EFFORT target result without exposing arbitrary payloads."""

    _require_bulk_context(context)
    return _item_outcome(context, result)


__all__ = [
    "build_atomic_bulk_operation_plan",
    "build_bulk_target_operation_plan",
    "bulk_item_outcome",
]
