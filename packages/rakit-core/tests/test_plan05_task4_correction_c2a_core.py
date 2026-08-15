"""Plan 05 Task 4 Correction C2A: generic operation transaction lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from rakit_core.actions import ActionSuccess, DomainActionExecutor, PreparedMutationExecutor
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.mutations import OperationAuthorization
from rakit_core.operations import (
    CancellationContext,
    OperationContext,
    OperationExecutorCapabilities,
    OperationKind,
    OperationPlan,
    activate_operation_context,
    current_operation_context,
    resolve_operation_executor_capabilities,
    run_operation_plan,
)
from rakit_core.permissions import PermissionRequirement
from rakit_core.transactions import TransactionPolicy

_MANAGED_EXECUTOR_CAPABILITIES = OperationExecutorCapabilities(participates_in_uow=True)


@dataclass
class _FakeUnitOfWork:
    policy: TransactionPolicy
    success_marks: int = 0
    commits: int = 0
    rollbacks: int = 0
    completed: bool = False

    async def __aenter__(self) -> _FakeUnitOfWork:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            if not self.completed:
                await self.rollback(exc)
        elif self.policy is TransactionPolicy.AUTO and self.success_marks and not self.completed:
            self.commits += 1
            self.completed = True
        elif not self.completed:
            await self.rollback()
        return False

    async def mark_success(self) -> None:
        self.success_marks += 1

    async def commit(self) -> None:
        if self.policy is not TransactionPolicy.MANUAL:
            raise RuntimeError("explicit commit requires MANUAL")
        self.commits += 1
        self.completed = True

    async def rollback(self, cause: BaseException | None = None) -> None:
        self.rollbacks += 1
        self.completed = True


class _FakeFactory:
    def __init__(self) -> None:
        self.opened: list[_FakeUnitOfWork] = []

    def open(self, *, policy, event_publisher, operation_context):
        uow = _FakeUnitOfWork(policy=policy)
        self.opened.append(uow)
        return uow


def _authorization(operation: str = "action:approve") -> OperationAuthorization:
    return OperationAuthorization.for_requirement(
        admin_id="ops",
        resource_id="orders",
        operation=operation,
        principal_id="operator",
        requirement=PermissionRequirement.all_of("ops.actions.approve.execute"),
    )


def _context(operation: str = "action:approve") -> OperationContext:
    authorization = _authorization(operation)
    return OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        operation_id="request-operation",
        principal_id="operator",
        admin_id="ops",
        resource_id="orders",
        operation=operation,
        permissions=authorization.permissions,
        permission_requirement=authorization.requirement,
    )


def _plan(
    execute,
    *,
    policy: TransactionPolicy = TransactionPolicy.AUTO,
    capabilities: OperationExecutorCapabilities | None = None,
    success=lambda result: result == "ok",
    concurrency: bool = False,
) -> OperationPlan[None, str]:
    return OperationPlan(
        operation_id="approve",
        kind=OperationKind.ACTION,
        input=None,
        authorization=_authorization(),
        execute=execute,
        mutating=policy is not TransactionPolicy.READ_ONLY,
        transaction_policy=policy,
        concurrency_required=concurrency,
        executor_capabilities=(
            capabilities if capabilities is not None else _MANAGED_EXECUTOR_CAPABILITIES
        ),
        result_is_success=success,
    )


def test_executor_capability_contract_is_fail_closed() -> None:
    assert resolve_operation_executor_capabilities(object()) == OperationExecutorCapabilities()
    assert (
        resolve_operation_executor_capabilities(
            DomainActionExecutor(lambda _context: ActionSuccess())
        )
        == OperationExecutorCapabilities()
    )
    assert resolve_operation_executor_capabilities(
        PreparedMutationExecutor(lambda _context: {}, lambda _plan, _context: ActionSuccess())
    ) == OperationExecutorCapabilities(participates_in_uow=True)
    with pytest.raises(ValueError, match="Atomic concurrency"):
        OperationExecutorCapabilities(atomic_concurrency=True)


@pytest.mark.anyio
async def test_auto_success_marks_root_uow_and_commits() -> None:
    seen: list[object] = []
    context = _context()

    async def execute(operation_context: OperationContext, _input: None) -> str:
        assert current_operation_context() is operation_context is context
        assert operation_context.unit_of_work is not None
        seen.append(operation_context.unit_of_work)
        return "ok"

    factory = _FakeFactory()
    with activate_operation_context(context):
        result = await run_operation_plan(_plan(execute), context, unit_of_work_factory=factory)

    assert current_operation_context() is None
    assert result == "ok"
    assert len(factory.opened) == 1
    assert seen == [factory.opened[0]]
    assert factory.opened[0].success_marks == 1
    assert factory.opened[0].commits == 1
    assert factory.opened[0].rollbacks == 0
    assert context.unit_of_work is None


@pytest.mark.anyio
async def test_auto_unsuccessful_result_rolls_back_without_success_mark() -> None:
    async def execute(_context: OperationContext, _input: None) -> str:
        return "rejected"

    factory = _FakeFactory()
    result = await run_operation_plan(_plan(execute), _context(), unit_of_work_factory=factory)

    assert result == "rejected"
    assert factory.opened[0].success_marks == 0
    assert factory.opened[0].commits == 0
    assert factory.opened[0].rollbacks == 1


@pytest.mark.anyio
async def test_auto_exception_rolls_back() -> None:
    async def execute(_context: OperationContext, _input: None) -> str:
        raise RuntimeError("boom")

    factory = _FakeFactory()
    with pytest.raises(RuntimeError, match="boom"):
        await run_operation_plan(_plan(execute), _context(), unit_of_work_factory=factory)

    assert factory.opened[0].success_marks == 0
    assert factory.opened[0].commits == 0
    assert factory.opened[0].rollbacks == 1


@pytest.mark.anyio
async def test_manual_commit_is_explicit_and_no_completion_rolls_back() -> None:
    async def committed(context: OperationContext, _input: None) -> str:
        assert context.unit_of_work is not None
        await context.unit_of_work.commit()
        return "ok"

    committed_factory = _FakeFactory()
    await run_operation_plan(
        _plan(committed, policy=TransactionPolicy.MANUAL),
        _context(),
        unit_of_work_factory=committed_factory,
    )
    assert committed_factory.opened[0].success_marks == 0
    assert committed_factory.opened[0].commits == 1
    assert committed_factory.opened[0].rollbacks == 0

    async def incomplete(_context: OperationContext, _input: None) -> str:
        return "ok"

    incomplete_factory = _FakeFactory()
    await run_operation_plan(
        _plan(incomplete, policy=TransactionPolicy.MANUAL),
        _context(),
        unit_of_work_factory=incomplete_factory,
    )
    assert incomplete_factory.opened[0].commits == 0
    assert incomplete_factory.opened[0].rollbacks == 1


@pytest.mark.anyio
async def test_read_only_and_disabled_do_not_require_uow_factory() -> None:
    async def execute(context: OperationContext, _input: None) -> str:
        assert context.unit_of_work is None
        return "ok"

    read_authorization = _authorization("action:read")
    read_only = OperationPlan(
        operation_id="read",
        kind=OperationKind.ACTION,
        input=None,
        authorization=read_authorization,
        execute=execute,
        transaction_policy=TransactionPolicy.READ_ONLY,
    )
    read_context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        operation_id="read-op",
        principal_id="operator",
        admin_id="ops",
        resource_id="orders",
        operation="action:read",
        permissions=read_authorization.permissions,
        permission_requirement=read_authorization.requirement,
    )
    assert await run_operation_plan(read_only, read_context, unit_of_work_factory=None) == "ok"

    disabled = _plan(
        execute,
        policy=TransactionPolicy.DISABLED,
        capabilities=OperationExecutorCapabilities(),
    )
    assert await run_operation_plan(disabled, _context(), unit_of_work_factory=None) == "ok"


@pytest.mark.anyio
async def test_auto_requires_managed_executor_and_registered_uow() -> None:
    async def execute(_context: OperationContext, _input: None) -> str:
        return "ok"

    unmanaged = _plan(execute, capabilities=OperationExecutorCapabilities())
    with pytest.raises(RakitError) as unmanaged_error:
        await run_operation_plan(unmanaged, _context(), unit_of_work_factory=_FakeFactory())
    assert unmanaged_error.value.code == ErrorCode.CONFIG_INVALID
    assert unmanaged_error.value.details["reason"] == "executor_not_uow_managed"

    managed = _plan(execute)
    with pytest.raises(RakitError, match="unit-of-work provider"):
        await run_operation_plan(managed, _context(), unit_of_work_factory=None)


@pytest.mark.anyio
async def test_strong_concurrency_rejects_precheck_only_executor() -> None:
    async def execute(_context: OperationContext, _input: None) -> str:
        return "ok"

    plan = _plan(
        execute,
        concurrency=True,
        capabilities=OperationExecutorCapabilities(participates_in_uow=True),
    )
    with pytest.raises(RakitError) as caught:
        await run_operation_plan(plan, _context(), unit_of_work_factory=_FakeFactory())
    assert caught.value.code == ErrorCode.CONFIG_INVALID
    assert caught.value.details["reason"] == "atomic_concurrency_not_supported"
