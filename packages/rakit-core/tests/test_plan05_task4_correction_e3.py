"""Correction E3: advanced action results remain durable AUTO successes."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from rakit_core.actions import (
    ActionAdvancedResponse,
    ActionContext,
    ActionDefinition,
    ActionResponseKind,
    ActionScope,
    PreparedMutationExecutor,
    action_permission_requirement,
    build_action_operation_plan,
)
from rakit_core.events import EventPublisher
from rakit_core.mutations import OperationAuthorization
from rakit_core.operations import CancellationContext, OperationContext, run_operation_plan
from rakit_core.transactions import (
    OperationUnitOfWorkFactory,
    TransactionPolicy,
)


class _TrackingUnitOfWork:
    def __init__(self, policy: TransactionPolicy) -> None:
        self.policy = policy
        self.marked_success = False
        self.committed = False
        self.rolled_back = False

    async def mark_success(self) -> None:
        self.marked_success = True

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self, cause: BaseException | None = None) -> None:
        del cause
        self.rolled_back = True


class _TrackingUnitOfWorkFactory:
    def __init__(self) -> None:
        self.uow: _TrackingUnitOfWork | None = None

    @asynccontextmanager
    async def open(
        self,
        *,
        policy: TransactionPolicy,
        event_publisher: EventPublisher | None,
        operation_context: OperationContext,
    ) -> AsyncIterator[_TrackingUnitOfWork]:
        del event_publisher, operation_context
        uow = _TrackingUnitOfWork(policy)
        self.uow = uow
        try:
            yield uow
        except BaseException as exc:
            await uow.rollback(exc)
            raise
        else:
            if uow.marked_success:
                await uow.commit()
            else:
                await uow.rollback()


@pytest.mark.anyio
async def test_advanced_action_result_marks_auto_uow_success() -> None:
    permission = action_permission_requirement("export", admin_id="ops")
    authorization = OperationAuthorization.for_requirement(
        admin_id="ops",
        resource_id="tools",
        operation="action:export",
        principal_id="tester",
        requirement=permission,
        target_identity=None,
    )

    def prepare(_context: ActionContext) -> object:
        return object()

    def commit(_prepared: object, _context: ActionContext) -> ActionAdvancedResponse:
        return ActionAdvancedResponse(
            kind=ActionResponseKind.FILE,
            payload={"filename": "orders.csv"},
        )

    action = ActionDefinition(
        action_id="export",
        label="Export",
        scope=ActionScope.PAGE,
        page_id="tools",
        permission=permission,
        executor=PreparedMutationExecutor(prepare, commit),
        mutating=True,
        transaction_policy=TransactionPolicy.AUTO,
    )
    action_context = ActionContext(
        definition=action,
        scope=ActionScope.PAGE,
        authorization=authorization,
    )
    plan = build_action_operation_plan(action_context)
    operation_context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        principal_id="tester",
        admin_id="ops",
        resource_id="tools",
        operation="action:export",
        permissions=authorization.permissions,
        permission_requirement=permission,
    )
    factory = _TrackingUnitOfWorkFactory()

    result = await run_operation_plan(
        plan,
        operation_context,
        unit_of_work_factory=cast(OperationUnitOfWorkFactory, factory),
    )

    assert isinstance(result, ActionAdvancedResponse)
    assert result.kind is ActionResponseKind.FILE
    assert factory.uow is not None
    assert factory.uow.marked_success is True
    assert factory.uow.committed is True
    assert factory.uow.rolled_back is False
